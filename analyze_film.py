import os
import json
import base64
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np
import pandas as pd
import openai
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector, ThresholdDetector, AdaptiveDetector
from dotenv import load_dotenv
import time
import re
import glob
import webvtt
from youtube_transcript_api import YouTubeTranscriptApi

# Load environment variables from .env file
load_dotenv()

MOONSHOT_MODEL = os.environ.get("MOONSHOT_MODEL", "moonshot-v1-8k-vision-preview")
LOCAL_MODEL    = os.environ.get("LOCAL_MODEL",    "llava")
LOCAL_BASE_URL = os.environ.get("LOCAL_BASE_URL", "http://localhost:11434/v1")
MAX_WORKERS    = int(os.environ.get("ANALYSIS_WORKERS", "4"))

def get_shot_schema():
    return {
        "type": "object",
        "properties": {
            "shot_type": {
                "type": "string",
                "description": "The shot type, e.g., wide, medium-wide, close up, two-shot, etc."
            },
            "whats_depicted": {
                "type": "string",
                "description": "What is depicted in the shot, including any action that happens. Refer to previously identified characters by name."
            },
            "camera_movement": {
                "type": "string",
                "description": "Camera movement, e.g., static, pan, tilt, tracking, etc."
            },
            "characters_in_shot": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name assigned to the character, e.g., 'Woman in red'."
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief physical description of the character so they can be identified again later."
                        }
                    },
                    "required": ["name", "description"]
                },
                "description": "List of characters appearing in this shot. Give any prominent characters logical descriptive names."
            }
        },
        "required": ["shot_type", "whats_depicted", "camera_movement", "characters_in_shot"]
    }

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def _parse_srt(srt_path: str) -> list:
    """Parse an SRT subtitle file into the standard transcript list format."""
    transcript = []
    try:
        content = Path(srt_path).read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'\n\s*\n', content.strip()):
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
            m = re.match(
                r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
                lines[1])
            if not m:
                continue
            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
            start = h1*3600 + m1*60 + s1 + ms1/1000
            end   = h2*3600 + m2*60 + s2 + ms2/1000
            text  = ' '.join(l.strip() for l in lines[2:] if l.strip())
            text  = re.sub(r'<[^>]+>', '', text)  # strip HTML tags
            if text:
                transcript.append({'text': text, 'start': start, 'duration': end - start})
    except Exception as e:
        print(f"Failed to parse SRT {srt_path}: {e}")
    return transcript


def fetch_existing_transcript(video_path: str) -> list:
    """
    Tries to find a pre-existing transcript for the video in priority order:
      1. Local .vtt file (downloaded by yt-dlp alongside the video)
      2. Local .srt file
      3. YouTube Transcript API (if the filename contains a YouTube video ID)
    Returns a list of {text, start, duration} dicts, or [] if nothing found.
    """
    video_path_obj = Path(video_path)
    parent_dir = video_path_obj.parent
    stem_name  = video_path_obj.stem

    # 1. VTT
    vtt_files = glob.glob(str(parent_dir / f"{glob.escape(stem_name)}*.vtt"))
    if vtt_files:
        print(f"Found local VTT: {vtt_files[0]}. Parsing...")
        try:
            transcript = []
            for caption in webvtt.read(vtt_files[0]):
                start_parts = caption.start.split(':')
                end_parts   = caption.end.split(':')
                start_sec = float(start_parts[0])*3600 + float(start_parts[1])*60 + float(start_parts[2])
                end_sec   = float(end_parts[0])*3600   + float(end_parts[1])*60   + float(end_parts[2])
                transcript.append({'text': caption.text, 'start': start_sec, 'duration': end_sec - start_sec})
            if transcript:
                return transcript
        except Exception as e:
            print(f"Failed to parse VTT: {e}")

    # 2. SRT
    srt_files = glob.glob(str(parent_dir / f"{glob.escape(stem_name)}*.srt"))
    if srt_files:
        print(f"Found local SRT: {srt_files[0]}. Parsing...")
        transcript = _parse_srt(srt_files[0])
        if transcript:
            return transcript

    # 3. YouTube Transcript API
    match = re.search(r"\[([a-zA-Z0-9_-]{11})\]", stem_name)
    if not match:
        return []

    video_id = match.group(1)
    print(f"Found YouTube ID: {video_id}. Fetching transcript via API...")
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        try:
            fetched = transcript_list.find_transcript(['en', 'en-US', 'en-GB']).fetch()
        except Exception:
            fetched = None
            for t in transcript_list:
                if t.is_translatable:
                    fetched = t.translate('en').fetch()
                    break
        if fetched:
            return [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in fetched]
        return []
    except Exception as e:
        print(f"Failed to fetch YouTube transcript: {e}")
        return []


def run_whisperx_transcription(video_path: str) -> list:
    """
    Transcribes audio from the video.
    Tries WhisperX first (GPU, word-level alignment), then falls back to
    plain openai-whisper (CPU-friendly, simpler install).
    Returns a list of {text, start, duration} dicts, or [] on failure.
    Requires ffmpeg on PATH for both backends.
    """
    # ── Try WhisperX (best quality, word-level timestamps) ────────────────────
    try:
        import torch
        import whisperx

        device       = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        print(f"WhisperX: starting transcription on {device.upper()}...")

        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "audio.wav"
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video_path,
                 "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                 str(wav_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode != 0:
                raise RuntimeError("ffmpeg audio extraction failed for WhisperX.")

            model = whisperx.load_model("large-v3", device, compute_type=compute_type)
            audio = whisperx.load_audio(str(wav_path))
            wx_result = model.transcribe(audio, batch_size=16)

            model_a, metadata = whisperx.load_align_model(
                language_code=wx_result["language"], device=device)
            wx_result = whisperx.align(
                wx_result["segments"], model_a, metadata, audio, device,
                return_char_alignments=False)

        transcript = [
            {'text': seg['text'].strip(), 'start': seg['start'],
             'duration': seg['end'] - seg['start']}
            for seg in wx_result["segments"]
            if seg.get('text', '').strip()
        ]
        print(f"WhisperX: transcribed {len(transcript)} segments.")
        return transcript

    except ImportError:
        pass  # WhisperX not installed — try plain whisper below
    except Exception as e:
        print(f"WhisperX transcription failed: {e}")
        return []

    # ── Fallback: openai-whisper (pip install openai-whisper) ─────────────────
    try:
        import whisper

        print("WhisperX not installed — falling back to openai-whisper (base model)...")
        model = whisper.load_model("base")
        result = model.transcribe(video_path, verbose=False)
        transcript = [
            {'text': seg['text'].strip(), 'start': seg['start'],
             'duration': seg['end'] - seg['start']}
            for seg in result.get("segments", [])
            if seg.get('text', '').strip()
        ]
        print(f"Whisper: transcribed {len(transcript)} segments.")
        return transcript

    except ImportError:
        print("No transcription model installed — skipping.")
        print("  Option A (recommended): pip install openai-whisper")
        print("  Option B (better timestamps): pip install whisperx")
        print("  Both also require ffmpeg on your PATH.")
        return []
    except Exception as e:
        print(f"Whisper transcription failed: {e}")
        return []

def analyze_video(video_path: str, mock_test: bool = False, threshold: float = 27.0,
                  cancel_event=None, progress_callback=None, use_local_model: bool = False,
                  transcribe_audio: bool = False) -> Optional[list]:
    """
    Returns a list of warning strings on success (empty = no warnings).
    Returns None if cancelled.
    """
    warnings = []
    video_path_obj = Path(video_path)
    output_dir   = video_path_obj.parent / f"{video_path_obj.stem}_keyframes"
    sidecar_path = video_path_obj.parent / f"breakdown_{video_path_obj.stem}_progress.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Load resume data ──────────────────────────────────────────────────────
    completed_results: Dict[int, dict] = {}
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding='utf-8'))
            completed_results = {int(k): v for k, v in sidecar.get("shots", {}).items()}
            print(f"Resuming: {len(completed_results)} shots already complete.")
        except Exception as e:
            print(f"Could not load resume file, starting fresh: {e}")

    # ── Detect scenes (hard cuts + fades + dissolves) ─────────────────────────
    print(f"Detecting scenes (pace threshold={threshold:.0f})...")
    video_stream = open_video(video_path)
    scene_mgr    = SceneManager()
    scene_mgr.add_detector(ContentDetector(threshold=threshold))          # hard cuts
    scene_mgr.add_detector(ThresholdDetector(threshold=8, fade_bias=0))   # fades to/from black or white
    scene_mgr.add_detector(AdaptiveDetector(adaptive_threshold=3.0))      # dissolves / crossfades
    scene_mgr.detect_scenes(video_stream, show_progress=False)
    scene_list = scene_mgr.get_scene_list()
    print(f"Detected {len(scene_list)} scenes.")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video {video_path}")
        return

    # ── Set up API client ─────────────────────────────────────────────────────
    if use_local_model:
        client     = openai.OpenAI(api_key="ollama", base_url=LOCAL_BASE_URL)
        model_name = LOCAL_MODEL
        print(f"Using local model: {model_name} at {LOCAL_BASE_URL}")
    else:
        api_key = os.environ.get("MOONSHOT_API_KEY", os.environ.get("KIMI_API_KEY"))
        if not api_key and not mock_test:
            print("Please set MOONSHOT_API_KEY or KIMI_API_KEY environment variable.")
            cap.release()
            return
        client     = openai.OpenAI(api_key=api_key or "mock_key", base_url="https://api.moonshot.ai/v1")
        model_name = MOONSHOT_MODEL

    scenes_to_process  = scene_list[:5] if mock_test else scene_list
    total_scenes       = len(scenes_to_process)

    # ── Transcript: try existing sources; optionally start WhisperX in parallel ──
    transcript_data   = []
    whisper_executor  = None
    whisper_future    = None

    if transcribe_audio:
        transcript_data = fetch_existing_transcript(video_path)
        if transcript_data:
            print(f"Transcript loaded: {len(transcript_data)} segments.")
        elif not mock_test:
            print("No existing subtitles found — starting WhisperX in background...")
            whisper_executor = ThreadPoolExecutor(max_workers=1)
            whisper_future   = whisper_executor.submit(run_whisperx_transcription, video_path)

    # ── Phase 1: Extract all keyframes (sequential; cv2 is not thread-safe) ──
    print("Extracting keyframes...")
    shot_meta = []

    for i, scene in enumerate(scenes_to_process):
        if cancel_event and cancel_event.is_set():
            print("Cancelled during keyframe extraction.")
            cap.release()
            if whisper_executor:
                whisper_executor.shutdown(wait=False)
            return

        start_sec      = scene[0].get_seconds()
        end_sec        = scene[1].get_seconds()
        start_frame    = scene[0].get_frames()
        end_frame      = scene[1].get_frames()
        duration_frames = end_frame - start_frame

        target_frame = start_frame + 8
        if target_frame >= end_frame:
            target_frame = start_frame + (duration_frames // 2)

        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()

        keyframe_path = ""
        if ret:
            proposed_path = output_dir / f"shot_{i:04d}.jpg"
            ok, buf = cv2.imencode('.jpg', frame)
            if ok:
                proposed_path.write_bytes(buf.tobytes())
                keyframe_path = str(proposed_path)
            else:
                print(f"Warning: Could not encode frame for shot {i+1}")
        else:
            print(f"Warning: Could not extract frame for shot {i+1}")

        shot_dialogue = [
            t['text'].replace('\n', ' ')
            for t in transcript_data
            if t['start'] < end_sec and (t['start'] + t['duration']) > start_sec
        ]

        shot_meta.append({
            "index":          i,
            "start_sec":      start_sec,
            "end_sec":        end_sec,
            "duration_sec":   end_sec - start_sec,
            "duration_frames": duration_frames,
            "keyframe_path":  keyframe_path,
            "dialogue":       " ".join(shot_dialogue),
        })

    cap.release()

    # ── Collect WhisperX result (ran in parallel with Phase 1) ───────────────
    if whisper_future is not None:
        if cancel_event and cancel_event.is_set():
            whisper_executor.shutdown(wait=False)
        else:
            print("Waiting for WhisperX transcription to finish...")
            transcript_data = whisper_future.result() or []
            whisper_executor.shutdown(wait=False)
            if transcript_data:
                print(f"WhisperX complete: {len(transcript_data)} segments.")
            else:
                print("WhisperX returned no segments; Dialogue column will be empty.")
                warnings.append(
                    "No transcript could be obtained — the Dialogue column will be empty.\n\n"
                    "To enable local transcription, install one of:\n"
                    "  pip install openai-whisper   (simpler, CPU-friendly)\n"
                    "  pip install whisperx         (better timestamps, needs CUDA)\n\n"
                    "Both also require ffmpeg on your PATH."
                )

        # Rebuild dialogue strings now that we have the transcript
        if transcript_data:
            for meta in shot_meta:
                meta["dialogue"] = " ".join(
                    t['text'].replace('\n', ' ')
                    for t in transcript_data
                    if t['start'] < meta["end_sec"] and (t['start'] + t['duration']) > meta["start_sec"]
                )

    # ── Phase 2: Parallel LLM analysis ───────────────────────────────────────
    prompt_schema_str = json.dumps(get_shot_schema(), indent=2)

    def analyze_one(meta) -> tuple:
        idx = meta["index"]
        if cancel_event and cancel_event.is_set():
            return idx, None
        if not meta["keyframe_path"]:
            return idx, None

        if mock_test:
            print(f"Mocking shot {idx+1}...")
            time.sleep(0.05)
            return idx, {
                "shot_type": "Close up",
                "whats_depicted": "Character A looks at the camera",
                "camera_movement": "Static",
                "characters_in_shot": [{"name": "Character A", "description": "Brown hair, blue shirt"}]
            }

        b64 = encode_image(meta["keyframe_path"])
        prompt_text = (
            "You are a professional filmmaker breaking down a scene. "
            "Analyze this single frame. Identify the shot type, what is depicted "
            "(including any action), and infer the camera movement. Give any prominent "
            "characters logical descriptive names (e.g., 'Woman in Red').\n\n"
            f"Output strictly valid JSON matching this schema:\n{prompt_schema_str}"
        )

        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model_name,
                    timeout=60,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    ]}],
                    response_format={"type": "json_object"},
                    temperature=0.2
                )
                return idx, json.loads(resp.choices[0].message.content)
            except Exception as e:
                print(f"Shot {idx+1} error (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    time.sleep(2)
        return idx, None

    results: Dict[int, Optional[dict]] = dict(completed_results)
    to_analyze   = [m for m in shot_meta if m["index"] not in results and m["keyframe_path"]]
    already_done = len(results)
    resume_note  = f" ({already_done} resumed)" if already_done else ""
    print(f"Analyzing {len(to_analyze)} shots with {MAX_WORKERS} parallel workers{resume_note}...")

    if progress_callback and already_done:
        progress_callback(already_done, total_scenes)

    completed_in_run = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(analyze_one, m): m["index"] for m in to_analyze}

        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                for f in futures:
                    f.cancel()
                break

            try:
                idx, result = future.result()
                results[idx] = result
                completed_in_run += 1
                print(f"Analyzed shot {idx+1}/{total_scenes}")

                try:
                    sidecar_path.write_text(json.dumps({
                        "video_path": video_path,
                        "shots": {str(k): v for k, v in results.items() if v is not None}
                    }), encoding='utf-8')
                except Exception as e:
                    print(f"Warning: Could not save progress: {e}")

                if progress_callback:
                    progress_callback(already_done + completed_in_run, total_scenes)
            except Exception as e:
                print(f"Shot processing error: {e}")
                completed_in_run += 1
                if progress_callback:
                    progress_callback(already_done + completed_in_run, total_scenes)

    if cancel_event and cancel_event.is_set():
        print(f"\nAnalysis cancelled. Progress saved — re-run to resume from where you left off.")
        return None

    # ── Phase 3: Assemble shot_data in order ──────────────────────────────────
    shot_data = []
    for meta in shot_meta:
        i  = meta["index"]
        ar = results.get(i)
        char_names = ""
        if ar:
            char_names = ", ".join(c["name"] for c in ar.get("characters_in_shot", []) if c.get("name"))

        shot_data.append({
            "Shot":               i + 1,
            "Start Time (s)":     round(meta["start_sec"], 2),
            "End Time (s)":       round(meta["end_sec"], 2),
            "Shot Length (s)":    round(meta["duration_sec"], 2),
            "Shot Length (frames)": meta["duration_frames"],
            "Shot Type":          ar.get("shot_type",      "ERROR") if ar else "ERROR",
            "What's Depicted":    ar.get("whats_depicted", "ERROR") if ar else "ERROR",
            "Camera Movement":    ar.get("camera_movement","ERROR") if ar else "ERROR",
            "Dialogue":           meta["dialogue"],
            "Characters":         char_names,
            "Keyframe Path":      meta["keyframe_path"],
        })

    # ── Phase 4: Generate Excel ───────────────────────────────────────────────
    df           = pd.DataFrame(shot_data)
    output_excel = video_path_obj.parent / f"breakdown_{video_path_obj.stem}.xlsx"

    print(f"Generating spreadsheet {output_excel}...")
    writer = pd.ExcelWriter(output_excel, engine='xlsxwriter')

    df_display = df.drop(columns=["Keyframe Path"])
    df_display.insert(0, 'Image', '')
    df_display.to_excel(writer, sheet_name='Film Breakdown', index=False)

    workbook  = writer.book
    worksheet = writer.sheets['Film Breakdown']

    worksheet.set_column('A:A', 68)
    worksheet.set_column('B:F', 15)
    wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'vcenter'})
    worksheet.set_column('G:K', 40, wrap_format)

    first_keyframe = shot_data[0]["Keyframe Path"] if shot_data else ""
    row_height = 140
    img_scale  = 0.25
    col_width  = 45

    if first_keyframe and os.path.exists(first_keyframe):
        img_data = np.frombuffer(Path(first_keyframe).read_bytes(), np.uint8)
        img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        if img is not None:
            h, w = img.shape[:2]
            target_pixel_height = min(h * 0.25, 400)
            img_scale  = target_pixel_height / h
            row_height = h * img_scale * 0.75
            col_width  = w * img_scale / 7.0

    worksheet.set_column('A:A', col_width)

    for row_num, keyframe_path in enumerate(df["Keyframe Path"]):
        worksheet.set_row(row_num + 1, row_height, wrap_format)
        if keyframe_path and os.path.exists(keyframe_path):
            worksheet.insert_image(
                row_num + 1, 0, keyframe_path,
                {'x_scale': img_scale, 'y_scale': img_scale, 'positioning': 1}
            )

    writer.close()

    if sidecar_path.exists():
        sidecar_path.unlink()

    print(f"Excel report successfully generated at {output_excel}")
    return warnings


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", help="Path to the video file")
    parser.add_argument("--mock",      action="store_true", help="Run in mock mode (no API calls)")
    parser.add_argument("--threshold", type=float, default=27.0, help="Scene detection threshold (default 27, lower = more cuts)")
    parser.add_argument("--local",      action="store_true", help="Use local Ollama model instead of Moonshot")
    parser.add_argument("--transcribe", action="store_true", help="Transcribe dialogue/voiceover (uses existing subs or WhisperX)")
    args = parser.parse_args()

    analyze_video(args.video_path, mock_test=args.mock, threshold=args.threshold,
                  use_local_model=args.local, transcribe_audio=args.transcribe)
