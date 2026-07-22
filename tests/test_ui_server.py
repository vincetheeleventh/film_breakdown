from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from film_study_tool.ui_server import (
    analysis_target_ids,
    apply_caption_cues_to_rows,
    build_memory_update_prompt,
    build_llm_text_prompt,
    call_qwen_video,
    generate_shot_details_with_native_video,
    merge_generated_shot_details,
    normalize_ai_transition_suggestions,
    parse_generated_analysis,
    timeline_analysis_id,
    timeline_revision,
)


class CaptionAssignmentTests(unittest.TestCase):
    def test_cue_crossing_cut_belongs_to_midpoint_shot_only(self) -> None:
        rows = [
            {"start": "00:00:57.558", "end": "00:01:00.961", "audio_dialogue": "old"},
            {"start": "00:01:00.961", "end": "00:01:04.131", "audio_dialogue": "old duplicate"},
        ]
        cues = [
            {"start": 57.54, "end": 61.16, "text": "She put her head down."},
            {"start": 61.193, "end": 64.063, "text": "She noticed the button."},
        ]

        apply_caption_cues_to_rows(rows, cues)

        self.assertEqual(rows[0]["audio_dialogue"], "She put her head down.")
        self.assertEqual(rows[1]["audio_dialogue"], "She noticed the button.")

    def test_manual_dialogue_is_preserved(self) -> None:
        rows = [
            {
                "start": "00:00:00.000",
                "end": "00:00:02.000",
                "audio_dialogue": "My correction",
                "manual_fields": ["audio_dialogue"],
            }
        ]
        apply_caption_cues_to_rows(rows, [{"start": 0, "end": 1, "text": "Caption"}])
        self.assertEqual(rows[0]["audio_dialogue"], "My correction")


class GeneratedDetailIdentityTests(unittest.TestCase):
    def test_analysis_id_wins_over_returned_shot_number(self) -> None:
        current = [
            {"shot": 1, "shot_title": "Old 1"},
            {"shot": 2, "shot_title": "Old 2"},
        ]
        generated = [
            {"analysis_id": "row_0002", "shot": 1, "shot_title": "Second image"},
            {"analysis_id": "row_0001", "shot": 2, "shot_title": "First image"},
        ]
        merged = merge_generated_shot_details(current, generated)
        self.assertEqual([row["shot_title"] for row in merged], ["First image", "Second image"])

    def test_one_response_contains_details_and_cut_review(self) -> None:
        rows, transitions = parse_generated_analysis(
            '{"shots":[{"analysis_id":"row_0001","shot_title":"Opening"}],'
            '"transitions":[{"time_seconds":1.25,"transition_type":"dissolve"}]}'
        )
        self.assertEqual(rows[0]["shot_title"], "Opening")
        self.assertEqual(transitions[0]["transition_type"], "dissolve")

    def test_detail_prompt_requests_transitions_in_same_json(self) -> None:
        prompt = build_llm_text_prompt(
            "Test Film",
            [{"start": "00:00:00.000", "end": "00:00:02.000", "duration_seconds": 2}],
            {"sentences": []},
            "",
            ffmpeg_candidates=[(1.25, 0.42)],
        )
        self.assertIn('top-level keys named "shots", "transitions", and "film_memory"', prompt)
        self.assertIn('"scene_score": 0.42', prompt)

    def test_native_video_is_called_once_for_details_and_cuts(self) -> None:
        response = (
            '{"shots":[{"analysis_id":"row_0001","shot":1,"shot_title":"Opening"}],'
            '"transitions":[{"time_seconds":1.25,"transition_type":"dissolve"}]}'
        )
        with (
            patch("film_study_tool.ui_server.prepare_qwen_analysis_videos", return_value=[Path(__file__)]),
            patch("film_study_tool.ui_server.call_qwen_video", return_value=response) as qwen_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            rows, transitions, memory, provider, _model = generate_shot_details_with_native_video(
                model="qwen3.7-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Test Film",
                project_dir=Path(__file__).parent,
                shots=[{"start": "00:00:00.000", "end": "00:00:02.000"}],
                outline={"sentences": []},
                user_context="",
                ffmpeg_candidates=[(1.25, 0.42)],
            )
        self.assertEqual(qwen_call.call_count, 1)
        self.assertEqual(provider, "qwen")
        self.assertEqual(memory, {})
        self.assertEqual(rows[0]["shot_title"], "Opening")
        self.assertEqual(transitions[0]["transition_type"], "dissolve")

    def test_timestamp_identity_survives_renumbering(self) -> None:
        row = {"shot": 9, "start": "00:00:03.500", "end": "00:00:06.250"}
        first = timeline_analysis_id(row, 8)
        row["shot"] = 2
        self.assertEqual(first, timeline_analysis_id(row, 1))

    def test_incremental_merge_only_clears_returned_row(self) -> None:
        current = [
            {"analysis_id": "shot_a", "shot": 1, "shot_title": "Old A", "analysis_stale": True},
            {"analysis_id": "shot_b", "shot": 2, "shot_title": "Old B", "analysis_stale": True},
        ]
        merged = merge_generated_shot_details(
            current,
            [{"analysis_id": "shot_b", "shot_title": "New B"}],
        )
        self.assertEqual(merged[0]["shot_title"], "Old A")
        self.assertTrue(merged[0]["analysis_stale"])
        self.assertEqual(merged[1]["shot_title"], "New B")
        self.assertFalse(merged[1]["analysis_stale"])

    def test_only_unseen_interval_is_targeted_after_first_pass(self) -> None:
        shots = [
            {"start": "00:00:00.000", "end": "00:00:02.000", "shot_title": "A", "visual_description": "A", "action_camera": "A", "narrative_function": "A"},
            {"start": "00:00:02.000", "end": "00:00:04.000", "shot_title": "B", "visual_description": "B", "action_camera": "B", "narrative_function": "B"},
        ]
        first_id = timeline_analysis_id(shots[0], 0)
        session = {"analyzedShots": {first_id: {}}}
        self.assertEqual(analysis_target_ids(shots, session), [timeline_analysis_id(shots[1], 1)])
        self.assertEqual(len(timeline_revision(shots)), 16)

    def test_memory_update_explicitly_omits_video(self) -> None:
        prompt = build_memory_update_prompt(
            "Test Film",
            [{"start": "00:00:00.000", "end": "00:00:02.000", "shot_title": "Opening"}],
            {"sentences": []},
            "The entrance may be a reversal.",
            {"synopsis": "A person enters."},
        )
        self.assertIn("video is intentionally not attached", prompt)
        self.assertIn("The entrance may be a reversal", prompt)

    def test_qwen_omni_uses_streaming_text_output(self) -> None:
        with patch("film_study_tool.ui_server.call_chat_completion_stream", return_value="{}") as stream_call:
            call_qwen_video(
                "test-key",
                "qwen3.5-omni-plus",
                "Return JSON.",
                "Analyze it.",
                Path(__file__),
            )
        request = stream_call.call_args.args[2]
        self.assertTrue(request["stream"])
        self.assertEqual(request["modalities"], ["text"])
        self.assertNotIn("max_tokens", request)

    def test_qwen_omni_accepts_chronological_video_segments(self) -> None:
        with patch("film_study_tool.ui_server.call_chat_completion_stream", return_value="{}") as stream_call:
            call_qwen_video(
                "test-key",
                "qwen3.5-omni-plus",
                "Return JSON.",
                "Analyze it.",
                [Path(__file__), Path(__file__)],
            )
        content = stream_call.call_args.args[2]["messages"][1]["content"]
        self.assertEqual([item["type"] for item in content], ["video_url", "video_url", "text"])
        self.assertIn("consecutive transport segments", content[-1]["text"])


class AiBoundarySuggestionTests(unittest.TestCase):
    def test_existing_boundaries_are_filtered_and_hard_cuts_snap_to_ffmpeg(self) -> None:
        shots = [
            {"start": "00:00:00.000", "end": "00:00:05.000"},
            {"start": "00:00:05.000", "end": "00:00:10.000"},
        ]
        transitions = [
            {"time_seconds": 5.1, "transition_type": "hard_cut", "confidence": "high"},
            {
                "time_seconds": 7.2,
                "transition_type": "hard_cut",
                "confidence": "high",
                "before_details": {"shot_title": "Before Cut", "visual_description": "First image"},
                "after_details": {"shot_title": "After Cut", "visual_description": "Second image"},
            },
        ]
        suggestions = normalize_ai_transition_suggestions(
            transitions,
            shots,
            [5.0],
            [(7.05, 0.4), (7.25, 0.8)],
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["time_seconds"], 7.25)
        self.assertEqual(suggestions[0]["sourceShot"], 2)
        self.assertEqual(suggestions[0]["before_details"]["shot_title"], "Before Cut")
        self.assertEqual(suggestions[0]["after_details"]["shot_title"], "After Cut")


if __name__ == "__main__":
    unittest.main()
