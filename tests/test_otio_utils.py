import json
import os
import tempfile
import unittest

from app.utils.otio_utils import generate_and_open_otio


class OTIOUtilsTests(unittest.TestCase):
    def test_generate_otio_uses_current_manager_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "timeline.otio")

            generate_and_open_otio([], output_path)

            with open(output_path, encoding="utf-8") as handle:
                timeline = json.load(handle)

        self.assertEqual(timeline["OTIO_SCHEMA"], "Timeline.1")
        self.assertEqual(timeline["tracks"]["children"][0]["children"], [])


if __name__ == "__main__":
    unittest.main()
