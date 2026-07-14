from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from film_study_tool.ui_server import OUTPUTS_DIR, load_project_meta, save_project_meta


CHANNEL_URL = "https://www.tiktok.com/@annalaura_art?lang=en-GB"


def main() -> int:
    result = subprocess.run(
        [
            "yt-dlp",
            "--no-update",
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            "120",
            CHANNEL_URL,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "Could not fetch channel metadata.", file=sys.stderr)
        return result.returncode
    data = json.loads(result.stdout)
    entries = data.get("entries") if isinstance(data, dict) else []
    by_url = {
        entry.get("url"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("url"), str)
    }
    updated = 0
    for meta_path in OUTPUTS_DIR.glob("*/project_meta.json"):
        project_dir = meta_path.parent
        meta = load_project_meta(project_dir)
        source_url = str(meta.get("sourceUrl") or "")
        entry = by_url.get(source_url)
        if not entry:
            continue
        for source_key, target_key in [
            ("view_count", "viewCount"),
            ("like_count", "likeCount"),
            ("repost_count", "repostCount"),
            ("comment_count", "commentCount"),
            ("save_count", "saveCount"),
        ]:
            if entry.get(source_key) is not None:
                meta[target_key] = int(entry.get(source_key) or 0)
        save_project_meta(project_dir, meta)
        updated += 1
    print(json.dumps({"updated": updated}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
