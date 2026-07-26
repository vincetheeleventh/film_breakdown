# Film Study Tool Product Requirements

**Status:** Living product document  
**Last updated:** 2026-07-22  
**Current product stage:** Local-first working prototype  
**Target stage:** Shared multimodal film reference and creative-guidance platform

## Product Summary

Film Study Tool helps filmmakers understand how finished films create meaning through shots, edits, performance, composition, color, sound, music, and narrative progression.

The product first creates a reliable, editable study of an existing film. It then distills selected studies into reusable cinematic guidance for planning original work. A user should eventually be able to provide a plot, memory, unstructured story, or film idea and ask the system to develop it using the abstract cinematic grammar learned from selected reference films.

The system is not intended to train a foundational model. It uses retrieval, examples, structured style profiles, and large language model reasoning to guide downstream image, video, music, and sound-generation systems.

## Product Problem

Existing film-analysis workflows are slow and fragmented:

- Editors manually identify shots and take screenshots.
- Technical, narrative, visual, and audio observations live in disconnected notes.
- Model analysis often loses continuity between shots or attaches descriptions to stale timelines.
- Spreadsheets are useful for reading but poor at representing revisions, relationships, provenance, and media.
- Reference films are difficult to reuse systematically when planning a new film.
- Prompts for video, image, music, and sound models are often improvised instead of grounded in a coherent cinematic plan.

## Target Users

- Filmmakers studying editing, cinematography, sound, and narrative technique
- Directors and writers translating stories into visual sequences
- Editors comparing pacing and montage structures
- Creators studying short-form advertisements, talking-head videos, and personal-brand content
- AI filmmakers building coherent multi-shot image, video, music, and sound-generation workflows

## Core Jobs

1. Break a film into an accurate, editable shot timeline.
2. Understand what every shot contributes visually, aurally, kinetically, and narratively.
3. Understand how groups of shots operate as filmic sentences, beats, scenes, and sequences.
4. Preserve a human viewer's accumulating context across the full film and future edits.
5. Find and organize films worth studying.
6. Distill selected films into reusable cinematic and sonic style profiles.
7. Apply those profiles to an original story without copying its plot or characters.
8. Produce coherent, provider-specific prompts for image, video, music, and sound generation.

## Product Principles

### Evidence Before Interpretation

Measured facts, model observations, and human interpretation must remain distinguishable. Narrative claims should link to temporal evidence whenever possible.

### The Edited Timeline Is Canonical

Every analysis request must use the latest user-edited shot boundaries. Generated details must attach by stable identity and exact interval, never by a mutable row number.

### Human Work Is Protected

Model generations must not silently replace fields the user has edited. Structural edits must explicitly resolve which existing annotations survive.

### Film Knowledge Accumulates

Characters, locations, motifs, goals, reversals, and unanswered questions should persist across shots and analysis sessions.

### Guidance Is Abstract And Traceable

Style guidance should describe pacing, composition, camera grammar, palette, sonic strategy, and narrative mechanisms. Recommendations should link back to reference evidence.

### Provider Neutrality

The canonical creative specification must be independent of any one video, image, music, or language model. Provider adapters compile the specification into model-specific prompts.

### Spreadsheets Are Views

XLSX, CSV, and printable studies are human-facing exports. They are not the canonical database.

## Product Scope

### Film Ingestion

- Accept local MP4, MOV, MKV, and WebM files.
- Import supported single video URLs with `yt-dlp`.
- Verify that downloaded source assets contain both video and audio streams before creating the study, and retry a safer combined rendition when source-platform format metadata is inaccurate.
- Accept channel URLs or pasted blocks containing multiple URLs.
- Retrieve available captions and social metadata when supported.
- Preserve the source URL and source metadata.
- Enforce a 10-minute starting limit while the system is optimized for short-form work.

### Timeline Construction

- Use FFmpeg scene scores to propose initial hard-cut boundaries.
- Ask an audio-video model to review the same film for missed hard cuts and gradual transitions.
- Require an explicit model verdict for every FFmpeg candidate, automatically apply model-confirmed boundaries, and retain undo plus manual correction.
- Split, combine, reorder within filmic sentences, and change representative frames.
- Preserve structural lineage when a shot is split or combined.
- Provide undo for unsaved timeline edits.

### Shot Analysis

Each shot can contain:

- Short title
- Start, end, and duration
- Representative image and source interval
- Shot size, composition, characters, setting, props, color, and lighting
- Dialogue, voice-over, music, ambience, and sound effects
- Primary and secondary action
- Camera movement type, intensity, confidence, and evidence
- Narrative function and analytical notes
- Manual-edit state, model provenance, confidence, and review status

### Structural Analysis

- Automatically group every individual shot into contiguous filmic sentences while preserving manual rearrangement.
- Give each sentence a title, duration, beat, and conveyed idea.
- Support higher-level scenes and sequences in the target data model.
- Record causal relationships, setup/payoff, motifs, repeated gestures, and emotional progression.

### Library And Discovery

- Display analyzed films in a searchable library.
- Organize films into nested folders, channels, collections, and study types.
- Support tags for heartfelt shorts, advertisements, talking-head work, and additional user-defined categories.
- Sort and filter by source, duration, popularity, date, tags, analysis status, and guidance approval.
- Let users select and crop cover images.

### Audio And Music Analysis

Audio uses an independent timeline because cues frequently cross shot boundaries.

The target system records:

- Dialogue, speakers, and voice-over
- Ambience, silence, and sound effects
- Music cue boundaries
- Tempo, meter, key, mode, instrumentation, and texture
- Loudness, dynamics, and intensity progression
- Motifs and recurring sonic ideas
- Musical hit points aligned with cuts, actions, and emotional turns
- Whether music leads, follows, bridges, supports, or contradicts the image

Deterministic extraction should provide timing and measurable features. Omni-model analysis should provide semantic, emotional, and narrative interpretation. Human review remains separately recorded.

### Style Profiles

A selected film can produce a versioned style profile containing:

- Shot-length distribution and pacing curve
- Cut density by beat and narrative intensity
- Composition and framing vocabulary
- Camera movement vocabulary and frequency
- Palette, contrast, lighting, and color progression
- Transition and montage grammar
- Performance and blocking patterns
- Visual causality and information-reveal patterns
- Music, silence, ambience, and synchronization strategy
- Narrative structures, recurring gestures, motifs, setup, reversal, and payoff patterns
- Links to representative shots, sentences, beats, and audio cues

Profiles may combine multiple reference films with explicit weights. They must use abstract attributes rather than relying only on a work's title or creator name.

### Creative Guidance

The user supplies a plot, recollection, transcript, brief, or unstructured idea. The system:

1. Extracts characters, desires, obstacles, changes, locations, chronology, and emotional turns.
2. Builds a beat structure without inventing unnecessary story content.
3. Retrieves relevant reference films, beats, shots, transitions, and audio cues.
4. Creates a provider-neutral creative specification.
5. Proposes shot durations, compositions, actions, camera behavior, transitions, visual continuity, and pacing.
6. Creates a music cue sheet, sound plan, and synchronization points.
7. Compiles prompts for selected image, video, music, and sound-generation providers.
8. Preserves every prompt's connection to its story purpose and reference evidence.

### Creative Specification

The canonical guidance package includes:

```json
{
  "story": {},
  "style_profiles": [],
  "characters": [],
  "locations": [],
  "beats": [],
  "shots": [],
  "visual_continuity": {},
  "music_cues": [],
  "sound_events": [],
  "reference_examples": [],
  "generation_constraints": {}
}
```

Every proposed shot should define its story purpose, timing, composition, action, camera, lighting, palette, beginning and ending state, continuity requirements, references, and generation instructions.

### Prompt Compilation

Prompt adapters convert the creative specification into:

- Text-to-video prompts
- Image-to-video prompts
- First-frame and final-frame image prompts
- Character and location reference-image prompts
- Music-generation prompts and cue durations
- Ambience and sound-effect prompts
- Continuity instructions for neighboring shots
- Provider-specific parameters without contaminating the canonical specification

## Canonical Data Model

The target model includes:

| Entity | Purpose |
|---|---|
| Film | Stable identity, source, rights, tags, and library metadata |
| Source asset | Original video, audio, captions, hashes, and object-storage location |
| Analysis revision | Exact model, prompt, timeline, context, and timestamp used |
| Shot revision | Immutable interval and lineage after splits or combinations |
| Frame asset | Representative and evidentiary frames |
| Transition | Type, interval, confidence, evidence, and review state |
| Sentence / beat / scene | Hierarchical narrative and editorial structure |
| Annotation | Field value, source, model, confidence, evidence, and review state |
| Audio event | Independent dialogue, music, ambience, silence, or sound-effect interval |
| Style profile | Versioned abstraction of visual, editorial, narrative, and sonic grammar |
| Embedding | Recomputable vector with modality and model version |
| Guidance package | Story plan, retrieved references, and creative specification |
| Prompt artifact | Provider-specific prompt compiled from a guidance package |

Assets should be stored once with content hashes. Shot clips should normally be represented by source-video intervals and materialized only as cached or exported derivatives.

## AI Architecture

### Current Analysis Architecture

- Qwen 3.5 Omni Plus is the default native audio-video model.
- Gemini 3.6 Flash is an optional fallback.
- The first analysis views the current complete film and current edited intervals.
- The app stores provider-independent film memory locally.
- Later structural edits send only changed shots and neighboring context.
- Changes to user hypotheses can update narrative analysis from stored film memory without resending video.
- Missing-cut decisions and shot-detail generation share the same viewing request. The model receives before/after evidence strips, must explicitly adjudicate every unmatched FFmpeg candidate, and may also report cuts FFmpeg missed. Model-confirmed cuts apply automatically; FFmpeg-only candidates never alter the timeline.
- After grounded video extraction and server-side application of confirmed missing cuts, a text-only continuity pass reads the complete chronological shot catalogue, reconciles narrative function, recurring-character identity, causality, setup, and payoff, and organizes all individual shots into contiguous filmic sentences.
- Character identity follows closed-world evidence rules. Franchise knowledge and face familiarity are not accepted as evidence; uncertain people receive stable neutral labels until the film, user notes, or human edits establish a proper name.
- Studies created before continuity reconciliation can upgrade their narrative fields without resending the source video.

### Target Guidance Architecture

- PostgreSQL stores canonical entities, revisions, and relationships.
- Alibaba OSS stores original and derived media.
- Vector retrieval combines text, image, audio, and eventually video embeddings.
- Metadata filters constrain retrieval by format, beat, duration, camera behavior, rights, and approval state.
- A planner transforms the new story and retrieved evidence into a neutral creative specification.
- Provider adapters generate final prompts.

## Rights And Provenance

Every source film should record its origin and permitted downstream use:

- `study_only`
- `retrieval_allowed`
- `prompt_reference_allowed`
- `training_allowed`
- `generated_asset_reference_allowed`

The app should not imply that private study automatically grants redistribution, commercial reuse, or model-training rights.

## Non-Functional Requirements

- **Integrity:** No generated detail may attach to the wrong shot revision.
- **Recoverability:** Manual work and prior revisions must be recoverable.
- **Portability:** A corpus can be exported without dependence on one AI provider.
- **Traceability:** Generated guidance links to references, model versions, and prompts.
- **Security:** API keys remain server-side; shared deployments require authentication and HTTPS or a private network.
- **Cost control:** Reuse film memory and analyze only changed regions when possible.
- **Responsiveness:** Video and model processing run as background jobs in the shared architecture.
- **Accessibility:** Core review and editing remain keyboard accessible and usable on laptop screens.
- **Concurrency:** Shared storage must avoid last-write-wins corruption and record editor identity.

## Success Metrics

- Zero known shot-detail alignment errors after timeline edits
- Median manual correction time per minute of source video
- Percentage of automatically applied AI cuts retained without undo or manual correction
- Percentage of generated shot fields accepted without editing
- Percentage of analyzed films approved for guidance
- User-rated usefulness of retrieved references
- User-rated coherence of generated shot plans and music cue sheets
- Number of provider adapters using the same creative specification without schema changes

## Out Of Scope For The Current Product Stage

- Training a foundational image, video, music, or language model
- Replacing a nonlinear video editor
- Fully automatic final-film generation with no human review
- Public multi-tenant hosting before authentication and data isolation exist
- Treating generated narrative interpretation as objective ground truth

## Product Risks

- Automated shot detection will remain imperfect for animation, flashes, occlusion, and gradual transitions.
- Audio source separation and music-description models can produce uncertain results.
- Provider-specific generation capabilities and prompt formats will change.
- Small reference libraries can lead to repetitive or overly literal guidance.
- Copyright and provider restrictions may limit downstream use of some reference assets.
- Model analysis can sound confident while attaching weak evidence.

## Documentation Maintenance

Update this PRD when product scope, users, principles, canonical entities, or target architecture change. Keep implementation status out of this file when possible; record it in [CURRENT_STATE.md](CURRENT_STATE.md).
