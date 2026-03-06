import yt_dlp

ydl_opts = {
    'skip_download': True,
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitlesformat': 'vtt',
    'outtmpl': 'test_data/%(id)s.%(ext)s',
    'quiet': True
}
video_id = "KJNWlMiL1zM"
url = f"https://www.youtube.com/watch?v={video_id}"

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([url])
