from youtube_transcript_api import YouTubeTranscriptApi

try:
    transcript_list = YouTubeTranscriptApi().list('KJNWlMiL1zM')
    try:
        # Try to explicitly get english
        transcript = transcript_list.find_transcript(['en']).fetch()
    except Exception:
        # Default to whatever is there, and translate
        for t in transcript_list:
            if t.is_translatable:
                transcript = t.translate('en').fetch()
                break
    print("SUCCESS")
    print(transcript[:5])
except Exception as e:
    print("ERROR:", e)
