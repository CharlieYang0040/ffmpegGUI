import unittest

from app.core.models import ClipRange
from app.ui.workspace_state_adapter import (
    collect_workspace_state,
    split_clip_item_state,
)


class FakeOutput:
    def text(self):
        return "result.mp4"


class FakeItemWidget:
    def __init__(self, clip_id, path, frame_count, trim):
        self.clip_id = clip_id
        self.file_path = path
        self.total_frames = frame_count
        self.fps = 24.0
        self.trim = trim

    def get_trim_values(self):
        return self.trim


class FakeList:
    def __init__(self, widgets, current_row=0):
        self.widgets = widgets
        self.current_row = current_row

    def __bool__(self):
        return True

    def count(self):
        return len(self.widgets)

    def currentRow(self):
        return self.current_row

    def item(self, index):
        return index

    def itemWidget(self, item):
        return self.widgets[item]


class WorkspaceStateAdapterTests(unittest.TestCase):
    def test_collects_every_ready_item_through_same_clip_contract(self):
        window = type("Window", (), {})()
        window.output_edit = FakeOutput()
        window.current_preset_id = "h264_review"
        window.list_widget = FakeList(
            [
                FakeItemWidget("clip-a", "a.mp4", 100, (10, 20)),
                FakeItemWidget("clip-b", "b.mp4", 80, (5, 7)),
            ],
            current_row=1,
        )

        state = collect_workspace_state(window)

        self.assertEqual(state.selected_clip_id, "clip-b")
        self.assertEqual(state.edit_sequence.clips[0].source_range, ClipRange(10, 80))
        self.assertEqual(state.edit_sequence.clips[1].source_range, ClipRange(5, 73))
        self.assertEqual(state.output_file, "result.mp4")

    def test_returns_none_until_all_item_metadata_is_ready(self):
        window = type("Window", (), {})()
        window.output_edit = FakeOutput()
        window.list_widget = FakeList(
            [FakeItemWidget("clip-a", "a.mp4", 0, (0, 0))]
        )

        self.assertIsNone(collect_workspace_state(window))

    def test_split_item_state_preserves_range_length_without_overlap(self):
        original = {
            "clip_id": "original",
            "file_path": "a.mp4",
            "trim_start": 10,
            "trim_end": 20,
        }

        left, right = split_clip_item_state(
            original,
            source_frame_count=100,
            split_boundary=40,
            left_clip_id="left",
            right_clip_id="right",
        )

        self.assertEqual((left["trim_start"], left["trim_end"]), (10, 60))
        self.assertEqual((right["trim_start"], right["trim_end"]), (40, 20))
        left_length = 100 - left["trim_start"] - left["trim_end"]
        right_length = 100 - right["trim_start"] - right["trim_end"]
        self.assertEqual(left_length + right_length, 70)


if __name__ == "__main__":
    unittest.main()
