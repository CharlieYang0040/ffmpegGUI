import os
from pathlib import Path
import tempfile
import unittest

from app.core.encoding_presets import apply_preset_options, get_preset, get_presets
from app.core.ffmpeg_manager import FFmpegManager
from app.core.ffmpeg_process import build_ffmpeg_option_args, decode_process_output
from app.core.models import (
    CancellationToken,
    EncodingJob,
    EncodingOptions,
    EncodingProgressStage,
    EncodingProgressState,
    FFmpegEncoderCapabilities,
    FrameTrim,
    MediaItem,
    MediaType,
    PreflightSeverity,
)
from app.core.output_naming import build_auto_output_path
from app.core.preflight import build_preflight


class FakeSettings:
    def __init__(self, ffmpeg_path="", capabilities=None):
        self.ffmpeg_path = ffmpeg_path
        self.capabilities = capabilities

    def get_ffmpeg_path(self):
        return self.ffmpeg_path

    def get_encoder_capabilities(self):
        return self.capabilities or FFmpegEncoderCapabilities(
            encoders=set(),
            nvenc_available=False,
            checked_at=1.0,
            message="fake capabilities",
        )


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if not self.terminated else 1

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class UXWorkflowTests(unittest.TestCase):
    def test_preset_options_and_custom_preserve_current_options(self):
        h264 = apply_preset_options("h264_review", {"c:v": "libx265"})
        custom = apply_preset_options("custom", {"c:v": "prores_ks", "profile:v": "3"})

        self.assertEqual(h264["c:v"], "libx264")
        self.assertEqual(h264["crf"], "18")
        self.assertEqual(custom, {"c:v": "prores_ks", "profile:v": "3"})

    def test_preflight_reports_missing_input_and_output_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = os.path.join(temp_dir, "review.mp4")
            with open(output_file, "w", encoding="utf-8") as handle:
                handle.write("existing")

            job = EncodingJob(
                media_items=[
                    MediaItem("missing.mp4", MediaType.VIDEO, FrameTrim(2, 3)),
                ],
                output_file=output_file,
                options=EncodingOptions({"c:v": "libx264"}),
            )

            summary = build_preflight(job, FakeSettings("ffmpeg.exe"), get_preset("h264_review"))

        self.assertFalse(summary.can_start)
        self.assertTrue(summary.output_exists)
        self.assertEqual(summary.total_head_trim, 2)
        self.assertEqual(summary.total_tail_trim, 3)
        severities = [issue.severity for issue in summary.issues]
        self.assertIn(PreflightSeverity.ERROR, severities)
        self.assertIn(PreflightSeverity.WARNING, severities)

    def test_preflight_warns_when_output_extension_does_not_match_preset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "input.mp4")
            output = os.path.join(temp_dir, "output.mp4")
            Path(source).write_text("fake", encoding="utf-8")
            job = EncodingJob(
                media_items=[MediaItem(source, MediaType.VIDEO)],
                output_file=output,
                options=EncodingOptions({"c:v": "libvpx-vp9"}),
            )

            summary = build_preflight(job, FakeSettings("ffmpeg.exe"), get_preset("vp9_web"))

        self.assertTrue(summary.can_start)
        self.assertIn("output_extension_mismatch", [issue.code for issue in summary.issues])

    def test_auto_output_path_rules(self):
        result = build_auto_output_path(
            os.path.join("shots", "seq010", "plate.%04d.png"),
            os.path.join("renders", "old.mov"),
            auto_output_path=False,
            auto_naming=False,
            auto_foldernaming=False,
            extension=".webm",
        )
        folder_named = build_auto_output_path(
            os.path.join("shots", "seq010", "plate.%04d.png"),
            "",
            auto_foldernaming=True,
        )

        self.assertTrue(result.endswith("renders/old.webm") or result.endswith("renders\\old.webm"))
        self.assertTrue(folder_named.endswith("seq010.mp4"))

    def test_progress_state_clamps_progress(self):
        state = EncodingProgressState(EncodingProgressStage.PROCESSING, progress=250)
        self.assertEqual(state.progress, 100)

    def test_cancellation_token_terminates_registered_process(self):
        token = CancellationToken()
        process = FakeProcess()

        token.register_process(process)
        token.cancel()

        self.assertTrue(token.is_cancelled)
        self.assertTrue(process.terminated)
        with self.assertRaises(RuntimeError):
            token.throw_if_cancelled()

    def test_file_list_area_has_no_broken_question_mark_labels(self):
        source = Path("app/ui/components/file_list_area.py").read_text(encoding="utf-8")
        self.assertNotIn('QLabel("??', source)
        self.assertNotIn('QCheckBox("??', source)
        self.assertNotIn('QPushButton("??', source)
        self.assertIn('QLabel("소스 큐")', source)
        self.assertIn('QCheckBox("출력 경로 자동")', source)

    def test_timeline_component_get_in_out_points(self):
        try:
            from app.ui.components.timeline import TimelineComponent
        except ModuleNotFoundError as exc:
            self.skipTest(str(exc))

        component = object.__new__(TimelineComponent)
        component.timeline_widget = type("TimelineWidgetStub", (), {"in_point": 12, "out_point": 90})()
        self.assertEqual(TimelineComponent.get_in_out_points(component), (12, 90))

    def test_decode_process_output_replaces_invalid_utf8(self):
        decoded = decode_process_output(b"valid\n\xb0invalid")
        self.assertIn("valid", decoded)
        self.assertIn("\ufffd", decoded)

    def test_nvenc_preset_has_required_encoder_and_no_crf(self):
        preset = get_preset("gpu_h264_review")
        options = apply_preset_options(preset.preset_id, {"crf": "18", "c:v": "libx264"})

        self.assertEqual(preset.requires_encoder, "h264_nvenc")
        self.assertEqual(preset.hardware, "nvenc")
        self.assertEqual(options["c:v"], "h264_nvenc")
        self.assertEqual(options["cq"], "23")
        self.assertNotIn("crf", options)

    def test_all_gpu_presets_declare_required_encoder(self):
        gpu_presets = [preset for preset in get_presets() if preset.hardware == "nvenc"]
        self.assertGreaterEqual(len(gpu_presets), 5)
        for preset in gpu_presets:
            self.assertIn(preset.requires_encoder, {"h264_nvenc", "hevc_nvenc"})

    def test_ffmpeg_encoder_list_parses_nvenc(self):
        sample = """
Encoders:
 V..... libx264              libx264 H.264
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder
 A..... aac                  AAC encoder
"""
        encoders = FFmpegManager.parse_encoder_names(sample)
        self.assertIn("h264_nvenc", encoders)
        self.assertIn("hevc_nvenc", encoders)
        self.assertIn("aac", encoders)

    def test_preflight_blocks_gpu_when_nvenc_missing_but_allows_cpu(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "input.mp4")
            output = os.path.join(temp_dir, "output.mp4")
            Path(source).write_text("fake", encoding="utf-8")
            job = EncodingJob(
                media_items=[MediaItem(source, MediaType.VIDEO)],
                output_file=output,
                options=EncodingOptions({"c:v": "h264_nvenc"}),
            )
            missing_caps = FFmpegEncoderCapabilities(
                encoders={"libx264"},
                nvenc_available=False,
                checked_at=1.0,
                message="no nvenc",
            )

            gpu_summary = build_preflight(
                job,
                FakeSettings("ffmpeg.exe", missing_caps),
                get_preset("gpu_h264_review"),
            )
            cpu_summary = build_preflight(
                EncodingJob(
                    media_items=[MediaItem(source, MediaType.VIDEO)],
                    output_file=output,
                    options=EncodingOptions({"c:v": "libx264"}),
                ),
                FakeSettings("ffmpeg.exe", missing_caps),
                get_preset("h264_review"),
            )

        self.assertFalse(gpu_summary.can_start)
        self.assertIn("missing_required_encoder", [issue.code for issue in gpu_summary.issues])
        self.assertTrue(cpu_summary.can_start)

    def test_preflight_allows_gpu_when_required_encoder_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "input.mp4")
            output = os.path.join(temp_dir, "output.mp4")
            Path(source).write_text("fake", encoding="utf-8")
            caps = FFmpegEncoderCapabilities(
                encoders={"h264_nvenc", "hevc_nvenc"},
                nvenc_available=True,
                checked_at=1.0,
                message="ok",
            )
            summary = build_preflight(
                EncodingJob(
                    media_items=[MediaItem(source, MediaType.VIDEO)],
                    output_file=output,
                    options=EncodingOptions({"c:v": "h264_nvenc"}),
                ),
                FakeSettings("ffmpeg.exe", caps),
                get_preset("gpu_h264_review"),
            )

        self.assertTrue(summary.can_start)
        self.assertIn("required_encoder_available", [issue.code for issue in summary.issues])

    def test_image_sequence_options_do_not_override_nvenc_with_libx264(self):
        args = build_ffmpeg_option_args(
            {"c:v": "h264_nvenc", "cq": "23", "s": "1920x1080"},
            defaults={"c:v": "libx264", "pix_fmt": "yuv420p"},
            skip_keys=("s",),
        )

        self.assertIn("h264_nvenc", args)
        self.assertIn("-cq", args)
        self.assertNotIn("libx264", args)
        self.assertNotIn("1920x1080", args)


if __name__ == "__main__":
    unittest.main()