import unittest

from app.core.job_builder import (
    clip_range_to_trim,
    edit_sequence_to_media_items,
    timeline_range_to_clip_range,
    timeline_range_to_trim,
    trim_to_clip_range,
    validate_encoding_job,
)
from app.core.models import (
    ClipRange,
    EditClip,
    EditSequence,
    EncodingJob,
    EncodingOptions,
    FrameTrim,
    MediaItem,
    MediaType,
    TimelineRange,
    WorkspaceState,
)


class CoreModelTests(unittest.TestCase):
    def make_clip(self, clip_id="clip-a", source_range=None):
        return EditClip(
            clip_id=clip_id,
            source_path="input.mp4",
            source_range=source_range or ClipRange(10, 90),
            source_frame_count=100,
            media_type=MediaType.VIDEO,
            source_fps=24.0,
        )

    def test_frame_trim_normalizes_negative_and_float_values(self):
        trim = FrameTrim(-3, 4.8)

        self.assertEqual(trim.head_frames, 0)
        self.assertEqual(trim.tail_frames, 4)

    def test_timeline_range_converts_to_head_tail_trim(self):
        trim = timeline_range_to_trim(TimelineRange(in_frame=11, out_frame=90, frame_count=100))

        self.assertEqual(trim, FrameTrim(head_frames=10, tail_frames=10))

    def test_ui_timeline_range_converts_to_half_open_clip_range(self):
        clip_range = timeline_range_to_clip_range(
            TimelineRange(in_frame=16, out_frame=90, frame_count=100)
        )

        self.assertEqual(clip_range, ClipRange(15, 90))
        self.assertEqual(clip_range.frame_count, 75)

    def test_clip_range_and_legacy_trim_round_trip(self):
        clip_range = ClipRange(15, 90)

        trim = clip_range_to_trim(clip_range, 100)

        self.assertEqual(trim, FrameTrim(15, 10))
        self.assertEqual(trim_to_clip_range(trim, 100), clip_range)

    def test_clip_range_rejects_empty_or_reversed_range(self):
        with self.assertRaisesRegex(ValueError, "종료 프레임"):
            ClipRange(5, 5)
        with self.assertRaisesRegex(ValueError, "종료 프레임"):
            ClipRange(8, 7)
        with self.assertRaisesRegex(ValueError, "정수 프레임"):
            ClipRange(1.5, 7)

    def test_edit_clip_rejects_range_outside_source(self):
        with self.assertRaisesRegex(ValueError, "원본 프레임 범위"):
            self.make_clip(source_range=ClipRange(10, 101))

    def test_edit_sequence_split_preserves_total_length_and_source_boundary(self):
        sequence = EditSequence((self.make_clip(),))

        split = sequence.split("clip-a", 40, "clip-left", "clip-right")

        self.assertEqual([clip.clip_id for clip in split.clips], ["clip-left", "clip-right"])
        self.assertEqual(split.clips[0].source_range, ClipRange(10, 40))
        self.assertEqual(split.clips[1].source_range, ClipRange(40, 90))
        self.assertEqual(split.frame_count, sequence.frame_count)

    def test_edit_sequence_delete_duplicate_and_reorder_are_immutable(self):
        original = EditSequence(
            (
                self.make_clip("clip-a", ClipRange(0, 20)),
                self.make_clip("clip-b", ClipRange(20, 40)),
            )
        )

        duplicated = original.duplicate("clip-a", "clip-a-copy")
        reordered = duplicated.move("clip-b", 0)
        deleted = reordered.delete("clip-a")

        self.assertEqual([clip.clip_id for clip in original.clips], ["clip-a", "clip-b"])
        self.assertEqual(
            [clip.clip_id for clip in duplicated.clips],
            ["clip-a", "clip-a-copy", "clip-b"],
        )
        self.assertEqual(
            [clip.clip_id for clip in reordered.clips],
            ["clip-b", "clip-a", "clip-a-copy"],
        )
        self.assertEqual(
            [clip.clip_id for clip in deleted.clips],
            ["clip-b", "clip-a-copy"],
        )

    def test_edit_sequence_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "중복"):
            EditSequence((self.make_clip("same"), self.make_clip("same")))

    def test_edit_sequence_adapts_to_existing_media_item_contract(self):
        sequence = EditSequence((self.make_clip(source_range=ClipRange(15, 90)),))

        media_items = edit_sequence_to_media_items(sequence)

        self.assertEqual(len(media_items), 1)
        self.assertEqual(media_items[0].source_path, "input.mp4")
        self.assertEqual(media_items[0].trim, FrameTrim())
        self.assertEqual(media_items[0].source_range, ClipRange(15, 90))
        self.assertEqual(media_items[0].fps, 24.0)
        self.assertEqual(media_items[0].frame_count, 100)

    def test_workspace_state_routes_range_changes_through_edit_sequence(self):
        state = WorkspaceState(
            edit_sequence=EditSequence((self.make_clip(),)),
            selected_clip_id="clip-a",
        )

        changed = state.set_clip_range("clip-a", ClipRange(20, 70))

        self.assertEqual(state.selected_clip.source_range, ClipRange(10, 90))
        self.assertEqual(changed.selected_clip.source_range, ClipRange(20, 70))

    def test_workspace_split_selects_right_clip_and_preserves_total_length(self):
        state = WorkspaceState(
            edit_sequence=EditSequence((self.make_clip(),)),
            selected_clip_id="clip-a",
        )

        split = state.split_clip("clip-a", 40, "clip-left", "clip-right")

        self.assertEqual(split.selected_clip_id, "clip-right")
        self.assertEqual(split.edit_sequence.frame_count, state.edit_sequence.frame_count)

    def test_workspace_delete_selects_next_clip_or_clears_selection(self):
        state = WorkspaceState(
            edit_sequence=EditSequence(
                (self.make_clip("clip-a"), self.make_clip("clip-b"))
            ),
            selected_clip_id="clip-a",
        )

        one_clip = state.delete_clip("clip-a")
        empty = one_clip.delete_clip("clip-b")

        self.assertEqual(one_clip.selected_clip_id, "clip-b")
        self.assertIsNone(empty.selected_clip_id)
        self.assertEqual(empty.edit_sequence.clips, ())

    def test_workspace_duplicate_move_and_output_return_new_states(self):
        state = WorkspaceState(
            edit_sequence=EditSequence(
                (self.make_clip("clip-a"), self.make_clip("clip-b"))
            ),
            selected_clip_id="clip-a",
        )

        duplicated = state.duplicate_clip("clip-a", "clip-copy")
        moved = duplicated.move_clip("clip-copy", 2)
        configured = moved.with_output("result.mp4", "nvenc_h264")

        self.assertEqual(
            [clip.clip_id for clip in state.edit_sequence.clips],
            ["clip-a", "clip-b"],
        )
        self.assertEqual(
            [clip.clip_id for clip in moved.edit_sequence.clips],
            ["clip-a", "clip-b", "clip-copy"],
        )
        self.assertEqual(configured.output_file, "result.mp4")
        self.assertEqual(configured.preset_id, "nvenc_h264")

    def test_validate_encoding_job_rejects_empty_output_path(self):
        job = EncodingJob(
            media_items=[
                MediaItem(
                    source_path="input.mp4",
                    media_type=MediaType.VIDEO,
                    trim=FrameTrim(),
                )
            ],
            output_file="",
            options=EncodingOptions(),
        )

        with self.assertRaisesRegex(ValueError, "출력 경로"):
            validate_encoding_job(job)

    def test_validate_encoding_job_rejects_empty_media_items(self):
        job = EncodingJob(
            media_items=[],
            output_file="output.mp4",
            options=EncodingOptions(),
        )

        with self.assertRaisesRegex(ValueError, "소스를 하나 이상"):
            validate_encoding_job(job)


if __name__ == "__main__":
    unittest.main()
