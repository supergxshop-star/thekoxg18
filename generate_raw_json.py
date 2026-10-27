import json
import urllib.parse
from pathlib import Path

# Load cached API list
with open("cached_api_list.json", "r", encoding="utf-8") as f:
    data = json.load(f)

files = data.get("files", [])
raw_list = []

owner_repo = "supergxshop-star/thekoxg18"
branch = "main"

for idx, item in enumerate(files, 1):
    name = item.get("name", "video")
    ext = item.get("ext", "mp4").strip(".")
    size = item.get("size", 0)
    original_url = item.get("url", "").replace(r"\/", "/")

    safe_name = f"{name}.{ext}"
    quoted_name = urllib.parse.quote(safe_name)

    raw_list.append({
        "id": idx,
        "title": name,
        "filename": safe_name,
        "extension": ext,
        "size_bytes": size,
        "size_mb": round(size / (1024 * 1024), 2),
        "direct_source_url": original_url,
        "github_raw_url": f"https://raw.githubusercontent.com/{owner_repo}/{branch}/raw/{quoted_name}",
        "github_release_url": f"https://github.com/{owner_repo}/releases/download/media-vault/{quoted_name}",
    })

output_file = Path("raw_clips.json")
with open(output_file, "w", encoding="utf-8") as f:
    json.dump({
        "total_clips": len(raw_list),
        "source_api": "https://ak.xworms.xyz/api.php?action=list&sync=1",
        "updated_at": "2026-10-27 13:52:00",
        "clips": raw_list
    }, f, ensure_ascii=False, indent=2)

print(f"Generated {output_file.name} with {len(raw_list)} items.")
