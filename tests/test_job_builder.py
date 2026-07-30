import unittest

from app.core.job_builder import detect_media_type, media_items_to_legacy_tuples
from app.core.models import (
    ClipRange,
    EditClip,
    EditSequence,
    FrameTrim,
    MediaItem,
    MediaType,
    WorkspaceState,
)
from app.ui.encoding_job_adapter import collect_encoding_job


class FakeTextEdit:
    def __init__(self, value):
        self.value = value

    def text(self):
        return self.value


class FakeItemWidget:
    def __init__(self, file_path, trim_start=0, trim_end=0):
        self.file_path = file_path
        self.trim_start = trim_start
        self.trim_end = trim_end

    def get_trim_values(self):
        return self.trim_start, self.trim_end


class FakeListWidget:
    def __init__(self, item_widgets, current_row=0):
        self.item_widgets = item_widgets
        self.current_row = current_row

    def count(self):
        return len(self.item_widgets)

    def currentRow(self):
        return self.current_row

    def item(self, index):
        return index

    def itemWidget(self, item):
        return self.item_widgets[item]


class FakeControlArea:
    use_custom_framerate = True
    framerate = 24.0
    use_custom_resolution = True
    video_width = 1920
    video_height = 1080


class FakeTimeline:
    def get_in_out_points(self):
        return 11, 90


class LegacyTimeline:
    def get_in_point(self):
        return 21

    def get_out_point(self):
        return 80


class FakePreviewArea:
    current_media_path = "selected.mp4"
    current_media_fps = 24.0
    current_media_frame_count = 100
    timeline = FakeTimeline()


class LegacyPreviewArea:
    current_media_path = "selected.mp4"
    current_media_fps = 24.0
    current_media_frame_count = 100
    timeline = LegacyTimeline()


class FakeWindow:
    output_edit = FakeTextEdit("output.mp4")
    encoding_options = {"c:v": "libx264", "r": "30", "s": "1280x720"}
    control_area = FakeControlArea()
    preview_area = FakePreviewArea()

    def __init__(self):
        self.list_widget = FakeListWidget(
            [
                FakeItemWidget("selected.mp4", trim_start=2, trim_end=3),
                FakeItemWidget("plate.%04d.png", trim_start=4, trim_end=6),
            ],
            current_row=0,
        )


class JobBuilderTests(unittest.TestCase):
    def test_detect_media_type(self):
        self.assertEqual(detect_media_type("shot.%04d.png"), MediaType.IMAGE_SEQUENCE)
        self.assertEqual(detect_media_type("clip.webp"), MediaType.WEBP)
        self.assertEqual(detect_media_type("clip.mp4"), MediaType.VIDEO)
        self.assertEqual(detect_media_type("still.png"), MediaType.IMAGE)
        self.assertEqual(detect_media_type(""), MediaType.UNKNOWN)

    def test_media_items_to_legacy_tuples_preserves_head_tail_trim(self):
        items = [
            MediaItem(
                source_path="input.mp4",
                media_type=MediaType.VIDEO,
                trim=FrameTrim(3, 8),
            )
        ]

        self.assertEqual(media_items_to_legacy_tuples(items), [("input.mp4", 3, 8)])

    def test_collect_encoding_job_uses_timeline_for_selected_item_and_options_copy(self):
        window = FakeWindow()

        job = collect_encoding_job(window)

        self.assertEqual(job.output_file, "output.mp4")
        self.assertEqual(len(job.media_items), 2)
        self.assertEqual(job.media_items[0].trim, FrameTrim(10, 10))
        self.assertEqual(job.media_items[0].fps, 24.0)
        self.assertEqual(job.media_items[0].frame_count, 100)
        self.assertEqual(job.media_items[1].trim, FrameTrim(4, 6))
        self.assertEqual(job.media_items[1].media_type, MediaType.IMAGE_SEQUENCE)
        self.assertEqual(job.options.ffmpeg_options["r"], "24.0")
        self.assertEqual(job.options.ffmpeg_options["s"], "1920x1080")
        self.assertEqual(window.encoding_options["r"], "30")
        self.assertEqual(window.encoding_options["s"], "1280x720")

    def test_collect_encoding_job_falls_back_to_legacy_timeline_methods(self):
        window = FakeWindow()
        window.preview_area = LegacyPreviewArea()

        job = collect_encoding_job(window)

        self.assertEqual(job.media_items[0].trim, FrameTrim(20, 20))
        self.assertEqual(job.media_items[0].fps, 24.0)
        self.assertEqual(job.media_items[0].frame_count, 100)

    def test_collect_encoding_job_prefers_workspace_clip_ranges(self):
        window = FakeWindow()
        window.workspace_state = WorkspaceState(
            edit_sequence=EditSequence(
                (
                    EditClip(
                        clip_id="clip-a",
                        source_path="selected.mp4",
                        source_range=ClipRange(15, 90),
                        source_frame_count=100,
                        media_type=MediaType.VIDEO,
                        source_fps=24.0,
                    ),
                )
            ),
            selected_clip_id="clip-a",
            output_file="output.mp4",
        )

        job = collect_encoding_job(window)

        self.assertEqual(len(job.media_items), 1)
        self.assertEqual(job.media_items[0].source_range, ClipRange(15, 90))
        self.assertEqual(
            media_items_to_legacy_tuples(job.media_items),
            [("selected.mp4", 15, 10)],
        )


if __name__ == "__main__":
    unittest.main()
