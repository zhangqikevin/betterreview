#!/usr/bin/env python3
"""Discover Google and Yelp source IDs for Better Review.

Usage:
  GOOGLE_PLACES_API_KEY=... SERPAPI_API_KEY=... \
    python skills/review-source-discovery/scripts/discover_sources.py \
    --name "Restaurant Name" --address "123 Main St, City, ST"
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "data" / "source-profile.json"
ENV_FILE = ROOT / ".env"


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
    return {
        "google_places_key_present": bool(os.environ.get("GOOGLE_PLACES_API_KEY")),
        "serpapi_key_present": bool(os.environ.get("SERPAPI_API_KEY")),
    }


def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "BetterReview/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize(text: str | None) -> str:
    return " ".join((text or "").lower().replace("&", "and").split())


def similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def confidence(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= 0.66:
        return "medium"
    if score > 0:
        return "low"
    return "missing"


def source_status(score: float) -> str:
    if score >= 0.82:
        return "matched"
    if score > 0:
        return "ambiguous"
    return "missing"


def compact_google(result: dict[str, Any], target_name: str, target_address: str) -> dict[str, Any]:
    name_score = similarity(target_name, result.get("name"))
    address_score = similarity(target_address, result.get("formatted_address"))
    score = round((name_score * 0.55) + (address_score * 0.45), 3)
    geometry = result.get("geometry", {}).get("location")
    return {
        "status": source_status(score),
        "confidence": confidence(score),
        "match_score": score,
        "id": result.get("place_id"),
        "url": result.get("url"),
        "name": result.get("name"),
        "address": result.get("formatted_address"),
        "rating": result.get("rating"),
        "review_count": result.get("user_ratings_total"),
        "coordinates": {"lat": geometry["lat"], "lng": geometry["lng"]} if geometry else None,
        "business_status": result.get("business_status"),
        "raw": result,
    }


def compact_yelp(result: dict[str, Any], target_name: str, target_address: str) -> dict[str, Any]:
    address = result.get("address") or result.get("location") or result.get("formatted_address")
    if isinstance(address, list):
        address = ", ".join(str(part) for part in address if part)
    name_score = similarity(target_name, result.get("name") or result.get("title"))
    address_score = similarity(target_address, address)
    score = round((name_score * 0.6) + (address_score * 0.4), 3)
    coordinates = result.get("coordinates")
    return {
        "status": source_status(score),
        "confidence": confidence(score),
        "match_score": score,
        "id": str(result.get("place_id") or result.get("id") or "") or None,
        "url": result.get("link") or result.get("url"),
        "name": result.get("name") or result.get("title"),
        "address": address,
        "rating": result.get("rating"),
        "review_count": result.get("reviews") or result.get("review_count"),
        "coordinates": coordinates if isinstance(coordinates, dict) else None,
        "business_status": None,
        "raw": result,
    }


def missing_source(reason: str) -> dict[str, Any]:
    return {
        "status": "missing",
        "confidence": "missing",
        "match_score": 0,
        "id": None,
        "url": None,
        "name": None,
        "address": None,
        "rating": None,
        "review_count": None,
        "coordinates": None,
        "business_status": None,
        "raw": {"reason": reason},
    }


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
    return f"{provider} lookup failed: {raw}"


def discover_google(name: str, address: str, api_key: str) -> dict[str, Any]:
    search = get_json(
        "https://maps.googleapis.com/maps/api/place/textsearch/json",
        {"query": f"{name} {address}", "type": "restaurant", "key": api_key},
    )
    candidates = search.get("results", [])
    if not candidates:
        return missing_source(search.get("error_message") or "No Google Places candidates returned.")

    best = max(candidates, key=lambda item: similarity(name, item.get("name")) + similarity(address, item.get("formatted_address")))
    details = get_json(
        "https://maps.googleapis.com/maps/api/place/details/json",
        {
            "place_id": best.get("place_id"),
            "fields": "place_id,name,formatted_address,geometry,business_status,rating,user_ratings_total,url,website,formatted_phone_number,types",
            "key": api_key,
        },
    )
    return compact_google(details.get("result") or best, name, address)


def discover_yelp(name: str, address: str, api_key: str) -> dict[str, Any]:
    result = get_json(
        "https://serpapi.com/search.json",
        {
            "engine": "yelp",
            "find_desc": name,
            "find_loc": address,
            "api_key": api_key,
        },
    )
    candidates = result.get("organic_results") or result.get("results") or []
    if not candidates:
        return missing_source(result.get("error") or "No Yelp candidates returned through SerpApi.")
    best = max(candidates, key=lambda item: similarity(name, item.get("name") or item.get("title")) + similarity(address, str(item)))
    return compact_yelp(best, name, address)


def build_profile(name: str, address: str, phone: str | None, website: str | None) -> dict[str, Any]:
    load_dotenv_if_needed()
    google_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    serpapi_key = os.environ.get("SERPAPI_API_KEY")
    data_gaps: list[dict[str, Any]] = []

    if google_key:
        try:
            google = discover_google(name, address, google_key)
        except Exception as exc:
            google = missing_source(provider_error("Google Places", exc))
    else:
        google = missing_source("Missing GOOGLE_PLACES_API_KEY.")

    if serpapi_key:
        try:
            yelp = discover_yelp(name, address, serpapi_key)
            time.sleep(0.2)
        except Exception as exc:
            yelp = missing_source(provider_error("SerpApi Yelp", exc))
    else:
        yelp = missing_source("Missing SERPAPI_API_KEY.")

    for platform, source in (("google", google), ("yelp", yelp)):
        if source["status"] != "matched":
            data_gaps.append({"platform": platform, "reason": source["raw"].get("reason", "Match requires confirmation."), "retryable": True})

    return {
        "target": {"name": name, "address": address, "phone": phone, "website": website},
        "sources": {"google": google, "yelp": yelp},
        "data_gaps": data_gaps,
        "runtime_diagnostics": credential_status(),
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--phone")
    parser.add_argument("--website")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    profile = build_profile(args.name, args.address, args.phone, args.website)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
