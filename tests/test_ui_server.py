from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from film_study_tool.ui_server import (
    ANALYSIS_JOBS,
    CAPTION_LANGS,
    ServerConfig,
    analysis_job_status,
    analysis_scope_intervals,
    analysis_scope_revision,
    analysis_target_ids,
    ask_this_film,
    append_analysis_run,
    apply_ai_cuts_to_timeline,
    apply_caption_cues_to_rows,
    apply_identity_replacements,
    begin_api_usage_collection,
    build_narrative_continuity_prompt,
    build_memory_update_prompt,
    build_llm_text_prompt,
    call_chat_completion_stream,
    call_qwen_text,
    call_qwen_video,
    caption_evidence_by_analysis_id,
    clean_caption_text,
    create_library_folder,
    deduplicate_transition_candidates,
    delete_library_folder,
    download_source_video,
    extract_embedded_english_subtitles,
    export_film_study_for_ai,
    finish_api_usage_collection,
    format_duration_units,
    generate_shot_details_with_native_video,
    merge_film_memory,
    merge_generated_shot_details,
    normalize_ai_generated_outline,
    normalize_ai_transition_suggestions,
    normalize_shot_row,
    list_library_folders,
    load_analysis_runs,
    list_projects,
    load_film_conversation,
    open_project_directory,
    rename_library_folder,
    record_api_usage,
    reconcile_candidate_decisions,
    reconcile_narrative_continuity,
    parse_generated_analysis,
    plan_analysis_batches,
    prioritize_ffmpeg_candidates_for_ai,
    extract_urls_from_text,
    shot_requires_analysis,
    source_url_key,
    timeline_analysis_id,
    timeline_revision,
    update_analysis_job,
    update_project_metadata,
    validate_grounded_analysis_rows,
)


class UrlImportIdentityTests(unittest.TestCase):
    def test_distinct_youtube_watch_urls_do_not_collapse(self) -> None:
        text = "\n".join([
            "https://www.youtube.com/watch?v=uaWA2GbcnJU",
            "https://www.youtube.com/watch?v=nBobmn_u98w",
            "https://www.youtube.com/watch?v=dBw5rjWjZSk",
        ])

        self.assertEqual(len(extract_urls_from_text(text)), 3)
        self.assertEqual(
            [source_url_key(url) for url in extract_urls_from_text(text)],
            [
                "youtube.com/watch?v=uaWA2GbcnJU",
                "youtube.com/watch?v=nBobmn_u98w",
                "youtube.com/watch?v=dBw5rjWjZSk",
            ],
        )

    def test_youtube_aliases_share_one_video_identity(self) -> None:
        self.assertEqual(
            source_url_key("https://youtu.be/uaWA2GbcnJU?si=tracking"),
            source_url_key("https://www.youtube.com/watch?v=uaWA2GbcnJU&utm_source=test"),
        )

    def test_video_download_survives_best_effort_caption_pass(self) -> None:
        calls = []
        config = ServerConfig(
            outputs_dir=Path("outputs"),
            static_dir=Path("static"),
            data_dir=Path("data"),
        )

        def fake_run(args):
            calls.append(args)
            if "--skip-download" not in args:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="caption rate limited")

        fake_video = Path("Unsung_Hero_20260723_000000.mp4")
        with (
            patch("film_study_tool.ui_server._run", side_effect=fake_run),
            patch("film_study_tool.ui_server.downloaded_video_has_audio", return_value=True),
            patch.object(Path, "glob", return_value=[fake_video]),
            patch.object(Path, "stat", return_value=SimpleNamespace(st_mtime=1)),
        ):
            video_path = download_source_video(
                config,
                "yt-dlp",
                "https://www.youtube.com/watch?v=uaWA2GbcnJU",
                "Unsung Hero",
            )

        self.assertEqual(video_path.suffix, ".mp4")
        self.assertNotIn("--write-subs", calls[0])
        self.assertIn("--skip-download", calls[1])
        self.assertEqual(calls[1][calls[1].index("--sub-langs") + 1], CAPTION_LANGS)

    def test_tiktok_retries_when_a_claimed_av_format_has_no_audio_stream(self) -> None:
        calls = []
        config = ServerConfig(
            outputs_dir=Path("outputs"),
            static_dir=Path("static"),
            data_dir=Path("data"),
        )
        fake_video = Path("TikTok_20260726_000000.mp4")

        def fake_run(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch("film_study_tool.ui_server._run", side_effect=fake_run),
            patch(
                "film_study_tool.ui_server.downloaded_video_has_audio",
                side_effect=[False, True],
            ),
            patch.object(Path, "glob", return_value=[fake_video]),
            patch.object(Path, "stat", return_value=SimpleNamespace(st_mtime=1)),
        ):
            video_path = download_source_video(
                config,
                "yt-dlp",
                "https://www.tiktok.com/@creator/video/123",
                "TikTok",
            )

        first_selector = calls[0][calls[0].index("-f") + 1]
        retry_selector = calls[1][calls[1].index("-f") + 1]
        self.assertIn("format_id^=h264", first_selector)
        self.assertEqual(retry_selector, "download")
        self.assertIn("--skip-download", calls[2])
        self.assertEqual(video_path, fake_video)


class LibraryFolderTests(unittest.TestCase):
    def workspace(self) -> Path:
        root = Path(__file__).parent / "test-tmp"
        path = root / self._testMethodName
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        def cleanup() -> None:
            shutil.rmtree(path, ignore_errors=True)
            try:
                root.rmdir()
            except OSError:
                pass
        self.addCleanup(cleanup)
        return path

    def make_project(self, outputs_dir: Path, project_id: str, group_path=None) -> Path:
        project_dir = outputs_dir / project_id
        project_dir.mkdir(parents=True)
        (project_dir / "manifest.json").write_text("[]", encoding="utf-8")
        if group_path is not None:
            (project_dir / "project_meta.json").write_text(
                json.dumps({"groupPath": group_path}),
                encoding="utf-8",
            )
        return project_dir

    def test_existing_group_metadata_migrates_to_real_directory(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        self.make_project(outputs_dir, "Film_20260723_120000", ["Heartfelt"])

        projects = list_projects(outputs_dir)

        self.assertEqual(projects[0]["groupPath"], ["Heartfelt"])
        self.assertTrue((outputs_dir / "Heartfelt" / "Film_20260723_120000" / "manifest.json").exists())

    def test_title_edit_and_drag_move_persist_in_project_metadata(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        self.make_project(outputs_dir, "Film_20260723_120000")
        create_library_folder(outputs_dir, {"path": ["Advertisements"]})

        update_project_metadata(
            outputs_dir,
            "Film_20260723_120000",
            {"title": "A Better Film Title", "groupPath": ["Advertisements"]},
        )
        projects = list_projects(outputs_dir)

        self.assertEqual(projects[0]["name"], "A Better Film Title")
        self.assertEqual(projects[0]["groupPath"], ["Advertisements"])
        self.assertTrue((outputs_dir / "Advertisements" / "Film_20260723_120000").is_dir())

    def test_empty_folder_and_rename_are_real_directories(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        create_library_folder(outputs_dir, {"path": ["References", "Warm Films"]})

        rename_library_folder(
            outputs_dir,
            {"path": ["References", "Warm Films"], "newPath": ["References", "Heartfelt Films"]},
        )

        self.assertIn(["References", "Heartfelt Films"], list_library_folders(outputs_dir))
        self.assertFalse((outputs_dir / "References" / "Warm Films").exists())
        self.assertTrue((outputs_dir / "References" / "Heartfelt Films").is_dir())

    def test_non_library_output_directory_is_not_shown_as_folder(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        debug_dir = outputs_dir / "alignment_debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "frame.jpg").write_bytes(b"debug")

        self.assertEqual(list_library_folders(outputs_dir), [])

    def test_empty_library_folder_can_be_deleted(self) -> None:
        workspace = self.workspace()
        outputs_dir = workspace / "outputs"
        data_dir = workspace / "data"
        create_library_folder(outputs_dir, {"path": ["Empty Folder"]})
        config = ServerConfig(outputs_dir=outputs_dir, static_dir=workspace, data_dir=data_dir)

        result = delete_library_folder(config, {"path": ["Empty Folder"]})

        self.assertTrue(result["ok"])
        self.assertEqual(result["projectsDeleted"], [])
        self.assertFalse((outputs_dir / "Empty Folder").exists())

    def test_folder_only_tree_can_be_deleted(self) -> None:
        workspace = self.workspace()
        outputs_dir = workspace / "outputs"
        data_dir = workspace / "data"
        create_library_folder(outputs_dir, {"path": ["Parent", "Empty Child"]})
        config = ServerConfig(outputs_dir=outputs_dir, static_dir=workspace, data_dir=data_dir)

        result = delete_library_folder(config, {"path": ["Parent"]})

        self.assertTrue(result["ok"])
        self.assertEqual(result["projectsDeleted"], [])
        self.assertFalse((outputs_dir / "Parent").exists())

    def test_open_project_directory_is_scoped_to_known_project(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        project_dir = self.make_project(outputs_dir, "Film_20260723_120000")
        workbook_path = project_dir / "film_study.xlsx"
        workbook_path.write_bytes(b"workbook")

        with patch("film_study_tool.ui_server.subprocess.Popen") as popen:
            result = open_project_directory(outputs_dir, project_dir.name)

        self.assertTrue(result["ok"])
        popen.assert_called_once_with(["explorer.exe", f'/select,"{workbook_path.resolve()}"'])


class AnalysisRunHistoryTests(unittest.TestCase):
    def workspace(self) -> Path:
        root = Path(__file__).parent / "test-tmp"
        path = root / self._testMethodName
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)

        def cleanup() -> None:
            shutil.rmtree(path, ignore_errors=True)
            try:
                root.rmdir()
            except OSError:
                pass

        self.addCleanup(cleanup)
        return path

    def test_analysis_runs_persist_as_append_only_history(self) -> None:
        project_dir = self.workspace() / "Film"
        project_dir.mkdir()
        first = {
            "runId": "run-1",
            "status": "completed",
            "completedAt": "2026-07-23T10:00:00",
            "elapsedSeconds": 82,
            "provider": "qwen",
            "model": "qwen3.5-omni-plus",
            "mode": "full",
            "analyzedShotCount": 12,
            "totalShotCount": 12,
            "usage": {
                "apiCalls": 2,
                "totalTokens": 4200,
                "tokensReported": True,
                "costUsd": 0.12,
            },
        }
        second = {
            "runId": "run-2",
            "status": "failed",
            "completedAt": "2026-07-23T11:00:00",
            "elapsedSeconds": 17,
            "provider": "qwen",
            "model": "qwen3.5-omni-plus",
            "mode": "incremental",
            "error": "Access denied",
            "usage": {"apiCalls": 1, "tokensReported": False, "costUsd": None},
        }

        append_analysis_run(project_dir, first)
        append_analysis_run(project_dir, second)
        reloaded = load_analysis_runs(project_dir)

        self.assertEqual([run["runId"] for run in reloaded], ["run-2", "run-1"])
        self.assertEqual(reloaded[0]["error"], "Access denied")
        self.assertEqual(reloaded[1]["usage"]["totalTokens"], 4200)

    def test_legacy_session_history_remains_visible(self) -> None:
        project_dir = self.workspace() / "Film"
        project_dir.mkdir()
        session = {
            "provider": "qwen",
            "model": "qwen3.5-omni-plus",
            "history": [{
                "at": "2026-07-22T09:00:00",
                "mode": "full",
                "analyzedShotCount": 8,
                "provider": "qwen",
                "model": "qwen3.5-omni-plus",
                "usage": {"apiCalls": 1, "tokensReported": False, "costUsd": None},
            }],
        }

        runs = load_analysis_runs(project_dir, session)

        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["legacy"])
        self.assertIsNone(runs[0]["elapsedSeconds"])
        self.assertEqual(runs[0]["analyzedShotCount"], 8)


class ApiUsageTests(unittest.TestCase):
    def test_usage_records_are_aggregated_across_batches_and_retries(self) -> None:
        begin_api_usage_collection()
        record_api_usage(
            "qwen",
            "qwen3.5-omni-plus",
            {"usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}},
        )
        record_api_usage(
            "qwen",
            "qwen3.5-omni-plus",
            {"usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600}},
        )

        usage = finish_api_usage_collection()

        self.assertEqual(usage["apiCalls"], 2)
        self.assertEqual(usage["inputTokens"], 1500)
        self.assertEqual(usage["outputTokens"], 300)
        self.assertEqual(usage["totalTokens"], 1800)
        self.assertEqual(len(usage["calls"]), 2)
        self.assertEqual(usage["calls"][0]["totalTokens"], 1200)
        self.assertEqual(usage["calls"][1]["totalTokens"], 600)
        self.assertTrue(usage["tokensReported"])
        self.assertIsNone(usage["costUsd"])
        self.assertEqual(usage["costSource"], "unavailable")

    def test_configured_token_rates_produce_labeled_estimate(self) -> None:
        with patch.dict(
            "film_study_tool.ui_server.os.environ",
            {
                "QWEN_INPUT_COST_PER_MILLION_USD": "2",
                "QWEN_OUTPUT_COST_PER_MILLION_USD": "6",
            },
        ):
            begin_api_usage_collection()
            record_api_usage(
                "qwen",
                "qwen3.5-omni-plus",
                {"usage": {"input_tokens": 1_000_000, "output_tokens": 500_000}},
            )
            usage = finish_api_usage_collection()

        self.assertEqual(usage["costUsd"], 5)
        self.assertEqual(usage["costSource"], "configured_rates")


class AnalysisJobTimingTests(unittest.TestCase):
    def tearDown(self) -> None:
        ANALYSIS_JOBS.clear()

    @patch("film_study_tool.ui_server.time.monotonic")
    def test_completed_job_elapsed_time_is_frozen(self, monotonic) -> None:
        monotonic.side_effect = [100.0, 125.0, 900.0]
        update_analysis_job(
            "Film",
            status="running",
            _startedMonotonic=monotonic(),
        )
        completed = update_analysis_job("Film", status="completed")
        later = analysis_job_status("Film")

        self.assertEqual(completed["elapsedSeconds"], 25)
        self.assertEqual(later["elapsedSeconds"], 25)


class AnalysisScopeAndHandoffTests(unittest.TestCase):
    def workspace(self) -> Path:
        root = Path(__file__).parent / "test-tmp"
        path = root / self._testMethodName
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def rows(self) -> list[dict[str, object]]:
        return [
            {
                "shot": 1,
                "start": "00:00:00.000",
                "end": "00:00:10.000",
                "shot_title": "Long Intro",
                "analysis_excluded": True,
            },
            {
                "shot": 2,
                "start": "00:00:10.000",
                "end": "00:00:15.000",
                "shot_title": "Relevant Moment",
                "visual_description": "A speaker steps into warm window light.",
                "narrative_function": "The selected passage begins.",
            },
            {
                "shot": 3,
                "start": "00:00:15.000",
                "end": "00:00:30.000",
                "shot_title": "Rest of Episode",
                "analysis_excluded": True,
            },
        ]

    def test_analysis_targets_and_intervals_omit_excluded_shots(self) -> None:
        rows = self.rows()

        target_ids = analysis_target_ids(rows, {}, force_all=True)

        self.assertEqual(target_ids, [timeline_analysis_id(rows[1], 1)])
        self.assertEqual(analysis_scope_intervals(rows), [(10.0, 15.0)])
        focused_revision = analysis_scope_revision(rows)
        rows[0]["analysis_excluded"] = False
        self.assertNotEqual(focused_revision, analysis_scope_revision(rows))

    def test_duration_units_only_show_needed_leading_units(self) -> None:
        self.assertEqual(format_duration_units(3.75), "3.75s")
        self.assertEqual(format_duration_units(63.75), "1m 03.75s")
        self.assertEqual(format_duration_units(3723.75), "1h 02m 03.75s")
        self.assertEqual(format_duration_units(59.999), "1m 00.00s")

    def test_markdown_export_focuses_on_included_scope(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        project_dir = outputs_dir / "Test_Film"
        project_dir.mkdir(parents=True)
        (project_dir / "manifest.json").write_text(json.dumps(self.rows()), encoding="utf-8")
        (project_dir / "study_context.txt").write_text(
            "I think the light marks a turn.",
            encoding="utf-8",
        )
        (project_dir / "analysis_session.json").write_text(
            json.dumps({
                "hasFullAnalysis": True,
                "model": "qwen3.5-omni-plus",
                "filmMemory": {"synopsis": "A selected passage."},
            }),
            encoding="utf-8",
        )

        result = export_film_study_for_ai(outputs_dir, project_dir.name)

        self.assertIn("### Shot #2: Relevant Moment", result["markdown"])
        self.assertNotIn("### Shot #1: Long Intro", result["markdown"])
        self.assertIn("## Excluded From Analysis", result["markdown"])
        self.assertIn("I think the light marks a turn.", result["markdown"])
        self.assertTrue((project_dir / "film_study_for_ai.md").exists())

    def test_film_conversation_replays_saved_context_and_persists_messages(self) -> None:
        outputs_dir = self.workspace() / "outputs"
        project_dir = outputs_dir / "Test_Film"
        project_dir.mkdir(parents=True)
        (project_dir / "manifest.json").write_text(json.dumps(self.rows()), encoding="utf-8")
        (project_dir / "analysis_session.json").write_text(
            json.dumps({
                "hasFullAnalysis": True,
                "model": "qwen3.5-omni-plus",
                "analysisRevision": 3,
                "filmMemory": {"synopsis": "A selected passage."},
            }),
            encoding="utf-8",
        )

        with (
            patch.dict("film_study_tool.ui_server.os.environ", {"QWEN_API_KEY": "test-key"}),
            patch(
                "film_study_tool.ui_server.call_qwen_conversation",
                return_value="The warm light marks a change in authority.",
            ) as call,
        ):
            result = ask_this_film(
                outputs_dir,
                project_dir.name,
                {"question": "What does the light accomplish?"},
            )

        messages = load_film_conversation(project_dir)["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(result["answer"], "The warm light marks a change in authority.")
        sent_messages = call.call_args.args[2]
        self.assertIn("### Shot #2: Relevant Moment", sent_messages[0]["content"])
        self.assertEqual(sent_messages[-1]["content"], "What does the light accomplish?")


class TransitionCandidateTests(unittest.TestCase):
    def test_adjacent_detector_frames_keep_only_the_strongest_candidate(self) -> None:
        candidates = [
            (3.700, 0.21),
            (3.733, 0.42),
            (3.900, 0.31),
            (8.000, 0.28),
        ]

        self.assertEqual(
            deduplicate_transition_candidates(candidates),
            [(3.733, 0.42), (3.9, 0.31), (8.0, 0.28)],
        )


class CaptionAssignmentTests(unittest.TestCase):
    def workspace(self) -> Path:
        root = Path(__file__).parent / "test-tmp"
        path = root / self._testMethodName
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    @patch("film_study_tool.ui_server._require_binary", side_effect=lambda name: name)
    @patch("film_study_tool.ui_server._run")
    def test_embedded_english_subtitle_track_is_extracted(self, run, _require_binary) -> None:
        workspace = self.workspace()
        video_path = workspace / "film.mkv"
        video_path.write_bytes(b"video")

        def fake_run(command):
            if command[0] == "ffprobe":
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({
                        "streams": [
                            {"index": 5, "codec_name": "subrip", "tags": {"language": "chi"}},
                            {"index": 8, "codec_name": "ass", "tags": {"language": "eng", "title": "English"}},
                        ]
                    }),
                    stderr="",
                )
            output_path = Path(command[-1])
            output_path.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nHello there.\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        run.side_effect = fake_run
        output = extract_embedded_english_subtitles(workspace / "project", video_path)

        self.assertIsNotNone(output)
        self.assertTrue(output.is_file())
        ffmpeg_command = run.call_args_list[1].args[0]
        self.assertEqual(ffmpeg_command[ffmpeg_command.index("-map") + 1], "0:8")

    def test_ass_karaoke_markup_is_removed_from_dialogue(self) -> None:
        english = (
            '<font face="ObeliskMdITC TT">{\\an3}'
            "<font>They're the prey, and we're the hunters.</font></font>"
        )
        karaoke = (
            '<font face="ObeliskMdITC TT">{\\an7}'
            "<font>m 60 0 b 45 21 21 45 0 60</font></font>"
        )

        self.assertEqual(clean_caption_text(english), "They're the prey, and we're the hunters.")
        self.assertEqual(clean_caption_text(karaoke), "")

    def test_normalized_shot_duration_is_recomputed_from_current_timestamps(self) -> None:
        row = {
            "shot": 1,
            "start": "00:00:00.000",
            "end": "00:02:33.077",
            "duration_seconds": 0.925,
        }

        normalized = normalize_shot_row(row, 0, self.workspace())

        self.assertEqual(normalized["duration_seconds"], 153.077)

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

    def test_caption_evidence_uses_current_edited_timeline_ids(self) -> None:
        rows = [
            {
                "analysis_id": "edited_a",
                "start": "00:00:00.000",
                "end": "00:00:03.000",
            },
            {
                "analysis_id": "edited_b",
                "start": "00:00:03.000",
                "end": "00:00:06.000",
            },
        ]
        cues = [
            {"start": 1, "end": 2, "text": "We need a plan."},
            {"start": 3.5, "end": 5, "text": "Time is running out."},
        ]

        self.assertEqual(
            caption_evidence_by_analysis_id(rows, cues),
            {
                "edited_a": "We need a plan.",
                "edited_b": "Time is running out.",
            },
        )


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

    def test_rows_without_analysis_ids_are_never_merged_by_position(self) -> None:
        current = [
            {"analysis_id": "current_a", "shot": 1, "shot_title": "Keep A", "analysis_stale": True},
            {"analysis_id": "current_b", "shot": 2, "shot_title": "Keep B", "analysis_stale": True},
        ]
        generated = [
            {"shot": 1, "shot_title": "Wrong A"},
            {"shot": 2, "shot_title": "Wrong B"},
        ]

        merged = merge_generated_shot_details(current, generated)

        self.assertEqual([row["shot_title"] for row in merged], ["Keep A", "Keep B"])
        self.assertTrue(all(row["analysis_stale"] for row in merged))

    def test_impending_is_not_treated_as_pending_analysis(self) -> None:
        row = {
            "start": "00:00:00.000",
            "end": "00:00:01.000",
            "shot_title": "Hope Before Loss",
            "visual_description": "A complete visual description.",
            "action_camera": "A complete action description.",
            "narrative_function": "Builds optimism before impending tragedy.",
        }
        session = {"analyzedShots": {timeline_analysis_id(row, 0): {}}}

        self.assertFalse(shot_requires_analysis(row, 0, session))

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
        self.assertIn(
            'top-level keys named "shots", "transitions", "candidate_decisions", and "film_memory"',
            prompt,
        )
        self.assertIn('"scene_score": 0.42', prompt)
        self.assertIn("A montage is a filmic sentence made from multiple individual shots", prompt)

    def test_native_video_is_called_once_for_details_and_cuts(self) -> None:
        input_shot = {"start": "00:00:00.000", "end": "00:00:02.000"}
        analysis_id = timeline_analysis_id(input_shot, 0)
        progress_events = []
        response = (
            f'{{"shots":[{{"analysis_id":"{analysis_id}","shot":1,"shot_title":"Opening",'
            '"visual_description":"Wide shot of a doorway.","audio_dialogue":"Room tone.",'
            '"action_camera":"0.0-2.0s: A figure enters. Camera remains static.",'
            '"camera_movement_type":"static","camera_movement_intensity":"none",'
            '"camera_movement_confidence":"high","camera_movement_evidence":"Framing is fixed.",'
            '"narrative_function":"Introduces the figure."}],'
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
                shots=[input_shot],
                outline={"sentences": []},
                user_context="",
                ffmpeg_candidates=[(1.25, 0.42)],
                progress_callback=lambda **event: progress_events.append(event),
            )
        self.assertEqual(qwen_call.call_count, 1)
        self.assertEqual(provider, "qwen")
        self.assertEqual(memory, {})
        self.assertEqual(rows[0]["shot_title"], "Opening")
        self.assertEqual(transitions[0]["transition_type"], "dissolve")
        self.assertEqual(
            [event["phase"] for event in progress_events],
            ["preparing_batch", "waiting_api", "validating", "batch_complete"],
        )

    def test_qwen_connection_reset_retries_with_essential_references_only(self) -> None:
        input_shot = {"start": "00:00:00.000", "end": "00:00:02.000"}
        analysis_id = timeline_analysis_id(input_shot, 0)
        response = json.dumps({
            "shots": [{
                "analysis_id": analysis_id,
                "shot_title": "Opening",
                "visual_description": "Wide shot of a doorway.",
                "audio_dialogue": "Room tone.",
                "action_camera": "A figure enters. Camera remains static.",
                "camera_movement_type": "static",
                "camera_movement_intensity": "none",
                "camera_movement_confidence": "high",
                "camera_movement_evidence": "Framing is fixed.",
                "narrative_function": "Introduces the figure.",
            }],
            "transitions": [],
            "candidate_decisions": [{
                "time_seconds": 1.0,
                "decision": "reject",
                "reason": "Continuous movement within one composition.",
            }],
        })
        progress_events = []
        with (
            patch("film_study_tool.ui_server.prepare_qwen_analysis_videos", return_value=[Path(__file__)]),
            patch(
                "film_study_tool.ui_server.shot_reference_images",
                return_value=[("shot", Path(__file__))],
            ),
            patch(
                "film_study_tool.ui_server.candidate_reference_images",
                return_value=[("candidate", Path(__file__))],
            ),
            patch(
                "film_study_tool.ui_server.call_qwen_video",
                side_effect=[
                    ValueError("Could not reach Qwen: [WinError 10054] connection was forcibly closed"),
                    ValueError("Qwen stream ended before completion; partial response discarded"),
                    response,
                ],
            ) as qwen_call,
            patch("film_study_tool.ui_server.time.sleep") as sleep_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            rows, _transitions, _memory, provider, _model = generate_shot_details_with_native_video(
                model="qwen3.5-omni-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Test Film",
                project_dir=Path(__file__).parent,
                shots=[input_shot],
                outline={"sentences": []},
                user_context="",
                ffmpeg_candidates=[(1.0, 0.3)],
                progress_callback=lambda **event: progress_events.append(event),
            )

        self.assertEqual(qwen_call.call_count, 3)
        self.assertEqual(len(qwen_call.call_args_list[0].kwargs["reference_images"]), 2)
        self.assertEqual(len(qwen_call.call_args_list[1].kwargs["reference_images"]), 1)
        self.assertEqual(len(qwen_call.call_args_list[2].kwargs["reference_images"]), 1)
        self.assertEqual(sleep_call.call_count, 2)
        self.assertIn("retrying", [event["phase"] for event in progress_events])
        self.assertEqual(provider, "qwen")
        self.assertEqual(rows[0]["shot_title"], "Opening")

    def test_incomplete_grounded_batch_retries_only_that_batch(self) -> None:
        input_shot = {"start": "00:00:00.000", "end": "00:00:02.000"}
        analysis_id = timeline_analysis_id(input_shot, 0)
        incomplete_row = {
            "analysis_id": analysis_id,
            "shot_title": "Opening",
            "visual_description": "Wide doorway.",
            "action_camera": "A figure enters.",
            "camera_movement_type": "static",
            "camera_movement_intensity": "none",
            "camera_movement_confidence": "high",
            "camera_movement_evidence": "Fixed frame.",
            "narrative_function": "Introduces the figure.",
        }
        incomplete = json.dumps({"shots": [incomplete_row], "transitions": []})
        complete = json.dumps({
            "shots": [{**incomplete_row, "audio_dialogue": "No dialogue."}],
            "transitions": [],
        })
        with (
            patch("film_study_tool.ui_server.prepare_qwen_analysis_videos", return_value=[Path(__file__)]),
            patch("film_study_tool.ui_server.call_qwen_video", side_effect=[incomplete, complete]) as qwen_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            rows, _transitions, _memory, provider, _model = generate_shot_details_with_native_video(
                model="qwen3.5-omni-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Test Film",
                project_dir=Path(__file__).parent,
                shots=[input_shot],
                outline={"sentences": []},
                user_context="",
                ffmpeg_candidates=[],
            )

        self.assertEqual(qwen_call.call_count, 2)
        self.assertIn("VALIDATION RETRY", qwen_call.call_args.args[3])
        self.assertEqual(provider, "qwen")
        self.assertEqual(rows[0]["audio_dialogue"], "No dialogue.")

    def test_repeated_audio_only_omission_uses_current_interval_audio(self) -> None:
        input_shot = {
            "start": "00:00:00.000",
            "end": "00:00:02.000",
            "audio_dialogue": "No spoken dialogue; instrumental music continues.",
        }
        analysis_id = timeline_analysis_id(input_shot, 0)
        incomplete = json.dumps({
            "shots": [{
                "analysis_id": analysis_id,
                "shot_title": "Opening",
                "visual_description": "Wide doorway.",
                "action_camera": "A figure enters.",
                "camera_movement_type": "static",
                "camera_movement_intensity": "none",
                "camera_movement_confidence": "high",
                "camera_movement_evidence": "Fixed frame.",
                "narrative_function": "Introduces the figure.",
            }],
            "transitions": [],
        })
        with (
            patch("film_study_tool.ui_server.prepare_qwen_analysis_videos", return_value=[Path(__file__)]),
            patch("film_study_tool.ui_server.call_qwen_video", side_effect=[incomplete, incomplete]) as qwen_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            rows, _transitions, _memory, _provider, _model = generate_shot_details_with_native_video(
                model="qwen3.5-omni-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Test Film",
                project_dir=Path(__file__).parent,
                shots=[input_shot],
                outline={"sentences": []},
                user_context="",
                ffmpeg_candidates=[],
            )

        self.assertEqual(qwen_call.call_count, 2)
        self.assertEqual(
            rows[0]["audio_dialogue"],
            "No spoken dialogue; instrumental music continues.",
        )

    def test_grounded_batch_requires_every_exact_id_and_core_field(self) -> None:
        complete = {
            "analysis_id": "shot_a",
            "shot_title": "Opening",
            "visual_description": "Wide shot of a doorway.",
            "audio_dialogue": "Room tone.",
            "action_camera": "A figure enters. Camera remains static.",
            "camera_movement_type": "static",
            "camera_movement_intensity": "none",
            "camera_movement_confidence": "high",
            "camera_movement_evidence": "Framing is fixed.",
            "narrative_function": "Introduces the figure.",
        }
        self.assertEqual(validate_grounded_analysis_rows([complete], ["shot_a"]), [complete])
        with self.assertRaisesRegex(ValueError, "omitted requested analysis IDs"):
            validate_grounded_analysis_rows([complete], ["shot_a", "shot_b"])
        with self.assertRaisesRegex(ValueError, "omitted required fields"):
            validate_grounded_analysis_rows([{**complete, "action_camera": ""}], ["shot_a"])
        with self.assertRaisesRegex(ValueError, "duplicate analysis_id"):
            validate_grounded_analysis_rows([complete, complete], ["shot_a"])

    def test_film_memory_accumulates_across_batches(self) -> None:
        first = merge_film_memory({}, {
            "synopsis": "A daughter follows her father to the water.",
            "motifs": ["Bicycles"],
        })
        second = merge_film_memory(first, {
            "synopsis": "A daughter follows her father to the water. The father rows away, leaving her ashore.",
            "motifs": ["Bicycles", "Water"],
        })

        self.assertNotIn("sequence_summaries", second)
        self.assertIn("follows her father", second["synopsis"])
        self.assertIn("rows away", second["synopsis"])
        self.assertEqual(second["motifs"], ["Bicycles", "Water"])

    def test_narrative_continuity_prompt_contains_complete_chronology(self) -> None:
        shots = [
            {
                "analysis_id": "shot_a",
                "shot": 1,
                "start": "00:00:00.000",
                "end": "00:00:02.000",
                "shot_title": "Father and Daughter Ride",
                "visual_description": "A father and daughter ride bicycles together.",
            },
            {
                "analysis_id": "shot_b",
                "shot": 2,
                "start": "00:00:02.000",
                "end": "00:00:04.000",
                "shot_title": "Father Stops at Water",
                "visual_description": "The same father stops while his daughter watches.",
            },
        ]
        generated = [
            {"analysis_id": "shot_a", "narrative_function": "Introduces a father."},
            {"analysis_id": "shot_b", "narrative_function": "Introduces a man at the water."},
        ]

        prompt, rewrite_ids, generate_outline = build_narrative_continuity_prompt(
            "Father and Daughter",
            shots,
            generated,
            {"sentences": []},
            "",
            {},
        )

        self.assertEqual(rewrite_ids, ["shot_a", "shot_b"])
        self.assertTrue(generate_outline)
        self.assertLess(prompt.index('"shot": 1'), prompt.index('"shot": 2'))
        self.assertIn("Do not call a character introduced", prompt)
        self.assertIn("complete corrected timeline", prompt)
        self.assertIn("Assign every shot exactly once", prompt)

    def test_narrative_continuity_prompt_prioritizes_downloaded_subtitles(self) -> None:
        shots = [{
            "analysis_id": "shot_a",
            "shot": 1,
            "start": "00:00:00.000",
            "end": "00:00:04.000",
            "visual_description": "Soldiers confer beside a wall.",
        }]
        generated = [{
            "analysis_id": "shot_a",
            "audio_dialogue": "Indistinct foreign-language speech.",
            "narrative_function": "The group continues talking.",
        }]

        prompt, rewrite_ids, _generate_outline = build_narrative_continuity_prompt(
            "Pyxis Speech",
            shots,
            generated,
            {"sentences": []},
            "",
            {},
            caption_cues=[{
                "start": 0.5,
                "end": 3.5,
                "text": "The Titans aren't our only enemies.",
            }],
        )

        self.assertEqual(rewrite_ids, ["shot_a"])
        self.assertIn('"downloaded_subtitle_dialogue": "The Titans aren\'t our only enemies."', prompt)
        self.assertIn('"audio_soundtrack_observation": "Indistinct foreign-language speech."', prompt)
        self.assertIn("preferred source for the words being spoken", prompt)
        self.assertNotIn("The group continues talking.", prompt)
        self.assertIn('"current_narrative_function": ""', prompt)

    def test_rewrite_all_audits_identity_while_marking_manual_narrative(self) -> None:
        shots = [
            {
                "analysis_id": "shot_a",
                "shot": 1,
                "start": "00:00:00.000",
                "end": "00:00:02.000",
            },
            {
                "analysis_id": "shot_b",
                "shot": 2,
                "start": "00:00:02.000",
                "end": "00:00:04.000",
                "narrative_function": "Human correction.",
                "manual_fields": ["narrative_function"],
            },
        ]

        prompt, rewrite_ids, _generate_outline = build_narrative_continuity_prompt(
            "Test Film",
            shots,
            [],
            {"sentences": []},
            "",
            {},
            rewrite_all=True,
        )

        self.assertEqual(rewrite_ids, ["shot_a", "shot_b"])
        self.assertIn('"rewrite_narrative_function": false', prompt)
        self.assertIn('"manual_fields": [\n      "narrative_function"', prompt)

    def test_narrative_continuity_rewrites_batch_local_introductions(self) -> None:
        shots = [
            {
                "analysis_id": "shot_a",
                "shot": 1,
                "start": "00:00:00.000",
                "end": "00:00:02.000",
            },
            {
                "analysis_id": "shot_b",
                "shot": 2,
                "start": "00:00:02.000",
                "end": "00:00:04.000",
            },
        ]
        generated = [
            {"analysis_id": "shot_a", "narrative_function": "Introduces the father."},
            {"analysis_id": "shot_b", "narrative_function": "Introduces a man."},
        ]
        response = json.dumps({
            "shots": [
                {"analysis_id": "shot_a", "narrative_function": "Introduces the father and daughter together."},
                {
                    "analysis_id": "shot_b",
                    "narrative_function": "Continues the father's established journey and shifts it toward separation.",
                },
            ],
            "film_memory": {
                "synopsis": "A father and daughter travel together before separating.",
                "characters": [{"name": "Father", "first_seen_shot": 1}],
            },
            "sentences": [
                {
                    "id": "sentence-1",
                    "beat": "Journey",
                    "title": "Riding Toward Separation",
                    "idea": "Shared motion gives way to separation.",
                    "shotNumbers": [1, 2],
                }
            ],
        })
        with (
            patch("film_study_tool.ui_server.call_qwen_text", return_value=response) as text_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            reconciled, memory, outline, provider, model = reconcile_narrative_continuity(
                model="qwen3.5-omni-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Father and Daughter",
                project_dir=Path(__file__).parent,
                shots=shots,
                generated_rows=generated,
                outline={"sentences": []},
                user_context="",
                film_memory={},
                history_batch_number=2,
            )

        self.assertEqual(text_call.call_count, 1)
        self.assertIn("Continues the father's", reconciled[1]["narrative_function"])
        self.assertEqual(memory["characters"][0]["first_seen_shot"], 1)
        self.assertEqual(outline["sentences"][0]["shotNumbers"], [1, 2])
        self.assertEqual(provider, "qwen")
        self.assertEqual(model, "qwen3.7-plus")

    def test_narrative_continuity_retries_an_omitted_analysis_id(self) -> None:
        shots = [
            {"analysis_id": "shot_a", "shot": 1, "start": "00:00:00.000", "end": "00:00:01.000"},
            {"analysis_id": "shot_b", "shot": 2, "start": "00:00:01.000", "end": "00:00:02.000"},
        ]
        generated = [
            {"analysis_id": "shot_a", "narrative_function": "First provisional function."},
            {"analysis_id": "shot_b", "narrative_function": "Second provisional function."},
        ]
        incomplete = json.dumps({
            "shots": [{"analysis_id": "shot_a", "narrative_function": "First final function."}],
            "film_memory": {},
            "sentences": [],
        })
        complete = json.dumps({
            "shots": [
                {"analysis_id": "shot_a", "narrative_function": "First final function."},
                {"analysis_id": "shot_b", "narrative_function": "Second final function."},
            ],
            "film_memory": {},
            "sentences": [{
                "beat": "Beat 1",
                "title": "Complete Pair",
                "idea": "The two shots form one action.",
                "shotNumbers": [1, 2],
            }],
        })
        with (
            patch(
                "film_study_tool.ui_server.call_qwen_text",
                side_effect=[incomplete, complete],
            ) as text_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            reconciled, _memory, outline, _provider, _model = reconcile_narrative_continuity(
                model="qwen3.5-omni-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Test Film",
                project_dir=Path(__file__).parent,
                shots=shots,
                generated_rows=generated,
                outline={"sentences": []},
                user_context="",
                film_memory={},
                history_batch_number=2,
            )

        self.assertEqual(text_call.call_count, 2)
        self.assertEqual(reconciled[1]["narrative_function"], "Second final function.")
        self.assertEqual(outline["sentences"][0]["shotNumbers"], [1, 2])

    def test_narrative_continuity_keeps_grounded_provisional_text_after_two_omissions(self) -> None:
        shots = [
            {"analysis_id": "shot_a", "shot": 1, "start": "00:00:00.000", "end": "00:00:01.000"},
            {"analysis_id": "shot_b", "shot": 2, "start": "00:00:01.000", "end": "00:00:02.000"},
        ]
        generated = [
            {"analysis_id": "shot_a", "narrative_function": "Grounded first function."},
            {"analysis_id": "shot_b", "narrative_function": "Grounded second function."},
        ]
        incomplete = json.dumps({
            "shots": [{"analysis_id": "shot_a", "narrative_function": "Reconciled first function."}],
            "film_memory": {},
            "sentences": [],
        })
        with (
            patch(
                "film_study_tool.ui_server.call_qwen_text",
                side_effect=[incomplete, incomplete],
            ) as text_call,
            patch("film_study_tool.ui_server.write_llm_response"),
            patch("film_study_tool.ui_server.write_llm_error"),
        ):
            reconciled, _memory, _outline, _provider, _model = reconcile_narrative_continuity(
                model="qwen3.5-omni-plus",
                qwen_api_key="test-key",
                gemini_api_key="",
                project_name="Test Film",
                project_dir=Path(__file__).parent,
                shots=shots,
                generated_rows=generated,
                outline={"sentences": [{"shotNumbers": [1, 2]}]},
                user_context="",
                film_memory={},
                history_batch_number=2,
            )

        self.assertEqual(text_call.call_count, 2)
        self.assertEqual(reconciled[0]["narrative_function"], "Reconciled first function.")
        self.assertEqual(reconciled[1]["narrative_function"], "Grounded second function.")

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

    def test_accepted_analysis_clears_stale_scaffold_note(self) -> None:
        current = [{
            "analysis_id": "shot_a",
            "shot": 1,
            "shot_title": "Old",
            "notes": "Generated by the scaffold analyzer; prose fields are placeholders.",
        }]
        generated = [{"analysis_id": "shot_a", "shot_title": "New"}]

        merged = merge_generated_shot_details(current, generated)

        self.assertEqual(merged[0]["notes"], "")

    def test_generated_audio_replaces_pending_audio_scaffold(self) -> None:
        current = [{
            "analysis_id": "shot_a",
            "shot": 1,
            "audio_dialogue": (
                "Audio transcription pending. Future pass should align dialogue, voiceover, "
                "music, and sound effects to this shot interval."
            ),
        }]
        generated = [{
            "analysis_id": "shot_a",
            "audio_dialogue": "No dialogue; a restrained instrumental score continues.",
        }]

        merged = merge_generated_shot_details(current, generated)

        self.assertEqual(
            merged[0]["audio_dialogue"],
            "No dialogue; a restrained instrumental score continues.",
        )

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

    def test_incomplete_qwen_stream_is_rejected_instead_of_returning_partial_json(self) -> None:
        raw_stream = (
            'data: {"choices":[{"delta":{"content":"{\\\\\\"shots\\\\\\":["},'
            '"finish_reason":null}]}'
        )
        with patch("film_study_tool.ui_server.build_opener") as build_opener:
            response = build_opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = raw_stream.encode("utf-8")
            with self.assertRaisesRegex(ValueError, "stream ended before completion"):
                call_chat_completion_stream(
                    "https://example.invalid/chat/completions",
                    "test-key",
                    {"model": "qwen3.5-omni-plus", "messages": []},
                    "Qwen",
                )

    def test_complete_json_stream_without_final_marker_is_accepted(self) -> None:
        raw_stream = 'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":null}]}'
        with patch("film_study_tool.ui_server.build_opener") as build_opener:
            response = build_opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = raw_stream.encode("utf-8")
            content = call_chat_completion_stream(
                "https://example.invalid/chat/completions",
                "test-key",
                {
                    "model": "qwen3.5-omni-plus",
                    "messages": [],
                    "response_format": {"type": "json_object"},
                },
                "Qwen",
            )
        self.assertEqual(content, "{}")

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

    def test_qwen_omni_attaches_labeled_reference_stills(self) -> None:
        with patch("film_study_tool.ui_server.call_chat_completion_stream", return_value="{}") as stream_call:
            call_qwen_video(
                "test-key",
                "qwen3.5-omni-plus",
                "Return JSON.",
                "Analyze it.",
                Path(__file__),
                reference_images=[("SHOT 007 exact still", Path(__file__))],
            )
        content = stream_call.call_args.args[2]["messages"][1]["content"]
        self.assertEqual([item["type"] for item in content], ["video_url", "text", "image_url", "text"])
        self.assertEqual(content[1]["text"], "SHOT 007 exact still")

    def test_qwen_text_allows_a_complete_long_continuity_response(self) -> None:
        with patch("film_study_tool.ui_server.call_chat_completion_stream", return_value="{}") as stream_call:
            call_qwen_text(
                "test-key",
                "qwen3.5-omni-plus",
                "Return JSON.",
                "Rewrite the complete film.",
            )

        request_body = stream_call.call_args.args[2]
        self.assertEqual(request_body["max_tokens"], 32768)
        self.assertEqual(request_body["response_format"], {"type": "json_object"})

    def test_full_pass_is_split_into_grounded_batches(self) -> None:
        shots = [
            {
                "shot": index + 1,
                "start": f"00:00:{index * 3:02d}.000",
                "end": f"00:00:{(index + 1) * 3:02d}.000",
            }
            for index in range(12)
        ]
        batches = plan_analysis_batches(shots, None)
        self.assertEqual([len(batch) for batch in batches], [10, 2])

    def test_long_pass_uses_fewer_bounded_video_calls(self) -> None:
        shots = [
            {
                "shot": index + 1,
                "start": f"00:{index * 3 // 60:02d}:{index * 3 % 60:02d}.000",
                "end": f"00:{(index + 1) * 3 // 60:02d}:{(index + 1) * 3 % 60:02d}.000",
            }
            for index in range(61)
        ]

        batches = plan_analysis_batches(shots, None)

        self.assertEqual([len(batch) for batch in batches], [10, 10, 10, 10, 10, 10, 1])

    def test_noisy_detector_hits_are_clustered_before_ai_review(self) -> None:
        shots = [{
            "start": "00:00:00.000",
            "end": "00:00:10.000",
        }]
        candidates = [
            (5.0, 0.15),
            (5.1, 0.30),
            (5.2, 0.20),
            (8.0, 0.25),
        ]

        selected = prioritize_ffmpeg_candidates_for_ai(candidates, shots)

        self.assertEqual(selected, [(5.1, 0.30), (8.0, 0.25)])

    def test_identity_repair_neutralizes_model_names_but_preserves_manual_text(self) -> None:
        repaired = apply_identity_replacements(
            {
                "visual_description": "Levi kneels beside the gate.",
                "action_camera": "Levi looks up.",
                "narrative_function": "Levi reveals his fear.",
                "audio_dialogue": "Captain Levi, report.",
                "manual_fields": ["action_camera"],
            },
            [{"from": "Levi", "to": "the kneeling recruit"}],
        )

        self.assertEqual(
            repaired["visual_description"],
            "the kneeling recruit kneels beside the gate.",
        )
        self.assertEqual(repaired["action_camera"], "Levi looks up.")
        self.assertEqual(
            repaired["narrative_function"],
            "the kneeling recruit reveals his fear.",
        )
        self.assertEqual(repaired["audio_dialogue"], "Captain Levi, report.")

    def test_batch_prompt_preserves_global_shot_number(self) -> None:
        prompt = build_llm_text_prompt(
            "Test Film",
            [{"shot": 27, "start": "00:01:20.000", "end": "00:01:22.000"}],
            {"sentences": []},
            "",
            batch_number=3,
            batch_count=5,
        )
        self.assertIn('"shot": 27', prompt)
        self.assertIn("batch 3 of 5", prompt)
        self.assertIn("representative still", prompt)

    def test_prompt_requires_conservative_camera_and_transition_audit(self) -> None:
        prompt = build_llm_text_prompt(
            "Animated Test",
            [{"shot": 1, "start": "00:00:00.000", "end": "00:00:05.000"}],
            {"sentences": []},
            "",
        )
        self.assertIn("fixed background anchors", prompt)
        self.assertIn("beginning, middle, and end", prompt)
        self.assertIn("subject movement, not a pan", prompt)
        self.assertIn("visual rhyme rather than the same people", prompt)
        self.assertIn("Do not return an empty transitions array", prompt)

    def test_prompt_withholds_prior_model_prose_but_keeps_human_edits(self) -> None:
        prompt = build_llm_text_prompt(
            "Test Film",
            [{
                "shot": 3,
                "start": "00:00:05.000",
                "end": "00:00:07.000",
                "shot_title": "Human Title",
                "visual_description": "Wrong prior model scene",
                "action_camera": "Human action correction",
                "manual_fields": ["shot_title", "action_camera"],
            }],
            {"sentences": []},
            "",
        )
        self.assertIn("Human Title", prompt)
        self.assertIn("Human action correction", prompt)
        self.assertNotIn("Wrong prior model scene", prompt)
        self.assertIn("prior value was model-generated", prompt)

    def test_detail_prompt_includes_downloaded_subtitles_as_source_evidence(self) -> None:
        prompt = build_llm_text_prompt(
            "Pyxis Speech",
            [{
                "analysis_id": "shot_a",
                "shot": 3,
                "start": "00:00:05.000",
                "end": "00:00:09.000",
                "audio_dialogue": "Wrong prior model transcript",
            }],
            {"sentences": []},
            "",
            caption_cues=[{
                "start": 5.5,
                "end": 8.5,
                "text": "Staff officers, assemble!",
            }],
        )

        self.assertIn('"downloaded_subtitle_dialogue": "Staff officers, assemble!"', prompt)
        self.assertNotIn("Wrong prior model transcript", prompt)
        self.assertIn("preferred evidence for the words being spoken", prompt)


class AiBoundarySuggestionTests(unittest.TestCase):
    def workspace(self) -> Path:
        root = Path(__file__).parent / "test-tmp"
        path = root / self._testMethodName
        shutil.rmtree(path, ignore_errors=True)
        (path / "film").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_ai_cut_is_applied_server_side_before_save(self) -> None:
        outputs_dir = self.workspace()
        shots = [{
            "shot": 1,
            "analysis_id": "old",
            "start": "00:00:00.000",
            "end": "00:00:10.000",
            "shot_title": "Combined Images",
            "visual_description": "Two images.",
            "action_camera": "An internal cut occurs.",
        }]
        suggestion = {
            "time_seconds": 4.0,
            "before_details": {
                "shot_title": "First Image",
                "visual_description": "A first image.",
                "action_camera": "The subject waits. Camera: static.",
            },
            "after_details": {
                "shot_title": "Second Image",
                "visual_description": "A second image.",
                "action_camera": "The subject leaves. Camera: static.",
            },
        }

        with patch(
            "film_study_tool.ui_server.extract_project_frame",
            side_effect=[
                {"screenshot_path": "a.jpg", "screenshot": "a.jpg", "screenshotUrl": "/a.jpg"},
                {"screenshot_path": "b.jpg", "screenshot": "b.jpg", "screenshotUrl": "/b.jpg"},
            ],
        ):
            timeline, outline, applied, pending = apply_ai_cuts_to_timeline(
                outputs_dir,
                "film",
                shots,
                {"sentences": [{"shotNumbers": [1], "title": "Moment"}]},
                [suggestion],
            )

        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[0]["end"], "00:00:04.000")
        self.assertEqual(timeline[1]["start"], "00:00:04.000")
        self.assertEqual(outline["sentences"][0]["shotNumbers"], [1, 2])
        self.assertEqual(len(applied), 1)
        self.assertEqual(pending, [])

    def test_ffmpeg_candidate_alone_never_becomes_a_cut(self) -> None:
        shots = [
            {"start": "00:00:00.000", "end": "00:00:10.000"},
        ]

        suggestions = normalize_ai_transition_suggestions(
            [],
            shots,
            [],
            [(5.0, 0.42)],
        )

        self.assertEqual(suggestions, [])

    def test_montage_language_is_ai_confirmation_for_internal_candidates(self) -> None:
        timeline = [{
            "analysis_id": "shot_montage",
            "start": "00:00:10.000",
            "end": "00:00:20.000",
        }]
        generated = [{
            "analysis_id": "shot_montage",
            "shot_title": "Daily Life Montage",
            "visual_description": "This shot contains multiple rapid cuts between distinct scenes.",
            "action_camera": "Internal cuts connect the vignettes.",
        }]

        transitions = reconcile_candidate_decisions(
            json.dumps({"candidate_decisions": []}),
            generated,
            [],
            timeline,
            [(12.0, 0.22), (16.0, 0.3)],
        )

        self.assertEqual([row["time_seconds"] for row in transitions], [12.0, 16.0])
        self.assertTrue(all("model identified" in row["reason"] for row in transitions))

    def test_every_unmatched_candidate_requires_an_ai_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "did not accept or reject"):
            reconcile_candidate_decisions(
                json.dumps({"candidate_decisions": []}),
                [{"analysis_id": "shot_a", "shot_title": "Continuous Walk"}],
                [],
                [{
                    "analysis_id": "shot_a",
                    "start": "00:00:00.000",
                    "end": "00:00:05.000",
                }],
                [(2.5, 0.31)],
            )

    def test_ai_acceptance_turns_candidate_into_transition(self) -> None:
        raw = json.dumps({
            "candidate_decisions": [{
                "time_seconds": 2.5,
                "decision": "cut",
                "transition_type": "hard_cut",
                "confidence": "high",
                "from_visual": "Dog close-up",
                "to_visual": "Street wide",
                "reason": "The framing changes discontinuously.",
            }]
        })
        transitions = reconcile_candidate_decisions(
            raw,
            [{"analysis_id": "shot_a", "shot_title": "Dog Crosses Street"}],
            [],
            [{
                "analysis_id": "shot_a",
                "start": "00:00:00.000",
                "end": "00:00:05.000",
            }],
            [(2.5, 0.31)],
        )
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["time_seconds"], 2.5)

    def test_generated_outline_repairs_gaps_and_noncontiguous_groups(self) -> None:
        outline = normalize_ai_generated_outline(
            {
                "sentences": [{
                    "beat": "Kindness",
                    "title": "One Idea",
                    "idea": "Three related actions.",
                    "shotNumbers": [1, 2, 4],
                }]
            },
            5,
        )
        groups = [row["shotNumbers"] for row in outline["sentences"]]
        self.assertEqual(groups, [[1, 2], [3], [4], [5]])

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

    def test_approximate_ai_timestamp_snaps_to_strongest_candidate_within_one_second(self) -> None:
        suggestions = normalize_ai_transition_suggestions(
            [{
                "time_seconds": 142.7,
                "transition_type": "hard_cut",
                "confidence": "high",
            }],
            [{"start": "00:02:20.200", "end": "00:02:25.560"}],
            [],
            [(141.84, 0.2825), (143.64, 0.1633)],
        )

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["time_seconds"], 141.84)
        self.assertEqual(suggestions[0]["detectorSource"], "ai+ffmpeg")


if __name__ == "__main__":
    unittest.main()
