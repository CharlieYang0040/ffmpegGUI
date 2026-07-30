import os
from pathlib import Path
import queue
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from app.core.image_sequence_loader import ImageSequenceLoaderThread
    from app.ui.widgets.cut_timeline_widget import CutTimelineWidget
    from app.core.models import ClipRange
    from app.ui.components.preview_area import (
        frame_number_to_zero_based_index,
        reconcile_sequence_frame,
    )
    from app.ui.main_window import FFmpegGui
    from app.ui.widgets.drag_drop_list_widget import DragDropListWidget
    from app.ui.widgets.list_widget_item import ThumbnailLoader, load_media_metadata
except ModuleNotFoundError:  # pragma: no cover - exercised only without Qt installed
    QApplication = None
    Qt = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class UIRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_update_items_preserves_trim_values_for_existing_paths(self):
        widget = DragDropListWidget()
        widget.add_items(["C:/media/a.mp4", "C:/media/b.mp4"])
        widget.itemWidget(widget.item(0)).set_trim_values(12, 5)

        widget.update_items(["C:/media/b.mp4", "C:/media/a.mp4"])

        restored = None
        for row in range(widget.count()):
            item = widget.item(row)
            if item.data(Qt.UserRole) == "C:/media/a.mp4":
                restored = widget.itemWidget(item)
                break
        self.assertIsNotNone(restored)
        self.assertEqual(restored.get_trim_values(), (12, 5))

    def test_thumbnail_loader_reads_still_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "thumbnail.png"
            image = QImage(80, 50, QImage.Format_RGB32)
            image.fill(Qt.red)
            self.assertTrue(image.save(str(image_path)))
            loaded = []
            loader = ThumbnailLoader(str(image_path))
            loader.loaded.connect(loaded.append)

            loader.run()

            self.assertEqual(len(loaded), 1)
            self.assertFalse(loaded[0].isNull())

    def test_editing_selected_item_clip_range_updates_timeline_before_job_refresh(self):
        events = []
        widget = DragDropListWidget()
        widget.main_window = SimpleNamespace(
            apply_selected_item_trim_to_timeline=lambda: events.append("timeline"),
            refresh_job_inspector=lambda: events.append("inspector"),
        )
        widget.add_items(["C:/media/a.mp4"])
        item = widget.item(0)
        widget.setCurrentItem(item)
        item_widget = widget.itemWidget(item)
        item_widget.total_frames = 120
        item_widget.source_range = ClipRange(0, 120)
        events.clear()

        item_widget.set_clip_range(ClipRange(15, 90))

        self.assertEqual(events[:2], ["timeline", "inspector"])

    def test_timeline_trim_apply_allows_in_point_after_previous_out(self):
        timeline = CutTimelineWidget()
        timeline.set_video_info(100, 24.0, 100 / 24.0)
        timeline.set_out_point(50)

        class FakeItemWidget:
            def get_trim_values(self):
                return 80, 0

        class FakeListWidget:
            def currentItem(self):
                return object()

            def itemWidget(self, _item):
                return FakeItemWidget()

        window = SimpleNamespace(
            preview_area=SimpleNamespace(timeline=SimpleNamespace(timeline_widget=timeline)),
            list_widget=FakeListWidget(),
            _syncing_timeline_trim=False,
        )

        FFmpegGui.apply_selected_item_trim_to_timeline(window)

        self.assertEqual((timeline.in_point, timeline.out_point), (81, 100))
        self.assertFalse(window._syncing_timeline_trim)

    def test_timeline_reset_does_not_overwrite_trim_while_media_is_loading(self):
        calls = []
        timeline = SimpleNamespace(frame_count=120, in_point=1, out_point=120)
        item = SimpleNamespace(isSelected=lambda: True)
        item_widget = SimpleNamespace(
            set_trim_values=lambda start, end: calls.append((start, end))
        )
        list_widget = SimpleNamespace(
            currentItem=lambda: item,
            itemWidget=lambda _item: item_widget,
        )
        window = SimpleNamespace(
            preview_area=SimpleNamespace(
                timeline=SimpleNamespace(timeline_widget=timeline)
            ),
            list_widget=list_widget,
            _syncing_timeline_trim=False,
            _loading_selected_media_trim=True,
            refresh_job_inspector=lambda: calls.append("refreshed"),
        )

        FFmpegGui.sync_current_item_trim_from_timeline(window)

        self.assertEqual(calls, [])

    def test_loaded_media_applies_saved_trim_after_reset(self):
        calls = []
        window = SimpleNamespace(
            _loading_selected_media_trim=True,
            apply_selected_item_trim_to_timeline=lambda: calls.append("applied"),
        )

        FFmpegGui.apply_loaded_media_trim_to_timeline(window)

        self.assertFalse(window._loading_selected_media_trim)
        self.assertEqual(calls, ["applied"])

    def test_preset_extension_updates_known_output_container(self):
        class FakeLineEdit:
            def __init__(self, value):
                self.value = value

            def text(self):
                return self.value

            def setText(self, value):
                self.value = value

        window = SimpleNamespace(
            output_edit=FakeLineEdit("C:/renders/review.mp4"),
            auto_naming_checkbox=SimpleNamespace(isChecked=lambda: False),
        )

        FFmpegGui.update_output_extension_for_preset(window, ".webm")

        self.assertEqual(window.output_edit.text(), "C:/renders/review.webm")

    def test_sequence_metadata_uses_all_matching_frames(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for frame in range(1, 4):
                Path(temp_dir, f"frame.{frame:04d}.png").write_bytes(b"placeholder")
            pattern = os.path.join(temp_dir, "frame.%04d.png")

            with patch(
                "app.core.ffmpeg_core.get_media_properties",
                return_value={"nb_frames": 1, "r": 12.0, "duration": 0.0},
            ):
                metadata = load_media_metadata(pattern)

        self.assertEqual(metadata["nb_frames"], 3)
        self.assertEqual(metadata["duration"], 0.25)

    def test_sequence_filename_frame_number_converts_to_zero_based_index(self):
        self.assertEqual(frame_number_to_zero_based_index(0), 0)
        self.assertEqual(frame_number_to_zero_based_index(1), 0)
        self.assertEqual(frame_number_to_zero_based_index(1001), 1000)

    def test_sequence_playback_resynchronizes_after_missing_frame(self):
        self.assertEqual(reconcile_sequence_frame(5, 5), (True, 5, 0))
        self.assertEqual(reconcile_sequence_frame(5, 7), (True, 7, 2))
        self.assertEqual(reconcile_sequence_frame(7, 5), (False, 7, 0))

    def test_sequence_loader_skips_corrupt_frame_and_preserves_indices(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for frame in (1, 3):
                image = QImage(2, 2, QImage.Format_RGB32)
                image.fill(Qt.red)
                self.assertTrue(
                    image.save(os.path.join(temp_dir, f"frame.{frame:04d}.png"))
                )
            Path(temp_dir, "frame.0002.png").write_bytes(b"not-a-png")
            frame_buffer = queue.Queue(maxsize=10)
            loader = ImageSequenceLoaderThread(
                os.path.join(temp_dir, "frame.%04d.png"),
                frame_buffer,
                start_frame=1,
                buffer_size=10,
            )

            loader.run()

            loaded_indices = []
            while not frame_buffer.empty():
                loaded_indices.append(frame_buffer.get_nowait()[0])

        self.assertEqual(loaded_indices, [0, 2])

    def test_cancelled_encoding_stops_and_closes_progress_dialog(self):
        events = []
        dialog = SimpleNamespace(
            isVisible=lambda: True,
            stop_timer=lambda: events.append("timer_stopped"),
            status_label=SimpleNamespace(
                setText=lambda value: events.append(("status", value))
            ),
            update_task=lambda value: events.append(("dialog_task", value)),
            reject=lambda: events.append("dialog_closed"),
        )
        window = SimpleNamespace(
            _encoding_failed=False,
            encoding_thread=None,
            cancel_token=object(),
            progress_dialog=dialog,
            set_encoding_active=lambda enabled: events.append(("active", enabled)),
            update_task=lambda value: events.append(("task", value)),
            statusBar=lambda: SimpleNamespace(
                showMessage=lambda value: events.append(("status_bar", value))
            ),
        )

        with patch(
            "app.ui.main_window.QTimer.singleShot",
            side_effect=lambda _delay, callback: callback(),
        ):
            FFmpegGui.encoding_failed(window, "작업이 취소되었습니다.")

        self.assertIn("timer_stopped", events)
        self.assertIn("dialog_closed", events)
        self.assertIn(("status", "취소됨"), events)
        self.assertIsNone(window.cancel_token)


if __name__ == "__main__":
    unittest.main()
