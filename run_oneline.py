import os
import yt_dlp
from analyze_film import analyze_video

yt_url = "https://www.youtube.com/watch?v=RUaOpH31IRU"
print(f"YouTube URL detected: {yt_url}")
print("Downloading video using yt-dlp (with cookies to bypass age restriction)...")

os.makedirs("downloads", exist_ok=True)

out_tmpl = os.path.join(os.getcwd(), 'downloads', '%(title)s [%(id)s].%(ext)s')
ydl_opts = {
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'outtmpl': out_tmpl,
    'noplaylist': True,
    'quiet': False,
    'cookiesfrombrowser': ('edge',) # Bypass age restrictions
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(yt_url, download=True)
        target_path = ydl.prepare_filename(info)
        print(f"Download complete: {target_path}")

    analyze_video(target_path, mock_test=False)
except yt_dlp.utils.DownloadError as e:
    print(f"yt-dlp error: {e}")
    print("If it's an age restriction error, please try changing 'edge' to 'chrome' or 'firefox' in the python script.")
