#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LZR-001 - Media Vault Auto-Sync for GitHub API
Automated downloader and GitHub uploader for https://ak.xworms.xyz/api.php?action=list&sync=1
"""

import os
import sys
import json
import time
import re
import argparse
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

# Ensure UTF-8 output on Windows terminals
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_URL_DEFAULT = "https://ak.xworms.xyz/api.php?action=list&sync=1"
HISTORY_FILE = "sync_history.json"
MAX_GITHUB_GIT_FILE_SIZE = 95 * 1024 * 1024  # 95 MB threshold for git commits
MAX_RELEASE_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB limit for release assets


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames and HTTP headers."""
    # Remove characters illegal in Windows/Linux filenames: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    # Normalize multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "unnamed_media"


class GitHubSyncEngine:
    def __init__(
        self,
        token: str,
        repo: str,
        api_url: str = API_URL_DEFAULT,
        release_tag: str = "media-vault",
        mode: str = "release",
        proxy: Optional[str] = None,
        max_files: Optional[int] = None,
        dry_run: bool = False,
    ):
        self.token = token.strip()
        self.repo = repo.strip()  # Format: "owner/repo"
        self.api_url = api_url
        self.release_tag = release_tag
        self.mode = mode
        self.proxy = proxy
        self.max_files = max_files
        self.dry_run = dry_run

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        })
        if self.proxy:
            self.session.proxies.update({
                "http": self.proxy,
                "https": self.proxy,
            })

        self.gh_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        self.history = self._load_history()

    def _load_history(self) -> Dict[str, Any]:
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[!] Warning reading {HISTORY_FILE}: {e}")
        return {"synced_files": {}, "last_run": None}

    def _save_history(self):
        self.history["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def fetch_media_list(self) -> List[Dict[str, Any]]:
        """Fetch list of files from source API with local cache fallback."""
        print(f"[*] Fetching media list from: {self.api_url}")
        try:
            res = self.session.get(self.api_url, timeout=20)
            if res.status_code == 200:
                data = res.json()
                files = data.get("files", [])
                print(f"[+] Total files in API: {len(files)}")
                return files
            else:
                print(f"[!] Warning: API returned HTTP {res.status_code} (Cloudflare block).")
        except Exception as e:
            print(f"[!] Warning: Failed to connect to API: {e}")

        # Fallback to cached API list if available
        cache_file = Path("cached_api_list.json")
        if cache_file.exists():
            print(f"[*] Using local cache: {cache_file.name}")
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                files = data.get("files", [])
                print(f"[+] Loaded {len(files)} files from cache.")
                return files

        raise RuntimeError("Could not retrieve media list from API or cache.")

    def get_or_create_release(self) -> Dict[str, Any]:
        """Fetch existing release by tag or create a new one."""
        url = f"https://api.github.com/repos/{self.repo}/releases/tags/{self.release_tag}"
        res = requests.get(url, headers=self.gh_headers, timeout=20)

        if res.status_code == 200:
            print(f"[+] Found existing GitHub Release: {self.release_tag}")
            return res.json()
        elif res.status_code == 404:
            print(f"[*] Release '{self.release_tag}' not found. Creating new release...")
            create_url = f"https://api.github.com/repos/{self.repo}/releases"
            payload = {
                "tag_name": self.release_tag,
                "name": f"Media Vault ({self.release_tag})",
                "body": "Automated sync storage for media archives.",
                "draft": False,
                "prerelease": False,
            }
            create_res = requests.post(create_url, headers=self.gh_headers, json=payload, timeout=20)
            if create_res.status_code in [200, 201]:
                print(f"[+] Release created successfully!")
                return create_res.json()
            else:
                raise RuntimeError(f"Failed to create release: {create_res.status_code} - {create_res.text}")
        else:
            raise RuntimeError(f"GitHub API error fetching release: {res.status_code} - {res.text}")

    def get_existing_release_assets(self, release: Dict[str, Any]) -> set:
        """Get set of existing asset names in release to avoid re-uploading."""
        assets = release.get("assets", [])
        return {a["name"] for a in assets}

    def upload_to_release(self, upload_url_template: str, file_path: Path, asset_name: str) -> Optional[str]:
        """Upload file as a GitHub Release Asset."""
        # upload_url format is: https://uploads.github.com/repos/{owner}/{repo}/releases/{id}/assets{?name,label}
        upload_url = upload_url_template.split("{")[0]
        params = {"name": asset_name}
        file_size = file_path.stat().st_size

        print(f"[*] Uploading to GitHub Release: {asset_name} ({file_size / (1024*1024):.2f} MB)...")

        headers = self.gh_headers.copy()
        headers["Content-Type"] = "application/octet-stream"
        headers["Content-Length"] = str(file_size)

        with open(file_path, "rb") as f:
            res = requests.post(
                upload_url,
                params=params,
                headers=headers,
                data=f,
                timeout=600,
            )

        if res.status_code in [200, 201]:
            data = res.json()
            download_url = data.get("browser_download_url")
            print(f"[+] Upload successful! Asset URL: {download_url}")
            return download_url
        else:
            print(f"[!] Upload failed (HTTP {res.status_code}): {res.text}")
            return None

    def download_file(self, url: str, dest_path: Path, expected_size: Optional[int] = None) -> bool:
        """Download file with streaming and basic retry."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[*] Downloading: {dest_path.name}")

        try:
            with self.session.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = 0
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                        if chunk:
                            f.write(chunk)
                            total += len(chunk)
            print(f"[+] Download complete: {dest_path.name} ({total / (1024*1024):.2f} MB)")
            return True
        except Exception as e:
            print(f"[!] Download failed for {url}: {e}")
            if dest_path.exists():
                dest_path.unlink()
            return False

    def run(self):
        files = self.fetch_media_list()
        if not files:
            print("[-] No files found to sync.")
            return

        temp_dir = Path("./temp_downloads")
        temp_dir.mkdir(parents=True, exist_ok=True)

        existing_assets = set()
        upload_url = ""
        if self.mode == "release":
            release = self.get_or_create_release()
            upload_url = release.get("upload_url", "")
            existing_assets = self.get_existing_release_assets(release)
            print(f"[*] Found {len(existing_assets)} existing assets in Release.")

        processed_count = 0

        for item in files:
            if self.max_files and processed_count >= self.max_files:
                print(f"[*] Reached limit of {self.max_files} files.")
                break

            name = item.get("name", "video")
            ext = item.get("ext", "mp4").strip(".")
            url = item.get("url", "").replace(r"\/", "/")
            size = item.get("size", 0)

            safe_name = sanitize_filename(f"{name}.{ext}")

            # Check if already synced in history or release assets
            if safe_name in self.history["synced_files"] or safe_name in existing_assets:
                # Already processed
                continue

            print(f"\n--- [{processed_count + 1}] Processing: {safe_name} ({size / (1024*1024):.2f} MB) ---")

            if self.dry_run:
                print(f"[DRY-RUN] Would download from {url} and upload as {safe_name}")
                processed_count += 1
                continue

            # Check size limits
            if self.mode == "release" and size > MAX_RELEASE_FILE_SIZE:
                print(f"[!] Skipping: File exceeds GitHub Release max size of 2GB.")
                continue

            local_file = temp_dir / safe_name
            success = self.download_file(url, local_file, expected_size=size)
            if not success:
                continue

            try:
                if self.mode == "release":
                    asset_url = self.upload_to_release(upload_url, local_file, safe_name)
                    if asset_url:
                        self.history["synced_files"][safe_name] = {
                            "size": size,
                            "url": asset_url,
                            "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        self._save_history()
                        processed_count += 1
                else:
                    dest_file = Path("./downloads") / safe_name
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    local_file.rename(dest_file)
                    print(f"[*] Saved to: {dest_file}")
                    self.history["synced_files"][safe_name] = {
                        "size": size,
                        "path": str(dest_file),
                        "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    self._save_history()
                    processed_count += 1
            finally:
                # Remove temporary local file only if still in temp_dir
                if local_file.exists() and self.mode == "release":
                    local_file.unlink()
                    print(f"[+] Cleaned temp file: {local_file.name}")

        print(f"\n[+] Batch complete. Total newly synced files: {processed_count}")


def load_env_file():
    """Load key-value pairs from .env file into os.environ if present."""
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception as e:
            print(f"[!] Warning reading .env: {e}")


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description="Auto-sync media from API to GitHub")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub Personal Access Token")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPO"), help="Target GitHub repo (e.g. username/repo-name)")
    parser.add_argument("--api", default=os.getenv("MEDIA_API_URL", API_URL_DEFAULT), help="Source API URL")
    parser.add_argument("--tag", default=os.getenv("RELEASE_TAG", "media-vault"), help="GitHub Release tag name")
    parser.add_argument("--mode", default="release", choices=["release", "local"], help="Sync destination mode")
    parser.add_argument("--proxy", default=os.getenv("PROXY_URL"), help="Proxy URL (e.g. http://127.0.0.1:7890)")
    parser.add_argument("--limit", type=int, default=None, help="Max files to sync in this run")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without downloading/uploading")

    args = parser.parse_args()

    token = args.token
    repo = args.repo

    if args.mode == "release":
        if not token and sys.stdin.isatty():
            try:
                token = input("กรุณาใส่ GitHub Token: ").strip()
            except (EOFError, KeyboardInterrupt):
                pass
        if not repo and sys.stdin.isatty():
            try:
                repo = input("กรุณาใส่ชื่อ GitHub Repo (เช่น username/repo-name): ").strip()
            except (EOFError, KeyboardInterrupt):
                pass

        if not token:
            print("[!] Error: ต้องระบุ GitHub Token (ตั้งค่าใน .env หรือผ่าน --token)")
            sys.exit(1)
        if not repo:
            print("[!] Error: ต้องระบุ GitHub Repo (เช่น username/repo-name หรือผ่าน --repo)")
            sys.exit(1)

    engine = GitHubSyncEngine(
        token=token or "",
        repo=repo or "",
        api_url=args.api,
        release_tag=args.tag,
        mode=args.mode,
        proxy=args.proxy,
        max_files=args.limit,
        dry_run=args.dry_run,
    )
    engine.run()


if __name__ == "__main__":
    main()
