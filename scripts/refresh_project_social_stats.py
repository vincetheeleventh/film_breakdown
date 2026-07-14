from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from film_study_tool.ui_server import OUTPUTS_DIR, load_project_meta, save_project_meta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh social stats from each project's source URL.")
    parser.add_argument("--match", default="", help="Only refresh projects whose source URL contains this text.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    updated: list[str] = []
    skipped: list[dict[str, str]] = []
    for meta_path in OUTPUTS_DIR.glob("*/project_meta.json"):
        project_dir = meta_path.parent
        meta = load_project_meta(project_dir)
        source_url = str(meta.get("sourceUrl") or "")
        if not source_url or (args.match and args.match not in source_url):
            continue
        result = subprocess.run(
            ["yt-dlp", "--no-update", "--dump-single-json", "--skip-download", source_url],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            skipped.append({"project": project_dir.name, "reason": result.stderr.strip() or "metadata refresh failed"})
            continue
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError:
            skipped.append({"project": project_dir.name, "reason": "metadata JSON was unreadable"})
            continue
        changed = False
        for source_key, target_key in [
            ("view_count", "viewCount"),
            ("like_count", "likeCount"),
            ("repost_count", "repostCount"),
            ("comment_count", "commentCount"),
            ("save_count", "saveCount"),
        ]:
            value = info.get(source_key)
            if value not in (None, ""):
                meta[target_key] = int(value or 0)
                changed = True
        if changed:
            save_project_meta(project_dir, meta)
            updated.append(project_dir.name)
    print(json.dumps({"updated": updated, "skipped": skipped}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
