import os
from pathlib import Path
import queue
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame
    from PySide6.QtWidgets import QApplication, QLabel
    from app.core.image_sequence_loader import ImageSequenceLoaderThread
    from app.core.media_timing import FrameTimeMap
    from app.ui.widgets.cut_timeline_widget import CutTimelineWidget
    from app.core.models import (
        ClipRange,
        EditClip,
        EditSequence,
        MediaType,
        WorkspaceState,
    )
    from app.ui.components.preview_area import (
        PreviewAreaComponent,
        frame_number_to_zero_based_index,
        reconcile_sequence_frame,
    )
    from app.ui.components.timeline import TimelineComponent
    from app.ui.main_window import FFmpegGui, normalize_workspace_splitter_sizes
    from app.ui.commands.commands import (
        ClearListCommand,
        DuplicateClipCommand,
        RemoveItemsCommand,
        ReorderItemsCommand,
        ResetClipRangesCommand,
        SplitClipCommand,
        UpdateClipRangeCommand,
    )
    from app.ui.widgets.drag_drop_list_widget import DragDropListWidget
    from app.ui.widgets.list_widget_item import (
        MediaMetadataLoader,
        ThumbnailLoader,
        load_media_metadata,
    )
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

    def test_video_sink_frame_is_painted_into_preview_widget(self):
        component = PreviewAreaComponent.__new__(PreviewAreaComponent)
        component.is_video_mode = True
        component.media_player = None
        component.video_widget = QLabel()
        component.video_widget.resize(320, 180)
        component._last_video_pixmap = None
        image = QImage(160, 90, QImage.Format_RGB32)
        image.fill(Qt.red)

        component.on_video_frame_changed(QVideoFrame(image))

        self.assertIsNotNone(component._last_video_pixmap)
        self.assertIsNotNone(component.video_widget.pixmap())
        self.assertFalse(component.video_widget.pixmap().isNull())

    def test_playback_driven_frame_update_refreshes_timecode(self):
        class TimelineWidgetStub:
            fps = 30.0
            current_frame = 1

            def set_current_frame(self, frame, emit_signal):
                self.current_frame = frame

        component = TimelineComponent.__new__(TimelineComponent)
        component.timeline_widget = TimelineWidgetStub()
        component.current_timecode_label = QLabel("00:00:00:00")

        component.set_current_frame(31, emit_signal=False)

        self.assertEqual(component.current_timecode_label.text(), "00:00:01:00")

    def test_vfr_frame_time_map_drives_preview_seek(self):
        component = PreviewAreaComponent.__new__(PreviewAreaComponent)
        component.current_frame_time_map = FrameTimeMap.from_timestamps(
            [0, 66.667, 133.333, 1200, 2600]
        )
        component.current_media_fps = 30.0
        component.current_media_frame_count = 5
        component.current_media_duration_ms = 3000

        self.assertEqual(component._frame_to_ms(4), 1200)
        self.assertEqual(component._frame_to_ms(5), 2600)
        self.assertEqual(component._ms_to_frame(1199), 3)
        self.assertEqual(component._ms_to_frame(1200), 4)

    def test_seek_after_end_of_media_refreshes_stale_video_frame(self):
        events = []

        class Source:
            def toLocalFile(self):
                return "C:/media/vfr.mp4"

        class Player:
            def mediaStatus(self):
                return QMediaPlayer.EndOfMedia

            def playbackState(self):
                return QMediaPlayer.StoppedState

            def source(self):
                return Source()

            def setPosition(self, value):
                events.append(("position", value))

            def play(self):
                events.append("play")

            def pause(self):
                events.append("pause")

        component = PreviewAreaComponent.__new__(PreviewAreaComponent)
        component.media_player = Player()
        component.current_media_path = "C:/media/vfr.mp4"
        component._video_seek_generation = 0

        with patch(
            "app.ui.components.preview_area.QTimer.singleShot",
            side_effect=lambda _delay, callback: callback(),
        ):
            component._set_video_position(1200, refresh_stopped_frame=True)

        self.assertEqual(
            events,
            [("position", 1200), "play", "pause", ("position", 1200)],
        )
        component.media_player = None

    def test_duration_change_does_not_overwrite_known_vfr_frame_count(self):
        class Source:
            def toLocalFile(self):
                return "C:/media/vfr.mp4"

        component = PreviewAreaComponent.__new__(PreviewAreaComponent)
        component.is_video_mode = True
        component.current_media_path = "C:/media/vfr.mp4"
        component.current_media_duration_ms = 0
        component.current_media_frame_count = 68
        component.current_media_fps = 30.0
        component.current_frame_time_map = FrameTimeMap.from_fps(68, 30.0)
        component.timeline = SimpleNamespace(
            set_video_info=lambda *args, **kwargs: self.fail("frame count replaced")
        )
        component.media_player = SimpleNamespace(source=Source)

        component.on_duration_changed(3000)

        self.assertEqual(component.current_media_frame_count, 68)
        self.assertEqual(component.current_media_duration_ms, 3000)
        component.media_player = None

    def test_workspace_splitter_caps_wide_output_panel(self):
        self.assertEqual(
            normalize_workspace_splitter_sizes([440, 916, 550]),
            [440, 916, 380],
        )

    def test_preview_resize_does_not_treat_loading_video_as_sequence(self):
        component = PreviewAreaComponent.__new__(PreviewAreaComponent)
        component.media_info_loading = True
        component.is_video_mode = False
        component.image_preview_label = QLabel("미디어 정보 로딩 중...")
        component.image_preview_label.show()
        component.current_media_path = "C:/media/video.mp4"
        component.expected_sequence_frame_index = 0
        displayed = []
        component._display_sequence_frame = displayed.append

        component.update_preview_label()

        self.assertEqual(displayed, [])

    def test_preview_marker_reset_does_not_change_edit_clip_range(self):
        clip = EditClip(
            clip_id="clip-a",
            source_path="a.mp4",
            source_range=ClipRange(10, 110),
            source_frame_count=180,
            media_type=MediaType.VIDEO,
            source_fps=30.0,
        )
        timeline = CutTimelineWidget()
        timeline.set_workspace_state(
            WorkspaceState(EditSequence((clip,)), selected_clip_id="clip-a")
        )
        committed = []
        timeline.clip_range_committed.connect(
            lambda *values: committed.append(values)
        )
        component = TimelineComponent.__new__(TimelineComponent)
        component.timeline_widget = timeline

        component.reset_in_out_points()

        self.assertEqual(committed, [])
        self.assertEqual(
            timeline.workspace_state.selected_clip.source_range,
            ClipRange(10, 110),
        )
        self.assertEqual((timeline.in_point, timeline.out_point), (1, 180))
        timeline.close()

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

    def test_timeline_range_command_preserves_existing_media_widget(self):
        refreshes = []
        list_widget = DragDropListWidget()
        list_widget.main_window = SimpleNamespace(
            refresh_job_inspector=lambda: refreshes.append("refresh")
        )
        list_widget.add_items(["C:/media/a.mp4"])
        item = list_widget.item(0)
        item_widget = list_widget.itemWidget(item)
        item_widget.total_frames = 120
        item_widget.source_range = ClipRange(0, 120)
        original_loader = item_widget.loader
        original_thumbnail_loader = item_widget.thumbnail_loader
        refreshes.clear()

        command = UpdateClipRangeCommand(
            list_widget,
            item_widget.clip_id,
            ClipRange(0, 120),
            ClipRange(18, 94),
        )

        self.assertTrue(command.execute())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), item_widget)
        self.assertIs(item_widget.loader, original_loader)
        self.assertIs(item_widget.thumbnail_loader, original_thumbnail_loader)
        self.assertEqual(item_widget.get_clip_range(), ClipRange(18, 94))
        self.assertTrue(command.undo())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), item_widget)
        self.assertEqual(item_widget.get_clip_range(), ClipRange(0, 120))
        self.assertGreaterEqual(len(refreshes), 2)

    def test_split_and_duplicate_reuse_loaded_media_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "clip.mp4"
            media_path.write_bytes(b"placeholder")
            with patch.object(MediaMetadataLoader, "start"), patch.object(
                ThumbnailLoader,
                "start",
            ):
                list_widget = DragDropListWidget()
                list_widget.add_items([str(media_path)])
                original_item = list_widget.item(0)
                original_widget = list_widget.itemWidget(original_item)
                original_widget.total_frames = 120
                original_widget.fps = 30.0
                original_widget.source_range = ClipRange(0, 120)

                duplicate = DuplicateClipCommand(list_widget, 0, "duplicate")
                self.assertTrue(duplicate.execute())
                duplicate_widget = list_widget.itemWidget(list_widget.item(1))
                self.assertEqual(duplicate_widget.total_frames, 120)
                self.assertIsNone(duplicate_widget.loader)
                self.assertIsNone(duplicate_widget.thumbnail_loader)
                self.assertTrue(duplicate.undo())
                self.assertIs(list_widget.itemWidget(list_widget.item(0)), original_widget)
                self.assertTrue(duplicate.execute())
                self.assertIs(list_widget.itemWidget(list_widget.item(1)), duplicate_widget)
                self.assertTrue(duplicate.undo())

                split = SplitClipCommand(
                    list_widget,
                    0,
                    45,
                    "left",
                    "right",
                )
                self.assertTrue(split.execute())
                left_widget = list_widget.itemWidget(list_widget.item(0))
                right_widget = list_widget.itemWidget(list_widget.item(1))
                self.assertIs(left_widget, original_widget)
                self.assertEqual(left_widget.get_clip_range(), ClipRange(0, 45))
                self.assertEqual(right_widget.get_clip_range(), ClipRange(45, 120))
                self.assertIsNone(right_widget.loader)
                self.assertIsNone(right_widget.thumbnail_loader)
                self.assertTrue(split.undo())
                self.assertIs(list_widget.itemWidget(list_widget.item(0)), original_widget)
                self.assertEqual(original_widget.get_clip_range(), ClipRange(0, 120))
                self.assertTrue(split.execute())
                self.assertIs(list_widget.itemWidget(list_widget.item(1)), right_widget)
                self.assertTrue(split.undo())

    def test_reorder_preserves_widgets_and_is_undoable(self):
        list_widget = DragDropListWidget()
        list_widget.add_items(["C:/media/a.mp4", "C:/media/a.mp4"])
        widgets = [
            list_widget.itemWidget(list_widget.item(index))
            for index in range(2)
        ]
        old_order = list_widget.get_all_item_states()
        new_order = list(reversed(old_order))
        command = ReorderItemsCommand(list_widget, old_order, new_order)

        self.assertTrue(command.execute())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[1])
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[1])
        self.assertIs(list_widget.itemWidget(list_widget.item(1)), widgets[0])
        self.assertIs(list_widget.itemWidget(list_widget.item(1)), widgets[0])
        self.assertTrue(command.undo())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[0])
        self.assertIs(list_widget.itemWidget(list_widget.item(1)), widgets[1])
        self.assertTrue(command.execute())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[1])

    def test_remove_and_clear_undo_restore_same_widgets(self):
        list_widget = DragDropListWidget()
        list_widget.add_items(["C:/media/a.mp4", "C:/media/b.mp4"])
        widgets = [
            list_widget.itemWidget(list_widget.item(index))
            for index in range(2)
        ]
        remove = RemoveItemsCommand(list_widget, [list_widget.item(0)])

        self.assertTrue(remove.execute())
        self.assertEqual(list_widget.count(), 1)
        self.assertTrue(remove.undo())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[0])
        self.assertTrue(remove.execute())
        self.assertTrue(remove.undo())

        clear = ClearListCommand(list_widget)
        self.assertTrue(clear.execute())
        self.assertEqual(list_widget.count(), 0)
        self.assertTrue(clear.undo())
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[0])
        self.assertIs(list_widget.itemWidget(list_widget.item(1)), widgets[1])
        self.assertTrue(clear.execute())
        self.assertTrue(clear.undo())

    def test_reset_ranges_preserves_widgets_and_undoes_atomically(self):
        list_widget = DragDropListWidget()
        list_widget.add_items(["C:/media/a.mp4", "C:/media/b.mp4"])
        widgets = [
            list_widget.itemWidget(list_widget.item(index))
            for index in range(2)
        ]
        for widget, source_range in zip(
            widgets,
            (ClipRange(10, 90), ClipRange(5, 70)),
        ):
            widget.total_frames = 120
            widget.source_range = source_range
        command = ResetClipRangesCommand(list_widget)

        self.assertTrue(command.execute())
        self.assertEqual(widgets[0].get_clip_range(), ClipRange(0, 120))
        self.assertEqual(widgets[1].get_clip_range(), ClipRange(0, 120))
        self.assertTrue(command.undo())
        self.assertEqual(widgets[0].get_clip_range(), ClipRange(10, 90))
        self.assertEqual(widgets[1].get_clip_range(), ClipRange(5, 70))
        self.assertIs(list_widget.itemWidget(list_widget.item(0)), widgets[0])
        self.assertTrue(command.execute())
        self.assertEqual(widgets[0].get_clip_range(), ClipRange(0, 120))

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
        )

        FFmpegGui.apply_selected_item_trim_to_timeline(window)

        self.assertEqual((timeline.in_point, timeline.out_point), (81, 100))

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
