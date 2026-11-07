"""Negative tests: the guardrails must reject posts that break brand or fact rules.

Run:  python -m unittest discover -s tests -v
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from guardrails import check_post  # noqa: E402

GOOD = json.loads((ROOT / "outputs" / "2026-W45" / "posts.json").read_text(encoding="utf-8"))["posts"][1]


class GuardrailTests(unittest.TestCase):
    def test_good_post_passes(self):
        self.assertEqual(check_post(GOOD), [])

    def test_invented_number_is_flagged(self):
        p = copy.deepcopy(GOOD)
        p["caption"] = p["caption"].replace("4,4%", "9,9%")
        self.assertTrue(any("9.9" in x for x in check_post(p)))

    def test_guarantee_language_is_flagged(self):
        p = copy.deepcopy(GOOD)
        p["caption"] += " Pengajuan KPR kamu pasti disetujui!"
        self.assertTrue(any("banned phrase" in x for x in check_post(p)))

    def test_competitor_is_flagged(self):
        p = copy.deepcopy(GOOD)
        p["caption"] += " Bandingkan juga dengan Lamudi."
        self.assertTrue(any("competitor" in x for x in check_post(p)))

    def test_missing_brand_hashtag_is_flagged(self):
        p = copy.deepcopy(GOOD)
        p["hashtags"] = [h for h in p["hashtags"] if h != "#Rumah123"]
        self.assertTrue(any("#Rumah123" in x for x in check_post(p)))

    def test_too_long_caption_is_flagged(self):
        p = copy.deepcopy(GOOD)
        p["caption"] += " kata" * 80
        self.assertTrue(any("caption has" in x for x in check_post(p)))

    def test_unattributed_statistic_is_flagged(self):
        p = copy.deepcopy(GOOD)
        for term in ("Bank Indonesia", "BI"):
            p["caption"] = p["caption"].replace(term, "sumber")
        p["hook"] = p["hook"]
        self.assertTrue(any("names the source" in x for x in check_post(p)))


if __name__ == "__main__":
    unittest.main()
