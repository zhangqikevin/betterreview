#!/usr/bin/env python3
"""Ingest and deduplicate public reviews for Better Review.

Usage:
  SERPAPI_API_KEY=... \
    python skills/review-ingestion-storage/scripts/ingest_reviews.py \
    --mode initial --max-reviews 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_PROFILE = ROOT / "data" / "source-profile.json"
DEFAULT_COMPETITORS = ROOT / "data" / "competitors.json"
DEFAULT_OUTPUT = ROOT / "data" / "review-store.json"
ENV_FILE = ROOT / ".env"
SUPPORTED_PLATFORMS = ("google", "yelp")


def load_dotenv_if_needed() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def credential_status() -> dict[str, bool]:
    return {"serpapi_key_present": bool(os.environ.get("SERPAPI_API_KEY"))}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"Missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "BetterReview/0.1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def provider_error(provider: str, exc: Exception) -> str:
    raw = str(exc)
    reason = getattr(exc, "reason", None)
    reason_text = str(reason or raw)
    lower = reason_text.lower()
    if isinstance(exc, PermissionError) or isinstance(reason, PermissionError) or "operation not permitted" in lower:
        return f"{provider} 暂时无法连接：当前运行环境禁止外部网络连接。API key 已读取，但请求没有被发出；请在允许外网访问的运行环境中重试。"
    if isinstance(reason, socket.gaierror) or "nodename nor servname" in lower or "name or service not known" in lower:
        return f"{provider} 暂时无法连接：当前运行环境无法解析外部服务域名。API key 已读取，但 DNS 不可用；请在允许外网访问的运行环境中重试。"
    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in lower or "timeout" in lower:
        return f"{provider} 暂时无法连接：请求超时。API key 已读取，已标记为可重试网络问题。"
    if isinstance(exc, urllib.error.URLError) or "urlopen error" in lower:
        return f"{provider} 暂时无法连接：网络请求失败（{reason_text}）。API key 已读取，已标记为可重试网络问题。"
    return f"{provider} review ingestion failed: {raw}"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    digits = "".join(char for char in str(value) if char.isdigit())
    return int(digits) if digits else None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def source_name(source: dict[str, Any]) -> str | None:
    return source.get("name") or source.get("title")


def source_address(source: dict[str, Any]) -> str | None:
    address = source.get("address") or source.get("location") or source.get("formatted_address")
    if isinstance(address, list):
        return ", ".join(str(part) for part in address if part)
    if isinstance(address, dict):
        return ", ".join(str(value) for value in address.values() if value)
    return address


def snapshot(platform: str, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": platform,
        "source_id": source.get("id"),
        "source_url": source.get("url"),
        "source_status": source.get("status"),
        "confidence": source.get("confidence"),
        "rating": as_float(source.get("rating")),
        "review_count": as_int(source.get("review_count")),
        "business_status": source.get("business_status"),
        "captured_at": utc_now(),
    }


def monitoring_set(source_profile: dict[str, Any], competitors: dict[str, Any]) -> list[dict[str, Any]]:
    target = {
        "restaurant_key": "target",
        "role": "target",
        "name": source_profile["target"]["name"],
        "address": source_profile["target"]["address"],
        "sources": source_profile["sources"],
    }
    restaurants = [target]
    for index, competitor in enumerate(competitors.get("approved_competitors") or [], start=1):
        google = competitor.get("google") or {}
        yelp = competitor.get("yelp") or {}
        key_source = google.get("id") or yelp.get("id") or source_name(google) or f"competitor-{index}"
        restaurants.append(
            {
                "restaurant_key": f"competitor:{stable_hash(str(key_source))}",
                "role": "competitor",
                "name": source_name(google) or source_name(yelp) or f"Competitor {index}",
                "address": source_address(google) or source_address(yelp),
                "sources": {"google": google, "yelp": yelp},
            }
        )
    return restaurants


def fetch_google_reviews(source: dict[str, Any], api_key: str, max_reviews: int, language: str) -> dict[str, Any]:
    params = {
        "engine": "google_maps_reviews",
        "place_id": source.get("id"),
        "hl": language,
        "sort_by": "newestFirst",
        "api_key": api_key,
    }
    result = get_json("https://serpapi.com/search.json", params)
    reviews = result.get("reviews") or result.get("user_reviews") or []
    return {"raw": result, "reviews": reviews[:max_reviews]}


def fetch_yelp_reviews(source: dict[str, Any], api_key: str, max_reviews: int, language: str) -> dict[str, Any]:
    params = {
        "engine": "yelp_reviews",
        "place_id": source.get("id"),
        "url": source.get("url"),
        "hl": language,
        "api_key": api_key,
    }
    result = get_json("https://serpapi.com/search.json", params)
    reviews = result.get("reviews") or result.get("organic_results") or []
    return {"raw": result, "reviews": reviews[:max_reviews]}


def extract_author(raw: dict[str, Any]) -> str | None:
    user = raw.get("user") or raw.get("author") or raw.get("reviewer")
    if isinstance(user, dict):
        return user.get("name") or user.get("title")
    return raw.get("user_name") or raw.get("author_name") or raw.get("name") or raw.get("username") or user


def extract_text(raw: dict[str, Any]) -> str | None:
    value = raw.get("snippet") or raw.get("text") or raw.get("comment") or raw.get("review")
    if isinstance(value, dict):
        return value.get("text") or value.get("snippet")
    return value


def extract_date(raw: dict[str, Any]) -> str | None:
    return raw.get("date") or raw.get("iso_date") or raw.get("published_at") or raw.get("time")


def extract_review_id(platform: str, source_id: str | None, raw: dict[str, Any]) -> str | None:
    value = raw.get("review_id") or raw.get("id") or raw.get("link") or raw.get("url")
    if value:
        return f"{platform}:{value}"
    author = extract_author(raw) or ""
    date = extract_date(raw) or ""
    rating = str(raw.get("rating") or "")
    text = extract_text(raw) or ""
    if not any((author, date, rating, text)):
        return None
    return f"{platform}:synthetic:{stable_hash('|'.join([source_id or '', author, date, rating, text]))}"


def normalize_review(
    raw: dict[str, Any],
    platform: str,
    restaurant: dict[str, Any],
    source: dict[str, Any],
    run_id: str,
) -> dict[str, Any] | None:
    source_id = source.get("id")
    review_id = extract_review_id(platform, source_id, raw)
    text = extract_text(raw)
    if not review_id and not text:
        return None
    owner_response = raw.get("owner_response") or raw.get("response")
    return {
        "review_key": review_id or f"{platform}:synthetic:{stable_hash(json.dumps(raw, sort_keys=True, ensure_ascii=False))}",
        "platform": platform,
        "restaurant_key": restaurant["restaurant_key"],
        "restaurant_role": restaurant["role"],
        "restaurant_name": restaurant["name"],
        "source_id": source_id,
        "source_url": source.get("url"),
        "author": extract_author(raw),
        "rating": as_float(raw.get("rating") or raw.get("stars")),
        "published_at": extract_date(raw),
        "relative_date": raw.get("relative_date") or raw.get("date"),
        "text": text,
        "language": raw.get("language"),
        "review_url": raw.get("link") or raw.get("url"),
        "owner_response": owner_response if isinstance(owner_response, (dict, str)) else None,
        "first_seen_at": utc_now(),
        "last_seen_at": utc_now(),
        "seen_in_run_id": run_id,
        "raw": raw,
    }


def data_gap(platform: str, restaurant: dict[str, Any], reason: str, retryable: bool = True) -> dict[str, Any]:
    return {
        "platform": platform,
        "restaurant_key": restaurant["restaurant_key"],
        "restaurant_name": restaurant["name"],
        "reason": reason,
        "retryable": retryable,
        "recorded_at": utc_now(),
    }


def ingest_platform(
    restaurant: dict[str, Any],
    platform: str,
    source: dict[str, Any],
    api_key: str | None,
    max_reviews: int,
    language: str,
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    platform_snapshot = snapshot(platform, source)
    if source.get("status") != "matched" or not source.get("id") and not source.get("url"):
        upstream_reason = (source.get("raw") or {}).get("reason")
        reason = f"来源未匹配，暂时无法抓取评论。上游原因：{upstream_reason}" if upstream_reason else "Source is missing or not confidently matched."
        return [], [data_gap(platform, restaurant, reason)], platform_snapshot
    if not api_key:
        return [], [data_gap(platform, restaurant, "Missing SERPAPI_API_KEY.")], platform_snapshot

    try:
        if platform == "google":
            result = fetch_google_reviews(source, api_key, max_reviews, language)
        elif platform == "yelp":
            result = fetch_yelp_reviews(source, api_key, max_reviews, language)
        else:
            return [], [data_gap(platform, restaurant, "Unsupported platform.", retryable=False)], platform_snapshot
    except Exception as exc:
        return [], [data_gap(platform, restaurant, provider_error("SerpApi 评论抓取", exc))], platform_snapshot

    raw_reviews = result["reviews"]
    normalized = [review for review in (normalize_review(raw, platform, restaurant, source, run_id) for raw in raw_reviews) if review]
    gaps = []
    if not raw_reviews:
        message = result["raw"].get("error") or "Provider returned no visible review records."
        gaps.append(data_gap(platform, restaurant, message))
    elif not any(review.get("text") for review in normalized):
        gaps.append(data_gap(platform, restaurant, "Provider returned review records without visible review text."))

    platform_snapshot["provider_status"] = "ok" if raw_reviews else "empty"
    platform_snapshot["raw_result_metadata"] = {
        "search_metadata": result["raw"].get("search_metadata"),
        "search_parameters": result["raw"].get("search_parameters"),
    }
    return normalized, gaps, platform_snapshot


def merge_reviews(existing: dict[str, Any], incoming: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    by_key = {review["review_key"]: review for review in existing.get("reviews", [])}
    new_keys = []
    for review in incoming:
        key = review["review_key"]
        if key in by_key:
            original = by_key[key]
            original["last_seen_at"] = review["last_seen_at"]
            original["seen_in_run_id"] = review["seen_in_run_id"]
            original["raw"] = review["raw"]
            if review.get("text") and not original.get("text"):
                original["text"] = review["text"]
        else:
            by_key[key] = review
            new_keys.append(key)
    return sorted(by_key.values(), key=lambda item: item.get("first_seen_at") or ""), new_keys


def build_store(
    source_profile: dict[str, Any],
    competitors: dict[str, Any],
    existing: dict[str, Any],
    mode: str,
    max_reviews: int,
    language: str,
) -> dict[str, Any]:
    load_dotenv_if_needed()
    started_at = utc_now()
    run_id = f"{mode}:{stable_hash(started_at)}"
    api_key = os.environ.get("SERPAPI_API_KEY")
    restaurants = monitoring_set(source_profile, competitors)
    snapshots = []
    data_gaps: list[dict[str, Any]] = []
    incoming_reviews = []
    providers_attempted = []

    for restaurant in restaurants:
        for platform in SUPPORTED_PLATFORMS:
            source = restaurant["sources"].get(platform) or {}
            providers_attempted.append(platform)
            reviews, gaps, platform_snapshot = ingest_platform(restaurant, platform, source, api_key, max_reviews, language, run_id)
            incoming_reviews.extend(reviews)
            data_gaps.extend(gaps)
            snapshots.append(platform_snapshot)

    reviews, new_review_keys = merge_reviews(existing, incoming_reviews)
    finished_at = utc_now()
    return {
        "version": "0.1.0",
        "restaurants": [
            {
                "restaurant_key": item["restaurant_key"],
                "role": item["role"],
                "name": item["name"],
                "address": item["address"],
            }
            for item in restaurants
        ],
        "reviews": reviews,
        "new_review_keys": new_review_keys,
        "platform_snapshots": snapshots,
        "ingestion_runs": list(existing.get("ingestion_runs", []))
        + [
            {
                "run_id": run_id,
                "mode": mode,
                "started_at": started_at,
                "finished_at": finished_at,
                "providers_attempted": sorted(set(providers_attempted)),
                "restaurants_scanned": len(restaurants),
                "reviews_seen": len(incoming_reviews),
                "new_reviews": len(new_review_keys),
                "max_reviews_per_platform": max_reviews,
            }
        ],
        "data_gaps": data_gaps,
        "runtime_diagnostics": credential_status(),
        "last_checked_at": finished_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-profile", default=str(DEFAULT_SOURCE_PROFILE))
    parser.add_argument("--competitors", default=str(DEFAULT_COMPETITORS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", choices=["initial", "daily", "weekly"], default="initial")
    parser.add_argument("--max-reviews", type=int, default=50)
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    source_profile = load_json(Path(args.source_profile))
    competitors = load_json(Path(args.competitors), default={"approved_competitors": []})
    existing = load_json(Path(args.output), default={})
    store = build_store(source_profile, competitors, existing, args.mode, args.max_reviews, args.language)
    write_json(Path(args.output), store)
    print(f"Wrote {args.output}")
    print(f"New reviews: {len(store['new_review_keys'])}")
    print(f"Data gaps: {len(store['data_gaps'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
