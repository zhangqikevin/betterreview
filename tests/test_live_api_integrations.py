from __future__ import annotations

import importlib.util
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAME = "Mikiya Wagyu Shabu House"
ADDRESS = "3745 Alton Pkwy, Irvine, CA 92606"


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


source_discovery = load_module(
    "live_source_discovery",
    "skills/review-source-discovery/scripts/discover_sources.py",
)
competitor_discovery = load_module(
    "live_competitor_discovery",
    "skills/competitor-discovery-management/scripts/discover_competitors.py",
)
review_ingestion = load_module(
    "live_review_ingestion",
    "skills/review-ingestion-storage/scripts/ingest_reviews.py",
)


def live_tests_enabled() -> bool:
    return os.environ.get("RUN_LIVE_API_TESTS") == "1"


def assert_dns_works(host: str) -> None:
    try:
        socket.getaddrinfo(host, 443)
    except OSError as exc:
        raise AssertionError(
            f"Live API test cannot reach DNS for {host}: {exc}. "
            "This is an environment/network failure before API credentials are used."
        ) from exc


@unittest.skipUnless(live_tests_enabled(), "Set RUN_LIVE_API_TESTS=1 to call real external APIs.")
class LiveApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_discovery.load_dotenv_if_needed()
        competitor_discovery.load_dotenv_if_needed()
        review_ingestion.load_dotenv_if_needed()

    def test_real_google_serpapi_competitors_and_reviews_for_mikiya(self):
        self.assertTrue(os.environ.get("GOOGLE_PLACES_API_KEY"), "Missing GOOGLE_PLACES_API_KEY.")
        self.assertTrue(os.environ.get("SERPAPI_API_KEY"), "Missing SERPAPI_API_KEY.")
        assert_dns_works("maps.googleapis.com")
        assert_dns_works("serpapi.com")

        profile = source_discovery.build_profile(NAME, ADDRESS, None, None)
        self.assertEqual(profile["sources"]["google"]["status"], "matched", json.dumps(profile["sources"]["google"], ensure_ascii=False))
        self.assertEqual(profile["sources"]["yelp"]["status"], "matched", json.dumps(profile["sources"]["yelp"], ensure_ascii=False))
        self.assertTrue(profile["sources"]["google"]["id"])
        self.assertTrue(profile["sources"]["yelp"].get("id") or profile["sources"]["yelp"].get("url"))

        competitors = competitor_discovery.build_competitors(
            source_profile=profile,
            radius_miles=10,
            desired_count=5,
            category_hint="shabu",
            auto_select=True,
        )
        self.assertGreaterEqual(
            len(competitors["approved_competitors"]),
            1,
            json.dumps(competitors.get("data_gaps", []), ensure_ascii=False),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "review-store.json"
            existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            store = review_ingestion.build_store(
                source_profile=profile,
                competitors=competitors,
                existing=existing,
                mode="initial",
                max_reviews=5,
                language="en",
            )

        target_reviews = [
            review
            for review in store["reviews"]
            if review.get("restaurant_role") == "target" and review.get("text")
        ]
        self.assertGreaterEqual(
            len(target_reviews),
            1,
            json.dumps(store.get("data_gaps", []), ensure_ascii=False),
        )
        self.assertGreaterEqual(len(store["restaurants"]), 2)
        self.assertIn("google", store["ingestion_runs"][-1]["providers_attempted"])
        self.assertIn("yelp", store["ingestion_runs"][-1]["providers_attempted"])


if __name__ == "__main__":
    unittest.main()
