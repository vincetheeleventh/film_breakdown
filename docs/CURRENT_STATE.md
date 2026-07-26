# Film Study Tool Current State And Roadmap

**Snapshot date:** 2026-07-25  
**Package version:** 0.1.0  
**Status:** Working local-first prototype under active development

This document records what exists now, what remains limited, and what should be built next. The product intent lives in [PRD.md](PRD.md).

## Current User Workflow

1. Upload a short video or import one or more supported URLs.
2. FFmpeg proposes shot boundaries and extracts a representative screenshot for each shot.
3. Review the film in the dark library and study interface.
4. Split or combine shots, replace screencaps, and edit titles before analysis when needed.
5. Add a personal reading of the film as analysis context.
6. Run Qwen Omni analysis on the latest edited timeline.
7. The model adjudicates every candidate cut, applies confirmed boundaries automatically, and groups the retained individual shots into filmic sentences.
8. Review the result, undo or manually correct boundaries when needed, and refine sentence groupings.
9. Continue editing and update only changed shot regions.
10. Continue the study through a persistent per-film Qwen conversation.
11. Export a Markdown AI handoff to disk, download, and clipboard.
12. Save corrected manifests and an XLSX workbook.

## Implemented

### Ingestion And Library

- Local MP4, MOV, MKV, and WebM upload
- Ten-minute source limit
- Single URL, pasted URL block, and channel import through `yt-dlp`
- Canonical per-video URL identity, including distinct YouTube `watch?v=` links and equivalent `youtu.be` aliases
- Video-first URL imports so unavailable or rate-limited captions cannot discard a successfully downloadable video
- Post-download audio/video stream validation, with TikTok-specific H.264/AAC preference and automatic retry when a platform serves a falsely labeled silent rendition
- Top-five or top-ten channel import workflow
- Best-effort English subtitle and automatic-caption download, isolated from video-download success
- Best-effort likes, views, comments, reposts, saves, uploader, and source links
- Real nested directories under `outputs/`, with channel grouping and drag-and-drop film moves
- Folder creation, subfolder creation, renaming, thumbnail visibility toggle, and deletion
- Inline persistent film-title editing
- Film deletion, source deduplication, and library cover selection
- Landscape cover presentation with adjustable crop for vertical media
- PWA manifest and wheel icon assets

### Film Study And Editing

- Dark shot-overview grid
- Duration color scale and camera-movement card styling
- Editable shot titles directly from the overview
- Full-film playback
- Inline shot playback and shot-detail playback
- Open the current study directory in Finder, File Explorer, or the Linux file manager
- Browser-history navigation across Library, film overview, and individual shot pages
- Individual shot detail page with all analysis fields
- Centered play control directly on the shot image, with in-place shot playback
- Shift-click range selection
- Split at an exact timeline point with frame preview and 0.05-second nudging
- Combine adjacent ranges
- Explicit description-resolution choices for split and combine operations
- Change representative screencap from the same timeline control
- Undo unsaved structural edits
- Manual-field protection against later model replacement
- Drag shots into existing filmic sentences
- Remove selected shots from sentences; removing an interior shot automatically splits the remaining ranges into chronological sentence rows
- Sentence rows, colored outlines, titles, durations, beats, and ideas
- Corrected JSON, CSV, and XLSX generation
- Shot-level analysis inclusion and exclusion, including a selected-range shortcut and visible excluded cards
- Persistent `Ask This Film` conversation drawer
- Markdown AI handoff export with simultaneous download and clipboard copy

### AI Analysis

- Default `qwen3.5-omni-plus` native audio-video analysis
- Optional `gemini-3.6-flash` fallback
- User hypotheses supplied as context to validate, refine, or reject
- Each video batch produces shot details and independent transition review in the same request
- Structured camera-movement type, intensity, confidence, and evidence
- Short generated shot titles
- Dialogue preservation from downloaded captions
- Timestamp-aligned English subtitles are sent as explicit lexical evidence during video analysis and take precedence for spoken meaning
- Stable timestamp-derived analysis identities
- Persistent `analysis_session.json` film memory
- First full-film pass followed by changed-region updates
- Text-only reconsideration when only user context changes
- Explicit advanced full-video reprocessing
- Chronological Qwen upload segmentation for longer videos within Base64 limits
- Evidence-grounded chronological analysis batches of up to 10 shots or 60 seconds, with labeled reference stills for every current shot and at most 10 prioritized transition evidence strips
- Complete-request budgeting for Alibaba's Base64 limit, plus up to three compact essential-evidence retries after connection resets
- Streaming completion validation: a missing final marker is accepted only for already-complete JSON; interrupted partial output is discarded
- Complete-batch validation: every requested current ID and every core field must be present before a batch can be attached
- One targeted retry for malformed or incomplete provider output; repeated audio-only omissions retain a current non-placeholder interval note instead of discarding the film-wide run
- Prior model prose withheld during re-analysis so stale descriptions cannot anchor new output
- Exact-ID-only result merging; rows without a matching current `analysis_id` remain stale instead of being guessed by position
- Compact cumulative story memory carried across chronological video batches
- Qwen 3.7 Plus text-only narrative-continuity pass over the complete chronological shot catalogue, subtitle evidence, and Qwen Omni observations
- One-time subtitle-aware narrative repair for older studies without resending their video
- Prior model-generated narrative functions are withheld from rewritten rows to prevent stale visual-only prose from anchoring the replacement
- Conservative camera classification based on fixed background anchors, with explicit protection against mistaking subject and animated-object motion for camera motion
- Closed-world recurring-character identification with stable neutral labels; proper names require evidence from the film, user notes, or a human-edited field rather than franchise knowledge or face familiarity
- Image-prompt-style visual descriptions and time-ordered action/camera descriptions
- Before/after evidence strips around every unmatched FFmpeg candidate
- Explicit model verdicts for every candidate, with montage language used as supporting confirmation and FFmpeg timestamps used only for localization
- Server-side application of model-identified missing cuts before narrative reconciliation and spreadsheet save, including internal montage edits, with FFmpeg used only as candidate evidence and timestamp support
- Automatic complete, chronological filmic-sentence organization while retaining each component shot
- Exact-ID narrative reconciliation with retry and safe provisional fallback when a provider omits a requested identity
- Undo remains available after automatic AI cuts are saved
- One-time Upgrade Analysis action for studies created before automatic model cut decisions
- Live analysis phase, batch, provider-response, progress, elapsed-time, and durable missing-cut feedback
- Persisted API call and token totals, plus provider-reported or configured-rate USD cost when available
- Append-only per-film analysis run history covering successful, already-current, and failed attempts
- Scope-aware video batching, cut review, narrative continuity, sentences, film memory, chat, and export
- App-owned conversation replay using the same saved Qwen model and current film-study context

## Current Technical Architecture

| Area | Current implementation |
|---|---|
| Frontend | Vanilla JavaScript, HTML, and CSS PWA |
| Server | Python standard-library HTTP server |
| Media processing | FFmpeg and FFprobe subprocesses |
| Source imports | `yt-dlp` subprocesses |
| AI | Alibaba Qwen OpenAI-compatible endpoint; Gemini Interactions fallback |
| Metadata | JSON, JSONL, CSV, and small text files inside project directories |
| Media | Local `data/` plus directory-backed library folders under `outputs/` |
| Reports | XLSX with embedded JPEG screenshots |
| Tests | Python `unittest` plus JavaScript syntax checking |
| Authentication | None; localhost use only |

## Persistence Map

Current project directories can contain:

```text
data/
  source-video.mp4
  source-captions.vtt

outputs/project-id/
  manifest.json
  corrected_manifest.json
  corrected_manifest.csv
  film_study.xlsx
  corrected_film_study.xlsx
  project_meta.json
  outline.json
  study_context.txt
  analysis_session.json
  analysis_runs.jsonl
  film_conversation.json
  film_study_for_ai.md
  analysis_packets.jsonl
  last_llm_response.json
  frames/
  analysis_video/
```

The exact edited shot rows and project JSON files are canonical today. The spreadsheet is regenerated from those rows.

## Known Limitations

### Data And Collaboration

- There is no relational database, object storage, schema migration system, or revision ledger.
- Shared editing, user accounts, permissions, and conflict handling do not exist.
- OneDrive folder synchronization is not safe for concurrent writers.
- Stable interval identities and exact-ID-only model merging prevent description drift after current-timeline edits, but full immutable shot lineage is not implemented.
- Manual edits are marked at field level but are not separate annotation records with author and provenance.

### Processing

- Upload and analysis requests run synchronously rather than through durable background jobs.
- The ten-minute limit is hard-coded in current ingestion paths.
- Qwen automatically adjudicates candidate boundaries and applies confirmed cuts; undo and manual split/combine remain available for correction.
- Gradual transitions remain a weak point: in the source-audited *Father and Daughter* study, Qwen and FFmpeg both missed a dissolve inside shot 10 even though the action analysis correctly described it.
- URL and social metadata support depends on `yt-dlp` and source-platform behavior.
- Caption retrieval currently emphasizes English tracks.
- The server is suitable for trusted local use, not public hosting.

### Audio And Music

- Qwen listens to the soundtrack and can describe audible dialogue, music, and sound.
- Downloaded captions are aligned to shots.
- There is no source separation into dialogue, music, ambience, and effects.
- There is no independent audio-event timeline.
- Tempo, key, instrumentation, loudness, dynamics, motifs, and synchronization points are not deterministically extracted.
- Music profiles and music-generation cue sheets do not yet exist.

### Guidance And Generation

- Films do not yet have generated style profiles.
- There are no text, image, audio, or video embeddings.
- There is no retrieval engine for analogous shots, beats, or music cues.
- There is no story parser, creative specification, or prompt compiler.
- There are no provider adapters for video, image, music, or sound-generation systems.
- Rights and downstream-use permissions are not yet represented in project metadata.

### Engineering

- The server, storage, background processing, and domain logic remain concentrated in `ui_server.py`.
- The Qwen conversation is durable at the application level. The provider does not retain a permanent video thread, so current film memory, evidence, and recent turns are reconstructed for each question.
- The command-line placeholder analyzer and the newer Omni UI workflow have diverged.
- Analysis progress and run history are local-process and local-file based; there is not yet a durable multi-machine job queue or centralized telemetry service.
- Automated tests cover critical alignment and analysis behavior but not the full browser workflow or media pipeline.
- macOS is expected to work with Python, FFmpeg, FFprobe, and `yt-dlp`, but does not yet have a dedicated launcher or documented end-to-end verification record.

## Roadmap

### Phase 0: Analysis Reliability

**State:** In progress; exact-ID alignment, complete-batch validation, targeted retry, and two-film source audits are implemented

- Keep the latest edited timeline canonical for every model call.
- Validate exact-ID title, dialogue, and description alignment across more imported films.
- Add a dedicated gradual-transition detector or temporal verification pass; do not treat an empty Omni transition list as proof that no dissolve exists.
- Validate incremental analysis against split, combine, and AI-applied-cut workflows.
- Add browser-level regression tests for critical editing paths.
- Extend run provenance to individual generated fields and model-response artifacts.

### Phase 1: Canonical Corpus

**Goal:** Make every film study trustworthy and migration-ready.

- Define stable film, source asset, shot revision, transition, annotation, sentence, beat, and analysis-revision schemas.
- Record split and combine lineage instead of relying only on current intervals.
- Separate measured, model-generated, and human-authored values.
- Add review states and approval controls.
- Add downstream-use fields such as `study_only` and `prompt_reference_allowed`.
- Build a migration from existing project folders without losing manual edits.

### Phase 2: Shared Application

**Goal:** Give Windows and macOS access to one safe film library.

- Introduce a storage abstraction.
- Move structured data to PostgreSQL.
- Move source and derived media to Alibaba OSS.
- Run FFmpeg and AI work as resumable background jobs.
- Add authentication, HTTPS or private-network access, and backups.
- Preserve XLSX generation as an export.

### Phase 3: Rich Audio And Visual Features

**Goal:** Capture guidance beyond prose descriptions.

- Add an independent audio timeline and cue editor.
- Separate or classify dialogue, music, ambience, silence, and effects.
- Extract tempo, key, loudness, dynamics, color palettes, motion, and other reproducible features.
- Store measurement algorithms and versions.
- Add film-level visual, editing, narrative, music, and sound summaries.

### Phase 4: Style Profiles And Retrieval

**Goal:** Turn selected studies into reusable cinematic guidance.

- Generate versioned film style profiles with linked evidence.
- Let the user approve films, shots, beats, and cues for guidance.
- Add text and image embeddings first, followed by audio and video embeddings where useful.
- Retrieve by creative function as well as surface similarity.
- Combine multiple reference profiles with explicit weights.
- Show why each reference was retrieved.

### Phase 5: Story Planning And Prompt Compilation

**Goal:** Turn an original story into a coherent multimodal generation package.

- Parse structured or unstructured stories into characters, desires, obstacles, beats, and emotional turns.
- Generate a provider-neutral creative specification.
- Plan shot timing, composition, action, camera, transitions, color, music, and sound.
- Compile image, image-to-video, text-to-video, music, ambience, and sound-effect prompts.
- Add provider adapters without changing canonical story and style data.
- Preserve continuity across generated shots.

### Phase 6: Evaluation And Iteration

**Goal:** Learn from the user's choices without training a foundational model.

- Record accepted, edited, and rejected guidance.
- Compare alternative shot plans and prompts.
- Rank references by demonstrated usefulness.
- Track where generated assets diverge from the creative specification.
- Improve retrieval and planning prompts from reviewed examples.

## Next Three Build Goals

### 1. Canonical Revision And Annotation Schema

Write and validate the database-neutral schema before adding more generated fields. Include immutable shot revision IDs, lineage, annotation provenance, confidence, and review state.

**Done when:** Existing projects can be exported into the schema and reconstructed without losing timeline edits, manual fields, sentences, film memory, or source links.

### 2. Audio Event Timeline

Add dialogue, music, ambience, sound effects, and silence as timestamped entities independent of shot boundaries.

**Done when:** A music cue can span multiple shots, remain linked after timeline edits, and appear in both the study view and an exported cue sheet.

### 3. First Style Profile And Guidance Package

Use one deeply analyzed reference film, starting with Married Life, to generate an evidence-linked visual, editing, narrative, music, and sound profile. Apply it to a new user story to create a neutral shot plan and prompt package.

**Done when:** Every proposed shot and music cue identifies its story purpose, duration, reference evidence, and provider-neutral generation intent.

## Update Checklist

When a feature changes:

1. Update the relevant Implemented or Known Limitations section.
2. Move completed roadmap work into Implemented.
3. Update the snapshot date.
4. Update [PRD.md](PRD.md) only if product scope or architecture changed.
5. Update [../README.md](../README.md) if setup, commands, models, or major user capabilities changed.
6. Run the test suite and record meaningful new coverage in the commit or pull request.
