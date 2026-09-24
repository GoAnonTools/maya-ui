import unittest
from types import SimpleNamespace

from backend.wake.sherpa_provider import decoder_result_details


class DecoderResultDetailsTest(unittest.TestCase):
    def test_plain_string_result(self):
        self.assertEqual(decoder_result_details("HEY_MAYA"), ("HEY_MAYA", [], []))

    def test_structured_result(self):
        result = SimpleNamespace(keyword="HEY MAYA", tokens=["HEY", "MAYA"], timestamps=[0.1, 0.2])
        self.assertEqual(decoder_result_details(result), ("HEY MAYA", ["HEY", "MAYA"], [0.1, 0.2]))


if __name__ == "__main__":
    unittest.main()
