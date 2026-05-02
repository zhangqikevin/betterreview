from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


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
    "source_discovery",
    "skills/review-source-discovery/scripts/discover_sources.py",
)
competitor_discovery = load_module(
    "competitor_discovery",
    "skills/competitor-discovery-management/scripts/discover_competitors.py",
)
review_ingestion = load_module(
    "review_ingestion",
    "skills/review-ingestion-storage/scripts/ingest_reviews.py",
)


def mikiya_google_search_result():
    return {
        "results": [
            {
                "place_id": "google-mikiya",
                "name": NAME,
                "formatted_address": ADDRESS,
                "geometry": {"location": {"lat": 33.6847, "lng": -117.8122}},
                "business_status": "OPERATIONAL",
                "rating": 4.8,
                "user_ratings_total": 321,
                "types": ["restaurant", "food"],
            }
        ]
    }


def mikiya_google_details_result():
    return {
        "result": {
            "place_id": "google-mikiya",
            "name": NAME,
            "formatted_address": ADDRESS,
            "geometry": {"location": {"lat": 33.6847, "lng": -117.8122}},
            "business_status": "OPERATIONAL",
            "rating": 4.8,
            "user_ratings_total": 321,
            "url": "https://maps.google.com/?cid=mikiya",
            "types": ["restaurant", "food"],
        }
    }


def mikiya_yelp_search_result():
    return {
        "organic_results": [
            {
                "place_id": "yelp-mikiya",
                "name": NAME,
                "address": ADDRESS,
                "rating": 4.5,
                "reviews": "210 reviews",
                "link": "https://www.yelp.com/biz/mikiya-wagyu-shabu-house-irvine",
            }
        ]
    }


class ApiIntegrationTests(unittest.TestCase):
    def test_source_discovery_matches_google_and_yelp_for_mikiya(self):
        def fake_get_json(url, params):
            if "maps.googleapis.com" in url and "textsearch" in url:
                self.assertIn(NAME, params["query"])
                self.assertIn("Irvine", params["query"])
                return mikiya_google_search_result()
            if "maps.googleapis.com" in url and "details" in url:
                self.assertEqual(params["place_id"], "google-mikiya")
                return mikiya_google_details_result()
            if "serpapi.com" in url:
                self.assertEqual(params["engine"], "yelp")
                self.assertEqual(params["find_desc"], NAME)
                return mikiya_yelp_search_result()
            raise AssertionError(f"Unexpected request: {url} {params}")

        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-google", "SERPAPI_API_KEY": "test-serp"}, clear=False):
            with patch.object(source_discovery, "get_json", side_effect=fake_get_json):
                profile = source_discovery.build_profile(NAME, ADDRESS, None, None)

        self.assertEqual(profile["sources"]["google"]["status"], "matched")
        self.assertEqual(profile["sources"]["google"]["id"], "google-mikiya")
        self.assertEqual(profile["sources"]["yelp"]["status"], "matched")
        self.assertEqual(profile["sources"]["yelp"]["id"], "yelp-mikiya")
        self.assertEqual(profile["data_gaps"], [])
        self.assertTrue(profile["runtime_diagnostics"]["google_places_key_present"])
        self.assertTrue(profile["runtime_diagnostics"]["serpapi_key_present"])

    def test_competitor_discovery_returns_approved_restaurant_list(self):
        source_profile = {
            "target": {"name": NAME, "address": ADDRESS},
            "sources": {"google": source_discovery.compact_google(mikiya_google_details_result()["result"], NAME, ADDRESS)},
        }
        nearby_results = {
            "results": [
                {
                    "place_id": "google-competitor-1",
                    "name": "All That Shabu",
                    "vicinity": "15315 Culver Dr, Irvine, CA",
                    "geometry": {"location": {"lat": 33.697, "lng": -117.798}},
                    "business_status": "OPERATIONAL",
                    "rating": 4.6,
                    "user_ratings_total": 980,
                    "types": ["restaurant", "food"],
                },
                {
                    "place_id": "google-competitor-2",
                    "name": "Slice Shabu",
                    "vicinity": "16871 Beach Blvd, Huntington Beach, CA",
                    "geometry": {"location": {"lat": 33.716, "lng": -117.989}},
                    "business_status": "OPERATIONAL",
                    "rating": 4.4,
                    "user_ratings_total": 650,
                    "types": ["restaurant", "food"],
                },
            ]
        }

        def fake_get_json(url, params):
            if "nearbysearch" in url:
                self.assertIn(params["keyword"], {"shabu", "shabu shabu", "hot pot", "japanese hot pot", "sukiyaki", "wagyu hot pot"})
                return nearby_results if params["keyword"] == "shabu" else {"results": []}
            if "details" in url:
                place_id = params["place_id"]
                candidate = next(item for item in nearby_results["results"] if item["place_id"] == place_id)
                return {"result": {**candidate, "formatted_address": candidate["vicinity"], "url": f"https://maps.google.com/?cid={place_id}"}}
            if "serpapi.com" in url:
                return {
                    "organic_results": [
                        {
                            "place_id": f"yelp-{params['find_desc'].lower().replace(' ', '-')}",
                            "name": params["find_desc"],
                            "address": params["find_loc"],
                            "rating": 4.3,
                            "reviews": "100 reviews",
                            "categories": [{"title": "Hot Pot"}, {"title": "Japanese"}],
                            "price": "$$$",
                            "link": "https://www.yelp.com/biz/example",
                        }
                    ]
                }
            raise AssertionError(f"Unexpected request: {url} {params}")

        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-google", "SERPAPI_API_KEY": "test-serp"}, clear=False):
            with patch.object(competitor_discovery, "get_json", side_effect=fake_get_json):
                competitors = competitor_discovery.build_competitors(
                    source_profile=source_profile,
                    radius_miles=10,
                    desired_count=2,
                    category_hint="shabu",
                    auto_select=True,
                )

        self.assertEqual(len(competitors["suggested_competitors"]), 2)
        self.assertEqual(len(competitors["approved_competitors"]), 2)
        self.assertEqual(competitors["settings"]["confirmation_mode"], "auto_selected")
        self.assertEqual(competitors["settings"]["target_profile"]["category_key"], "hot_pot")
        self.assertEqual(competitors["data_gaps"], [])
        self.assertNotEqual(competitors["approved_competitors"][0]["google"]["id"], "google-mikiya")

    def test_competitor_discovery_downranks_unrelated_nearby_restaurants(self):
        source_profile = {
            "target": {"name": NAME, "address": ADDRESS},
            "sources": {
                "google": source_discovery.compact_google(mikiya_google_details_result()["result"], NAME, ADDRESS),
                "yelp": source_discovery.compact_yelp(
                    {
                        **mikiya_yelp_search_result()["organic_results"][0],
                        "categories": [{"title": "Hot Pot"}, {"title": "Japanese"}],
                        "price": "$$$",
                        "snippet": "AYCE shabu shabu spot for quality meat.",
                    },
                    NAME,
                    ADDRESS,
                ),
            },
        }
        nearby_by_keyword = {
            "hot pot": [
                {
                    "place_id": "google-hot-pot",
                    "name": "All That Shabu",
                    "vicinity": "15315 Culver Dr, Irvine, CA",
                    "geometry": {"location": {"lat": 33.697, "lng": -117.798}},
                    "business_status": "OPERATIONAL",
                    "rating": 4.6,
                    "user_ratings_total": 980,
                    "types": ["restaurant", "food"],
                },
                {
                    "place_id": "google-steakhouse",
                    "name": "Prime American Steakhouse",
                    "vicinity": "3900 Alton Pkwy, Irvine, CA",
                    "geometry": {"location": {"lat": 33.683, "lng": -117.816}},
                    "business_status": "OPERATIONAL",
                    "rating": 4.9,
                    "user_ratings_total": 4000,
                    "types": ["restaurant", "food"],
                },
            ]
        }

        def fake_get_json(url, params):
            if "nearbysearch" in url:
                return {"results": nearby_by_keyword.get(params["keyword"], [])}
            if "details" in url:
                for candidates in nearby_by_keyword.values():
                    for candidate in candidates:
                        if candidate["place_id"] == params["place_id"]:
                            return {"result": {**candidate, "formatted_address": candidate["vicinity"], "url": f"https://maps.google.com/?cid={candidate['place_id']}"}}
            if "serpapi.com" in url:
                if "Shabu" in params["find_desc"]:
                    categories = [{"title": "Hot Pot"}, {"title": "Japanese"}]
                    price = "$$$"
                    snippet = "Shabu shabu and hot pot restaurant."
                else:
                    categories = [{"title": "Steakhouses"}, {"title": "American"}]
                    price = "$$$$"
                    snippet = "American steakhouse and bar."
                return {
                    "organic_results": [
                        {
                            "place_id": f"yelp-{params['find_desc'].lower().replace(' ', '-')}",
                            "name": params["find_desc"],
                            "address": params["find_loc"],
                            "rating": 4.5,
                            "reviews": "500 reviews",
                            "categories": categories,
                            "price": price,
                            "snippet": snippet,
                            "link": "https://www.yelp.com/biz/example",
                        }
                    ]
                }
            raise AssertionError(f"Unexpected request: {url} {params}")

        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-google", "SERPAPI_API_KEY": "test-serp"}, clear=False):
            with patch.object(competitor_discovery, "get_json", side_effect=fake_get_json):
                competitors = competitor_discovery.build_competitors(
                    source_profile=source_profile,
                    radius_miles=10,
                    desired_count=2,
                    category_hint=None,
                    auto_select=True,
                )

        approved_names = [item["google"]["name"] for item in competitors["approved_competitors"]]
        self.assertEqual(approved_names, ["All That Shabu"])
        self.assertIn("同类关键词", competitors["approved_competitors"][0]["selection_reason"])
        suggested_names = [item["google"]["name"] for item in competitors["suggested_competitors"]]
        self.assertNotIn("Prime American Steakhouse", suggested_names)

    def test_review_ingestion_fetches_target_and_competitor_reviews(self):
        source_profile = {
            "target": {"name": NAME, "address": ADDRESS},
            "sources": {
                "google": source_discovery.compact_google(mikiya_google_details_result()["result"], NAME, ADDRESS),
                "yelp": source_discovery.compact_yelp(mikiya_yelp_search_result()["organic_results"][0], NAME, ADDRESS),
            },
        }
        competitors = {
            "approved_competitors": [
                {
                    "google": {
                        "status": "matched",
                        "confidence": "high",
                        "id": "google-competitor-1",
                        "url": "https://maps.google.com/?cid=competitor-1",
                        "name": "All That Shabu",
                        "address": "15315 Culver Dr, Irvine, CA",
                        "rating": 4.6,
                        "review_count": 980,
                        "business_status": "OPERATIONAL",
                    },
                    "yelp": {
                        "status": "matched",
                        "confidence": "high",
                        "id": "yelp-competitor-1",
                        "url": "https://www.yelp.com/biz/all-that-shabu",
                        "name": "All That Shabu",
                        "address": "15315 Culver Dr, Irvine, CA",
                        "rating": 4.3,
                        "review_count": 100,
                    },
                }
            ]
        }

        def fake_get_json(url, params):
            self.assertEqual(url, "https://serpapi.com/search.json")
            if params["engine"] == "google_maps_reviews":
                return {
                    "reviews": [
                        {
                            "review_id": f"g-{params['place_id']}",
                            "user": {"name": "Google Reviewer"},
                            "rating": 5,
                            "date": "2026-05-01",
                            "snippet": "Great wagyu and attentive service.",
                            "link": "https://maps.google.com/review",
                        }
                    ],
                    "search_metadata": {"status": "Success"},
                    "search_parameters": {"engine": "google_maps_reviews"},
                }
            if params["engine"] == "yelp_reviews":
                return {
                    "reviews": [
                        {
                            "id": f"y-{params['place_id']}",
                            "user": {"name": "Yelp Reviewer"},
                            "rating": 4,
                            "date": "2026-04-30",
                            "comment": "Fresh ingredients and a clean dining room.",
                            "url": "https://www.yelp.com/review",
                        }
                    ],
                    "search_metadata": {"status": "Success"},
                    "search_parameters": {"engine": "yelp_reviews"},
                }
            raise AssertionError(f"Unexpected request: {url} {params}")

        with patch.dict(os.environ, {"SERPAPI_API_KEY": "test-serp"}, clear=False):
            with patch.object(review_ingestion, "get_json", side_effect=fake_get_json):
                store = review_ingestion.build_store(
                    source_profile=source_profile,
                    competitors=competitors,
                    existing={},
                    mode="initial",
                    max_reviews=5,
                    language="en",
                )

        self.assertEqual(len(store["restaurants"]), 2)
        self.assertEqual(len(store["reviews"]), 4)
        self.assertEqual(len(store["new_review_keys"]), 4)
        self.assertEqual(store["data_gaps"], [])
        self.assertEqual(store["ingestion_runs"][0]["providers_attempted"], ["google", "yelp"])
        self.assertTrue(all(review["text"] for review in store["reviews"]))


if __name__ == "__main__":
    unittest.main()
