import unittest

from app.core.job_builder import timeline_range_to_trim, validate_encoding_job
from app.core.models import EncodingJob, EncodingOptions, FrameTrim, MediaItem, MediaType, TimelineRange


class CoreModelTests(unittest.TestCase):
    def test_frame_trim_normalizes_negative_and_float_values(self):
        trim = FrameTrim(-3, 4.8)

        self.assertEqual(trim.head_frames, 0)
        self.assertEqual(trim.tail_frames, 4)

    def test_timeline_range_converts_to_head_tail_trim(self):
        trim = timeline_range_to_trim(TimelineRange(in_frame=11, out_frame=90, frame_count=100))

        self.assertEqual(trim, FrameTrim(head_frames=10, tail_frames=10))

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
