import os
import tempfile
import unittest

from PIL import Image

from app.core.webp_processor import WebPProcessor, read_webp_frame_durations


class WebPProcessorTests(unittest.TestCase):
    def test_reads_animation_durations_from_anmf_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "animated.webp")
            first = Image.new("RGB", (16, 16), "red")
            second = Image.new("RGB", (16, 16), "blue")
            first.save(
                path,
                "WEBP",
                save_all=True,
                append_images=[second],
                duration=[400, 600],
                loop=0,
                lossless=True,
            )

            durations = read_webp_frame_durations(path)
            metadata = WebPProcessor().get_webp_metadata(path)

        self.assertEqual(durations, [400, 600])
        self.assertEqual(metadata["frame_count"], 2)
        self.assertEqual(metadata["duration_ms"], 1000)
        self.assertEqual(metadata["fps"], 2.0)


if __name__ == "__main__":
    unittest.main()
