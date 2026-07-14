from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Shot:
    number: int
    start: float
    end: float
    screenshot_path: Path | None = None
    scene_score: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def midpoint(self) -> float:
        if self.duration <= 0:
            return self.start
        return self.start + (self.duration / 2)


@dataclass(slots=True)
class ViewerState:
    story_summary: str = ""
    known_characters: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    motifs: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "story_summary": self.story_summary,
            "known_characters": self.known_characters,
            "locations": self.locations,
            "motifs": self.motifs,
            "open_questions": self.open_questions,
        }


@dataclass(slots=True)
class ShotAnalysis:
    visual_description: str
    audio_dialogue: str
    action_camera: str
    narrative_function: str
    shot_title: str = "Shot Title Pending"
    notes: str = ""
    camera_movement_type: str = ""
    camera_movement_intensity: str = ""
    camera_movement_confidence: str = ""
    camera_movement_evidence: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "shot_title": self.shot_title,
            "visual_description": self.visual_description,
            "audio_dialogue": self.audio_dialogue,
            "action_camera": self.action_camera,
            "narrative_function": self.narrative_function,
            "notes": self.notes,
            "camera_movement_type": self.camera_movement_type,
            "camera_movement_intensity": self.camera_movement_intensity,
            "camera_movement_confidence": self.camera_movement_confidence,
            "camera_movement_evidence": self.camera_movement_evidence,
        }


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    millis = int(round((sec - int(sec)) * 1000))
    if millis == 1000:
        sec = int(sec) + 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{int(sec):02d}.{millis:03d}"
