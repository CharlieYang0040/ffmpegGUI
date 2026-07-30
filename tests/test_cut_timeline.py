import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.models import ClipRange, EditClip, EditSequence, MediaType, WorkspaceState
from app.ui.timeline_geometry import TimelineGeometry
from app.ui.widgets.cut_timeline_widget import CutTimelineWidget


def make_workspace():
    clips = (
        EditClip(
            clip_id="clip-a",
            source_path="a.mp4",
            source_range=ClipRange(10, 110),
            source_frame_count=180,
            media_type=MediaType.VIDEO,
            source_fps=30.0,
        ),
        EditClip(
            clip_id="clip-b",
            source_path="b.mp4",
            source_range=ClipRange(0, 50),
            source_frame_count=90,
            media_type=MediaType.VIDEO,
            source_fps=25.0,
        ),
    )
    return WorkspaceState(EditSequence(clips), selected_clip_id="clip-a")


class TimelineGeometryTests(unittest.TestCase):
    def test_clip_widths_follow_frame_length(self):
        geometry = TimelineGeometry(800, (("a", 100), ("b", 50)))

        first, second = geometry.clips

        self.assertGreater(first.width, second.width)
        self.assertAlmostEqual(first.width / second.width, 2.0, delta=0.1)
        self.assertEqual(geometry.hit_test(first.x + 5).clip_id, "a")
        self.assertEqual(geometry.hit_test(second.x + 5).clip_id, "b")

    def test_pixel_delta_uses_same_scale_as_rendering(self):
        geometry = TimelineGeometry(600, (("a", 120),))

        pixels = geometry.pixels_per_frame * 17

        self.assertEqual(geometry.frame_delta_for_pixels(pixels), 17)

    def test_position_at_maps_gaps_and_outside_to_nearest_clip(self):
        geometry = TimelineGeometry(500, (("a", 100), ("b", 50)), zoom=2.0)

        first, second = geometry.clips

        self.assertEqual(geometry.position_at(first.right + 1)[0].clip_id, "a")
        self.assertEqual(geometry.position_at(-100)[0].clip_id, "a")
        self.assertEqual(geometry.position_at(10_000)[0].clip_id, "b")


class CutTimelineWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_workspace_renders_ordered_clip_blocks_and_selection(self):
        widget = CutTimelineWidget()
        widget.resize(800, 118)
        widget.set_workspace_state(make_workspace())
        widget.show()
        self.app.processEvents()

        self.assertEqual([clip.clip_id for clip in widget._clips()], ["clip-a", "clip-b"])
        self.assertEqual(widget.selected_clip_id, "clip-a")
        self.assertGreater(widget._geometry.clip("clip-a").width, widget._geometry.clip("clip-b").width)

        widget.close()

    def test_clicking_second_clip_emits_selection_and_source_frame(self):
        widget = CutTimelineWidget()
        widget.resize(800, 118)
        widget.set_workspace_state(make_workspace())
        widget.show()
        self.app.processEvents()
        selected = []
        frames = []
        widget.clip_selected.connect(selected.append)
        widget.frame_changed.connect(frames.append)
        second = widget._geometry.clip("clip-b")

        from PySide6.QtCore import QPoint
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(int(second.x + second.width / 2), widget.TRACK_TOP + 20),
        )

        self.assertEqual(selected[-1], "clip-b")
        self.assertGreaterEqual(frames[-1], 1)
        self.assertLessEqual(frames[-1], 50)
        widget.close()

    def test_dragging_selected_right_handle_commits_clip_range(self):
        from PySide6.QtCore import QPoint

        widget = CutTimelineWidget()
        widget.resize(800, 118)
        widget.set_workspace_state(make_workspace())
        widget.show()
        self.app.processEvents()
        committed = []
        widget.clip_range_committed.connect(
            lambda clip_id, source_in, source_out: committed.append(
                (clip_id, source_in, source_out)
            )
        )
        first = widget._geometry.clip("clip-a")
        start = QPoint(int(first.right - 2), widget.TRACK_TOP + 25)
        end = QPoint(int(first.right - 50), widget.TRACK_TOP + 25)

        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(widget, end, delay=10)
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)

        self.assertEqual(committed[0][0], "clip-a")
        self.assertEqual(committed[0][1], 10)
        self.assertLess(committed[0][2], 110)
        widget.close()

    def test_clicking_empty_ruler_space_seeks_nearest_clip(self):
        from PySide6.QtCore import QPoint

        widget = CutTimelineWidget()
        widget.resize(800, 118)
        widget.set_workspace_state(make_workspace())
        widget.show()
        self.app.processEvents()
        selected = []
        frames = []
        widget.clip_selected.connect(selected.append)
        widget.frame_changed.connect(frames.append)

        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(widget.width() - 1, 8),
        )

        self.assertEqual(selected[-1], "clip-b")
        self.assertEqual(frames[-1], 50)
        widget.close()

    def test_geometry_handles_fifty_clips_without_offscreen_iteration(self):
        clips = tuple(
            EditClip(
                clip_id=f"clip-{index}",
                source_path=f"{index}.mp4",
                source_range=ClipRange(0, 300),
                source_frame_count=300,
                media_type=MediaType.VIDEO,
                source_fps=30.0,
            )
            for index in range(50)
        )
        widget = CutTimelineWidget()
        widget.resize(1366, 118)
        widget.zoom = 12.0
        widget.set_workspace_state(
            WorkspaceState(EditSequence(clips), selected_clip_id="clip-0")
        )

        self.assertEqual(len(widget._geometry.clips), 50)
        self.assertGreater(widget._geometry.max_offset(), 0)
        widget.close()


if __name__ == "__main__":
    unittest.main()
