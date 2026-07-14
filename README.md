# Film Study Tool

This is a first local prototype for turning a short video file into a shot-by-shot study workbook.

It currently:

- accepts a video file up to 10 minutes by default
- detects likely shot changes with FFmpeg scene detection
- extracts one representative screenshot per shot
- writes a `.xlsx` workbook with the screenshots embedded
- adds columns for visual description, audio/dialogue, action/camera movement, duration, and narrative function
- writes an `analysis_packets.jsonl` file shaped for a future vision/audio LLM pass with persistent viewer context

The first version uses a placeholder analyzer. That means the workbook structure, timing, screenshots, and per-shot context packets are real, while the rich natural-language analysis fields are waiting for a model adapter.

## Requirements

- Python 3.10+
- FFmpeg and FFprobe available on your PATH
- Pillow, installed with:

```powershell
python -m pip install -e .
```

## Run

```powershell
python -m film_study_tool "C:\path\to\short-film.mp4"
```

Optional:

```powershell
python -m film_study_tool "C:\path\to\short-film.mp4" --output-dir outputs\my-film --threshold 0.32
```

The main output is:

```text
outputs\<video-name>_<timestamp>\film_study.xlsx
```

## Review and Correct Shots

Launch the local UI:

```powershell
python -m film_study_tool.ui_server
```

Then open:

```text
http://127.0.0.1:8765
```

The UI lets you:

- scan every generated screencap in an overview grid
- click a shot to view it larger with notes and analysis fields below
- use left and right arrows, or keyboard arrow keys, to move through shots
- turn on edit mode and combine adjacent shots when scene detection split one shot into multiple pieces
- save corrections, which writes `corrected_manifest.json`, `corrected_manifest.csv`, and `corrected_film_study.xlsx`

## Output Columns

- Shot
- Screenshot
- Start
- End
- Duration (s)
- Visual Description
- Audio / Dialogue
- Action / Camera
- Narrative Function
- Notes

## Next Model Layer

The `analysis_packets.jsonl` file is designed so a model can analyze each shot in order while receiving a compact persistent viewer state:

- prior story summary
- recurring character IDs or labels
- locations and motifs noticed so far
- unresolved questions
- current shot timing and screenshot path

That is the piece that will let the tool behave more like a human viewer who accumulates context while watching, instead of treating every frame as unrelated.
