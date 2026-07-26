# Film Study Tool

Film Study Tool turns a short film or social video into an editable, shot-by-shot study. It combines FFmpeg scene detection, manual timeline correction, captions, and native audio-video model analysis so a filmmaker can study editing, cinematography, sound, and narrative construction.

The current application is a working local-first prototype. Its longer-term purpose is to become a shared multimodal reference library that can use analyzed films to guide new storyboards, shot plans, image prompts, video prompts, music prompts, and sound-design prompts.

## Project Documents

- [Product requirements](docs/PRD.md)
- [Current state and roadmap](docs/CURRENT_STATE.md)
- [Model analysis instructions](film_study_tool/llm_instructions.md)

These are living documents. Update `docs/CURRENT_STATE.md` whenever behavior changes, and update `docs/PRD.md` whenever product scope or product principles change.

## What Works Today

- Upload MP4, MOV, MKV, and WebM videos up to 10 minutes.
- Import individual video URLs, channel URLs, or copied blocks of TikTok and YouTube links with `yt-dlp`. Downloads are verified for both video and audio streams before a study is created; TikTok imports prefer the reliable H.264/AAC rendition and retry instead of accepting a silent file.
- Keep distinct YouTube `watch?v=` links separate while recognizing equivalent `youtu.be` aliases.
- Fetch available English captions and align dialogue to the edited shot timeline.
- Detect candidate cuts with FFmpeg, then let the audio-video model adjudicate and automatically apply hard cuts, fades, dissolves, and crossfades with undo available.
- Split and combine shots, choose which details survive structural edits, change screencaps, and undo timeline edits.
- Watch the full film, individual shots, or inline shot clips.
- Open a study's project directory directly from its film page.
- Navigate Library, film overview, and shot pages with browser or mouse Back/Forward controls.
- Edit shot titles and analysis fields without later model runs overwriting protected manual work.
- Select one or more shot ranges as the AI analysis scope while retaining excluded material for playback and orientation.
- Automatically organize individual shots into filmic sentences and beats, with drag-and-drop refinement, sentence removal, and duration totals.
- Edit film titles and organize studies with drag-and-drop, real nested directories, folder creation/renaming, thumbnail hiding, cover cropping, and deletion.
- Analyze the edited timeline with Qwen 3.5 Omni Plus, including rich image-prompt-style visuals, timed action, soundtrack, camera movement, narrative function, and missing-cut review.
- Use Gemini 3.6 Flash as an optional native-video fallback.
- Preserve film memory between analysis runs and update only edited shot regions after the first full-film pass.
- Continue a persistent per-film Qwen conversation from the saved film memory, edited sentences, user notes, and included shot catalogue.
- Export a Markdown AI handoff that downloads and copies to the clipboard in one action.
- Generate corrected JSON, CSV, and XLSX study outputs with embedded screenshots.
- Install the dark interface as a PWA where the browser supports it.

## Requirements

- Python 3.10 or newer
- FFmpeg and FFprobe on `PATH`
- `yt-dlp` on `PATH` for URL, caption, and channel imports
- An Alibaba Model Studio API key for Qwen analysis
- An optional Gemini API key for fallback

Install the Python package from the repository root:

```bash
python -m pip install -e .
```

### macOS Dependencies

```bash
brew install python ffmpeg yt-dlp
```

### Windows Dependencies

Install Python, FFmpeg, and `yt-dlp`, then confirm each command is available in PowerShell:

```powershell
python --version
ffmpeg -version
ffprobe -version
yt-dlp --version
```

## Configuration

Create a local `.env` file in the repository root. It is ignored by Git.

```dotenv
QWEN_API_KEY=your_key_here
QWEN_COMPATIBLE_URL=https://your-workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_VIDEO_MODEL=qwen3.5-omni-plus

# Optional: enables a USD estimate when the provider returns tokens but not cost.
QWEN_INPUT_COST_PER_MILLION_USD=
QWEN_OUTPUT_COST_PER_MILLION_USD=

# Optional fallback
GEMINI_API_KEY=your_key_here
GEMINI_VIDEO_MODEL=gemini-3.6-flash
```

`DASHSCOPE_API_KEY` and `ALIBABA_CLOUD_API_KEY` are accepted aliases for `QWEN_API_KEY`.

During analysis, the app shows the current processing phase, batch progress, elapsed time, and API response state. Each film also keeps a collapsed Run History with the model, analysis mode, result, duration, shot count, missing cuts found and applied, API calls, token usage, and provider-reported or configured-rate USD cost. Runs created before this tracking existed remain visible with unavailable values clearly labeled.

Never commit `.env` or API credentials.

## Run The App

```bash
python -m film_study_tool.ui_server
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

On Windows, `Start Film Study Tool.cmd` starts the local app shortcut flow.

The command-line breakdown remains available:

```bash
python -m film_study_tool /path/to/short-film.mp4
```

## Storage

The current application uses local files as its canonical store:

```text
data/       Original and downloaded videos and captions
outputs/    Real library folders containing project manifests, screenshots, analysis sessions, and workbooks
```

Dragging a film between folders moves its complete project directory under `outputs/`; its stable project ID and source video remain unchanged. Both storage roots are ignored by Git. A spreadsheet is a generated review artifact, not the source of truth.

The planned shared architecture moves media to Alibaba OSS and structured metadata to PostgreSQL. Until authentication is added, do not expose the local server directly to the public internet.

## Analysis Lifecycle

1. FFmpeg proposes an initial timeline and extracts representative frames.
2. The user corrects boundaries, screencaps, titles, and groupings.
3. The user can include the complete film or choose one or more shot ranges as the analysis scope. Excluded intervals remain visible but are not sent to the model or included in narrative continuity.
4. The first AI analysis processes the current edited, included timeline in bounded chronological video batches of up to 10 shots or 60 seconds. Each request stays below Alibaba's complete Base64 request budget and includes a labeled reference still for every requested shot plus a capped set of the strongest before/after evidence strips around unmatched FFmpeg candidates. Every candidate receives an explicit model verdict; model-confirmed missing cuts are applied by the server before the final narrative pass and spreadsheet save, and remain undoable.
5. Every chronological batch must return every requested identity and core field. Connection resets retry up to three times with only the essential video and shot references. A stream without Qwen's final completion signal is accepted only when it already contains a complete JSON object; truncated output is discarded rather than attached to shots. Incomplete structured output is retried once; it is never merged by position.
6. A final Qwen 3.7 Plus text pass reads the included shot catalogue and timestamp-aligned English subtitles, reconciles narrative function, recurring characters, causality, setup, and payoff, and organizes every included individual shot into contiguous filmic sentences without uploading the video again. It uses closed-world identity rules: uncertain people retain stable neutral labels, and proper names require evidence inside the film, user notes, or human-edited fields. Qwen Omni remains responsible for grounded video and soundtrack observation.
7. The app saves durable film memory, exact timestamp-based shot identities, analysis scope, and model provenance. Generated rows are attached only by exact identity, never by array position or mutable shot number.
8. Later timeline edits send only changed shots plus neighboring context, followed by the same continuity check. Changing the analysis scope rebuilds film memory from the newly included material.
9. `Ask This Film` maintains an app-owned conversation by replaying its saved messages with current film memory and study evidence. It does not rely on undocumented provider-side memory.
10. `Export for AI` writes a Markdown study into the project directory, downloads it, and copies the same text to the clipboard.
11. Older studies can repair narrative continuity from existing analysis and downloaded subtitles without resending video. Stale model-generated narrative prose is withheld during this rewrite so it cannot anchor the replacement. Changes to the user's written interpretation can also be reconsidered from saved film memory.
12. Studies created before automatic AI cut decisions expose a one-time Upgrade Analysis action that rewatches the film and applies model-confirmed missing cuts.
13. Full video reprocessing remains an explicit advanced action.

## Tests

```bash
python -m unittest discover -s tests -v
node --check film_study_tool/ui_static/app.js
```

## Data And Rights

Use source films, screenshots, audio, and model-generated assets only in ways allowed by their licenses, applicable law, and provider terms. The planned corpus will record whether each film is approved for private study, retrieval guidance, prompt reference, or other downstream use.

## License

See [LICENSE](LICENSE).
