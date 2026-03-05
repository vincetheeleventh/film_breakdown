# Film Breakdown Tool — Development Tracker

---

## Current Limitations

### 1. Still-Frame Analysis Only
The tool extracts a single keyframe per shot and sends it to the vision model. This means:
- **Character actions** are inferred from a static pose, not observed motion
- **Camera movement** (pan, tilt, dolly, zoom) cannot be detected from one frame — it is guessed at best
- **Performance nuance** (timing, expression changes mid-shot) is lost

### 2. No Character Memory Across Shots
Each shot is analysed in isolation with no shared context:
- Recurring characters get re-described from scratch each shot
- No consistent naming across the breakdown
- Characters column can't be used to track a character's arc through the film

### 3. No Story Arc / Narrative Continuity
Shots processed in parallel with no memory between them:
- No awareness of what came before or after
- Scene-level context, dramatic beats, narrative structure not captured
- Breakdown reads as isolated observations, not a coherent story analysis

### Root Cause
All three limitations share the same root: **stateless, per-shot LLM calls on still frames**. Fixing them requires either a multi-pass approach or a video-native API.

---

## Current Bugs

- **Duplicate frames in spreadsheet** — some shots appear more than once. Likely caused by multiple scene detectors (ContentDetector + ThresholdDetector + AdaptiveDetector) firing on overlapping timecodes that aren't fully deduplicated before keyframe extraction.

---

## Proposed Solutions

### Solution A: Camera Movement via Optical Flow (Local, Near-Zero Cost)
**Addresses:** Limitation 1 (camera movement specifically)

OpenCV's Farneback dense optical flow computes per-pixel motion vectors between consecutive frames within a shot, making camera movement directly measurable without any API call.

**How it works:**
- Pan: flow vectors point uniformly left/right across the frame
- Tilt: vectors point uniformly up/down
- Zoom in/out: vectors radiate outward/inward from a centre point
- Static: vectors near-zero everywhere
- Handheld/complex: large, non-uniform vectors

**Implementation approach:**
- Sample 5–10 frame pairs evenly spaced within each detected shot
- Compute Farneback flow for each pair (`cv2.calcOpticalFlowFarneback`)
- Classify each pair (pan/tilt/zoom/static/complex) using mean dx/dy and radial flow analysis
- Take the mode across the samples as the shot's camera movement label

**Realistic accuracy:** ~70–80% on narrative film (pan/tilt/zoom/static 4-class problem). Fails on fast-action shots where actor movement drowns the camera signal. Handheld vs. pan is the hardest case.

**Upgrade path:** Replace Farneback with RAFT (deep learning optical flow, `torchvision.models.optical_flow.raft_large`) for ~15–20% better accuracy on complex scenes, at the cost of GPU and slower inference.

**Cost:** Zero. Runs locally using OpenCV which is already installed.

**Effort to implement:** Medium. No new dependencies; add a `classify_camera_movement(shot_frames)` function called during Phase 1 keyframe extraction.

---

### Solution B: Character Registry (Sequential + Accumulated Memory)
**Addresses:** Limitation 2 (character identity)

Process shots **sequentially** (not in parallel) and maintain a running character registry that is injected into each prompt.

**How it works:**
1. Start with an empty `character_registry: dict[str, str]` (name → description)
2. For each shot, inject the current registry into the LLM prompt: *"Known characters so far: [registry]. Identify which of these appears, or assign a new name if it's someone new."*
3. After each shot, parse the response and update the registry (new characters, refined descriptions)
4. By the end, characters have consistent names and the registry captures their evolving description

**Trade-offs:**
- Loses parallelism — shots must process one at a time (slower, can't cancel as cleanly)
- Model still can't *see* previous frames — it only reads text descriptions
- Registry can accumulate errors (a misidentification in shot 3 propagates forward)
- Works best for films with a small cast and frequent frontal close-ups

**Better alternative: Face/Appearance Embeddings** (see Solution C)

---

### Solution C: Automated Character Re-ID via Face + Appearance Embeddings
**Addresses:** Limitation 2 (character identity), more robustly than Solution B

A hybrid local pipeline that doesn't rely on the LLM for character identity at all:

**Tier 1 — Face embeddings (InsightFace, ArcFace model):**
- Detect faces in each keyframe using `insightface.app.FaceAnalysis`
- Extract 512-dim face embeddings; compare via cosine similarity to a growing character gallery
- Threshold ~0.4 cosine similarity for a confident match
- Accuracy: 85–95% on frontal/well-lit shots; drops to 50–70% on profiles, occlusion, extreme lighting

**Tier 2 — Appearance embeddings (CLIP, for non-frontal shots):**
- Detect persons using YOLOv8 (`pip install ultralytics`)
- Crop person bounding box; compute CLIP `ViT-L/14` image embedding
- Compare against gallery of known-character crops
- Handles rear shots, profiles, partial occlusion — captures clothing, hair, body shape
- Less precise than face embeddings but far better than nothing for non-frontal shots

**Tier 3 — VLM text registry (current approach, kept as fallback):**
- For shots where both face and CLIP similarity is below threshold, send frame + text registry to the VLM
- "Which of these characters [registry] is visible in this frame?"

**Temporal continuity heuristic:** If character X identified in shot N, and shot N+2 is adjacent, same location/costume → propagate identity forward even with low confidence.

**Realistic overall accuracy:** ~75–80% automated for a typical drama. 20–25% requires human review.

**Dependencies to add:** `insightface`, `ultralytics` (YOLOv8), `open-clip-torch`
**Cost:** Zero per analysis (local models). One-time model download.
**Effort:** High. Significant new pipeline.

---

### Solution D: Gemini Video API — Native Full-Video Ingestion
**Addresses:** Limitations 1, 2, and 3 (narrative context, shot type, character tracking in one pass)

Google Gemini 1.5 Pro and 2.0 Flash accept full video files natively via their File API. This is the most complete single-API solution.

**How it works:**
1. Upload the video file via `POST https://generativelanguage.googleapis.com/upload/v1beta/files`
2. Wait for processing (a few minutes for a feature film)
3. Send a structured prompt: *"For each shot, output JSON: {shot_number, start_time, end_time, shot_type, camera_movement, characters_visible, description, action}"*
4. Gemini returns a response grounded in the actual video — it sees motion, not just frames

**What Gemini can do that the current tool cannot:**
- Observe character **actions** (someone runs, falls, opens a door)
- Describe **camera movement** from actual video motion (not just a single frame)
- Maintain **character identity** across the full film within a single context window
- Generate a **narrative summary** of the whole film in one pass

**Context window limits:**
- Gemini samples at ~1 FPS internally (~258 tokens/frame)
- Gemini 1.5 Pro (2M token context): handles up to ~90 minutes comfortably
- Gemini 2.0 Flash (1M token context): handles ~60 minutes
- For longer films: split into acts and run separately

**Accuracy caveats:**
- Temporal accuracy is imperfect — may miss very short shots (<2s) or hallucinate timestamps
- Camera movement description is qualitative, not classified labels
- Attention dilution on very long films (later sequences analysed less carefully)

**Pricing (verify at ai.google.dev/pricing — may have changed):**
- Gemini 2.0 Flash: ~$0.075/1M input tokens — a 90-min film costs roughly $0.50–$3
- Gemini 1.5 Pro: ~$3.50/1M input tokens (under 128K prompt) — $5–$20 per film
- **Free tier** via Google AI Studio: Gemini 2.0 Flash available with rate limits — good for prototyping

**Integration:** Replace or augment the Moonshot per-frame calls. Moonshot remains useful for very high quality single-frame description; Gemini adds temporal/narrative context.

**Effort:** Medium. New API client (`pip install google-generativeai`), new upload + polling flow, prompt redesign for structured shot-list output.

---

### Solution E: TwelveLabs — Semantic Video Search + Chapter Analysis
**Addresses:** Limitation 3 (narrative context, scene-level understanding)

TwelveLabs is video-native (Marengo + Pegasus models) and excels at narrative comprehension and semantic search. Best used as a **supplementary pass** for narrative-level data, not as a replacement for per-shot analysis.

**What it adds:**
- Pegasus `chapter` task: returns `{start, end, chapter_title, chapter_summary}` — automatic act/scene breakdown
- Pegasus `open_ended`: ask any question about the video, grounded in video content ("What is the emotional arc of the protagonist?", "List all scenes where tension escalates")
- Marengo semantic search: find "the scene where the two characters argue near a window" → returns timestamps + confidence

**What it doesn't do:**
- No structured shot-type classification (close-up, wide shot) as native labels
- No camera movement labels
- No face recognition or character identity tracking
- Indexing is async (10–20 min for a feature film) and must happen before querying

**Workflow:**
1. Index the film once (async, ~10–20 min)
2. Run chapter detection → get scene-level segments with summaries
3. Run `open_ended` queries for narrative data (themes, character arcs, tone)
4. Use timestamps to map chapter data back onto the shot-level breakdown

**Pricing (verify at twelvelabs.io/pricing):**
- Free tier: ~600 video-minutes/month indexing
- Paid: ~$0.05–$0.15 per video-minute indexed
- A 100-min film: ~$5–$15 per analysis

**Effort:** Low–Medium. REST API, Python client available (`pip install twelvelabs`). Works as an add-on pass after the main analysis.

---

## Recommended Architecture (Phased)

### Phase 1 — Quick wins, no new APIs (implement now)
| What | How | Effort |
|---|---|---|
| Camera movement detection | Optical flow (Farneback) on 5-10 frames per shot | Medium |
| Fix duplicate frames bug | Audit scene deduplication before keyframe loop | Low |
| Story arc summary | Add a final LLM pass that synthesises all shot descriptions into a narrative summary | Low |

### Phase 2 — Character memory (implement next)
| What | How | Effort |
|---|---|---|
| Sequential mode + text registry | Process shots in order, inject accumulated character descriptions into each prompt | Medium |
| Face re-ID | InsightFace + CLIP embeddings for automated character matching | High |

### Phase 3 — Video-native API (bigger architectural change)
| What | How | Effort |
|---|---|---|
| Gemini video integration | Replace or augment Moonshot per-frame calls with Gemini full-video pass | Medium |
| TwelveLabs narrative layer | Add chapter/summary pass using TwelveLabs Pegasus after main analysis | Medium |

---

## Next Steps Checklist

- [ ] Fix duplicate frames bug
- [ ] Implement optical flow camera movement (Phase 1)
- [ ] Add narrative summary pass at end of analysis (Phase 1)
- [ ] Prototype Gemini video API on a short film (Phase 3 — evaluate quality vs. cost)
- [ ] Prototype TwelveLabs chapter detection (Phase 3 — evaluate narrative value)
- [ ] Implement sequential mode with character text registry (Phase 2)
- [ ] Evaluate InsightFace + CLIP re-ID pipeline (Phase 2)
