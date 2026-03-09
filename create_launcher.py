"""
Run once to:
  1. Generate film_breakdown.ico (neobrutalist monogram icon)
  2. Create a Desktop shortcut that launches the app
"""

import os
import sys
import subprocess
from pathlib import Path


# ── 1. Generate icon ──────────────────────────────────────────────────────────

def create_icon(ico_path: Path):
    from PIL import Image, ImageDraw, ImageFont

    SIZES = [256, 128, 64, 48, 32, 16]

    def make_frame(size):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)

        BG      = (245, 240, 232, 255)   # parchment
        BLACK   = (26,  22,  20,  255)   # near-black
        CRIMSON = (139, 26,  26,  255)   # deep red

        # Background fill
        d.rectangle([0, 0, size - 1, size - 1], fill=BG)

        # Outer border (neobrutalist thick lines)
        bw = max(2, size // 24)
        d.rectangle([0, 0, size - 1, size - 1], outline=BLACK, width=bw)

        # Top accent stripe
        sh = max(1, size // 12)
        d.rectangle([bw, bw, size - bw - 1, bw + sh], fill=CRIMSON)

        # Dot notches on the stripe (film strip holes)
        n_holes  = max(2, size // 32)
        hole_w   = max(2, sh - 2)
        spacing  = (size - 2 * bw) // (n_holes * 2 + 1)
        for i in range(n_holes):
            x0 = bw + spacing + i * spacing * 2
            y0 = bw + 1
            d.rectangle([x0, y0, x0 + hole_w, y0 + hole_w],
                        fill=BG, outline=None)

        # Bottom accent stripe (mirror)
        d.rectangle([bw, size - bw - sh - 1, size - bw - 1, size - bw - 1], fill=CRIMSON)
        for i in range(n_holes):
            x0 = bw + spacing + i * spacing * 2
            y0 = size - bw - sh
            d.rectangle([x0, y0, x0 + hole_w, y0 + hole_w],
                        fill=BG, outline=None)

        # Central "F" lettermark
        margin  = bw + sh + max(2, size // 16)
        content = size - 2 * margin
        fs      = int(content * 0.88)

        font = None
        for family in ("georgiab.ttf", "georgia.ttf", "arialbd.ttf", "Arial Bold.ttf"):
            for base in [
                os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
                "/usr/share/fonts/truetype",
            ]:
                candidate = os.path.join(base, family)
                if os.path.exists(candidate):
                    try:
                        font = ImageFont.truetype(candidate, fs)
                        break
                    except Exception:
                        pass
            if font:
                break

        if font is None:
            font = ImageFont.load_default()

        # Measure and center
        bbox = d.textbbox((0, 0), "F", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (size - tw) // 2 - bbox[0]
        ty = (size - th) // 2 - bbox[1] + max(0, (sh * 2) // 3)

        # Bold shadow effect (shift 1-2px down-right in near-black)
        offset = max(1, size // 64)
        d.text((tx + offset, ty + offset), "F", font=font, fill=BLACK)
        d.text((tx, ty), "F", font=font, fill=CRIMSON)

        return img

    frames = [make_frame(s) for s in SIZES]
    frames[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"Icon saved -> {ico_path}")


# ── 2. Create Windows Desktop shortcut ───────────────────────────────────────

def create_shortcut(app_dir: Path, ico_path: Path):
    python_exe = str(app_dir / "venv" / "Scripts" / "pythonw.exe")
    if not os.path.exists(python_exe):
        # Fall back to regular python.exe (shows a terminal window)
        python_exe = str(app_dir / "venv" / "Scripts" / "python.exe")

    app_script  = str(app_dir / "app.py")
    desktop     = Path(os.path.expanduser("~")) / "Desktop"
    lnk_path    = desktop / "Film Breakdown.lnk"

    ps_script = f"""
$WShell = New-Object -ComObject WScript.Shell
$Shortcut = $WShell.CreateShortcut("{lnk_path}")
$Shortcut.TargetPath   = "{python_exe}"
$Shortcut.Arguments    = '"{app_script}"'
$Shortcut.WorkingDirectory = "{app_dir}"
$Shortcut.IconLocation = "{ico_path},0"
$Shortcut.Description  = "Film Breakdown AI"
$Shortcut.Save()
Write-Output "Shortcut created: {lnk_path}"
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
    else:
        print(f"PowerShell error:\n{result.stderr.strip()}")
        print("\nManual fallback — run this in PowerShell:")
        print(ps_script)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app_dir  = Path(__file__).parent.resolve()
    ico_path = app_dir / "film_breakdown.ico"

    print("Creating icon...")
    create_icon(ico_path)

    print("Creating Desktop shortcut...")
    create_shortcut(app_dir, ico_path)

    print("\nDone. You can delete create_launcher.py if you like.")
