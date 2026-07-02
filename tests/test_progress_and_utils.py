import unittest
from unittest.mock import patch

from app.core.batch_processor import BatchProcessor
from app.utils.ffmpeg_utils import FFmpegUtils


class ProgressAndUtilsTests(unittest.TestCase):
    def test_progress_updates_are_bounded_and_monotonic(self):
        processor = BatchProcessor(ffmpeg_manager=object())
        processor._last_progress = 0
        values = []

        processor.update_file_progress(100, 0, 2, 0, 0.7, values.append)
        processor.update_file_progress(10, 0, 2, 0, 0.7, values.append)
        processor.update_merge_progress(50, 70, 0.3, values.append)
        processor.update_merge_progress(100, 70, 0.3, values.append)

        self.assertEqual(values, sorted(values))
        self.assertGreaterEqual(values[0], 0)
        self.assertLessEqual(values[-1], 100)
        self.assertEqual(values[-1], 100)

    def test_webp_progress_uses_preparation_stage(self):
        processor = BatchProcessor(ffmpeg_manager=object())
        processor._last_progress = 0
        values = []

        processor.update_webp_progress(50, 0, 3, 2, 0, values.append)
        processor.update_webp_progress(100, 0, 3, 2, 1, values.append)

        self.assertEqual(values, sorted(values))
        self.assertLessEqual(values[-1], 10)

    def test_concat_media_files_uses_media_merger_directly(self):
        utils = FFmpegUtils()

        with patch("app.core.media_merger.MediaMerger.concat_media_files", return_value="out.mp4") as concat:
            result = utils.concat_media_files(["a.mp4", "b.mp4"], "out.mp4", {"c:v": "libx264"})

        self.assertEqual(result, "out.mp4")
        concat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
