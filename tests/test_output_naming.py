import os
import tempfile
import unittest

from app.core.output_naming import next_available_output_path


class OutputNamingTests(unittest.TestCase):
    def test_adds_first_available_number(self):
        with tempfile.TemporaryDirectory() as directory:
            original = os.path.join(directory, "result.mkv")
            open(original, "wb").close()

            candidate = next_available_output_path(original)

            self.assertEqual(candidate, os.path.join(directory, "result_001.mkv"))

    def test_skips_existing_numbers_and_continues_numbered_name(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("result.mkv", "result_001.mkv", "result_002.mkv"):
                open(os.path.join(directory, name), "wb").close()

            candidate = next_available_output_path(
                os.path.join(directory, "result_001.mkv")
            )

            self.assertEqual(candidate, os.path.join(directory, "result_003.mkv"))


if __name__ == "__main__":
    unittest.main()
