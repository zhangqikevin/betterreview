#!/usr/bin/env python3
"""Discover and normalize nearby competitors for Better Review.

Usage:
  GOOGLE_PLACES_API_KEY=... SERPAPI_API_KEY=... \
    python skills/competitor-discovery-management/scripts/discover_competitors.py
"""

from __future__ import annotations

import argparse
import json
import math
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
DEFAULT_SOURCE_PROFILE = ROOT / "data" / "source-profile.json"
DEFAULT_OUTPUT = ROOT / "data" / "competitors.json"
ENV_FILE = ROOT / ".env"
METERS_PER_MILE = 1609.344
DEFAULT_RADIUS_MILES = 10.0
DEFAULT_DESIRED_COUNT = 5
MAX_RAW_CANDIDATES_PER_KEYWORD = 8
MAX_RAW_CANDIDATES_TOTAL = 36
MAX_DETAIL_CANDIDATES = 24
BLOCKED_TYPES = {
    "lodging",
    "gas_station",
    "convenience_store",
    "grocery_or_supermarket",
    "supermarket",
    "liquor_store",
    "meal_delivery",
}
FOOD_TYPES = {"restaurant", "food", "meal_takeaway", "cafe", "bakery", "bar"}
CUISINE_PROFILES = {
    "hot_pot": {
        "label": "日式/亚洲火锅",
        "cuisine": ["火锅", "日式涮涮锅", "亚洲餐饮"],
        "positioning": "偏高价位、肉品品质导向、适合聚餐和体验型正餐",
        "customer_segments": ["火锅/涮涮锅顾客", "肉品品质敏感顾客", "聚餐顾客", "晚餐体验型顾客"],
        "triggers": ["shabu", "hot pot", "sukiyaki", "wagyu", "japanese", "ayce", "nabe", "nabemono"],
        "search_keywords": ["shabu shabu", "hot pot", "japanese hot pot", "sukiyaki", "wagyu hot pot"],
        "strong_terms": ["shabu", "hot pot", "sukiyaki", "nabemono", "nabe"],
        "adjacent_terms": ["japanese", "korean bbq", "yakiniku", "wagyu", "ayce"],
        "negative_terms": [
            "american",
            "steakhouse",
            "burger",
            "pizza",
            "italian",
            "mexican",
            "sandwich",
            "brewery",
            "bar",
            "cafe",
            "breakfast",
            "bakery",
            "wine bar",
        ],
    },
    "sushi": {
        "label": "日料/寿司",
        "cuisine": ["日料", "寿司"],
        "positioning": "日料正餐，顾客关注食材、服务节奏和价格感",
        "customer_segments": ["日料顾客", "约会/聚餐顾客", "生鲜品质敏感顾客"],
        "triggers": ["sushi", "japanese", "omakase", "sashimi", "izakaya"],
        "search_keywords": ["sushi", "japanese restaurant", "omakase", "izakaya"],
        "strong_terms": ["sushi", "omakase", "sashimi"],
        "adjacent_terms": ["japanese", "izakaya", "ramen"],
        "negative_terms": ["american", "burger", "pizza", "mexican", "steakhouse", "breakfast", "bakery"],
    },
    "korean_bbq": {
        "label": "韩式烤肉",
        "cuisine": ["韩餐", "烤肉"],
        "positioning": "体验型肉类正餐，适合聚餐，价格和肉品体验是核心",
        "customer_segments": ["烤肉顾客", "聚餐顾客", "肉品品质敏感顾客"],
        "triggers": ["korean bbq", "kbbq", "bbq", "yakiniku"],
        "search_keywords": ["korean bbq", "kbbq", "yakiniku", "bbq restaurant"],
        "strong_terms": ["korean bbq", "kbbq", "yakiniku"],
        "adjacent_terms": ["hot pot", "wagyu", "ayce"],
        "negative_terms": ["american", "burger", "pizza", "italian", "mexican", "breakfast", "bakery", "cafe"],
    },
}
GENERIC_NEGATIVE_TERMS = {
    "american classics",
    "steakhouse",
    "burger",
    "pizza",
    "italian",
    "mexican",
    "sandwich",
    "brewery",
    "bar",
    "cafe",
    "breakfast",
    "bakery",
}


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


def text_blob(*items: Any) -> str:
    parts: list[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            parts.extend(str(value) for value in item.values())
        elif isinstance(item, list):
            parts.extend(str(value) for value in item)
        else:
            parts.append(str(item))
    return normalize(" ".join(parts))


def similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    digits = "".join(char for char in str(value) if char.isdigit())
    return int(digits) if digits else None


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


def haversine_miles(left: dict[str, float] | None, right: dict[str, float] | None) -> float | None:
    if not left or not right:
        return None
    lat1 = math.radians(left["lat"])
    lat2 = math.radians(right["lat"])
    dlat = math.radians(right["lat"] - left["lat"])
    dlng = math.radians(right["lng"] - left["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return round(3958.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def compact_google(result: dict[str, Any], target_coordinates: dict[str, float] | None = None) -> dict[str, Any]:
    geometry = result.get("geometry", {}).get("location")
    coordinates = {"lat": geometry["lat"], "lng": geometry["lng"]} if geometry else None
    return {
        "status": "matched",
        "confidence": "high",
        "match_score": 1,
        "id": result.get("place_id"),
        "url": result.get("url"),
        "name": result.get("name"),
        "address": result.get("formatted_address") or result.get("vicinity"),
        "rating": result.get("rating"),
        "review_count": result.get("user_ratings_total"),
        "coordinates": coordinates,
        "business_status": result.get("business_status"),
        "distance_miles": haversine_miles(target_coordinates, coordinates),
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
        "review_count": as_int(result.get("reviews") or result.get("review_count")),
        "coordinates": coordinates if isinstance(coordinates, dict) else None,
        "business_status": None,
        "raw": result,
    }


def extract_yelp_categories(source: dict[str, Any] | None) -> list[str]:
    raw = (source or {}).get("raw") or {}
    categories = raw.get("categories") or []
    names: list[str] = []
    for category in categories:
        if isinstance(category, dict):
            title = category.get("title")
        else:
            title = category
        if title:
            names.append(str(title))
    return names


def infer_target_profile(source_profile: dict[str, Any], category_hint: str | None = None) -> dict[str, Any]:
    google = source_profile["sources"].get("google") or {}
    yelp = source_profile["sources"].get("yelp") or {}
    google_raw = google.get("raw") or {}
    yelp_raw = yelp.get("raw") or {}
    categories = extract_yelp_categories(yelp)
    price = yelp_raw.get("price")
    if not price and google_raw.get("price_level"):
        price = "$" * int(google_raw["price_level"])
    blob = text_blob(
        source_profile.get("target", {}).get("name"),
        google.get("name"),
        yelp.get("name"),
        google_raw.get("types"),
        categories,
        yelp_raw.get("snippet"),
        category_hint,
    )

    best_key = None
    best_hits = 0
    for key, profile in CUISINE_PROFILES.items():
        hits = sum(1 for term in profile["triggers"] if term in blob)
        if hits > best_hits:
            best_key = key
            best_hits = hits

    if best_key:
        profile = CUISINE_PROFILES[best_key]
        keywords = list(dict.fromkeys([category_hint, *profile["search_keywords"]] if category_hint else profile["search_keywords"]))
        return {
            "category_key": best_key,
            "cuisine": profile["cuisine"],
            "price_positioning": price,
            "occasion_positioning": profile["positioning"],
            "target_customers": profile["customer_segments"],
            "search_keywords": keywords,
            "strong_terms": profile["strong_terms"],
            "adjacent_terms": profile["adjacent_terms"],
            "negative_terms": profile["negative_terms"],
            "evidence": {
                "name": source_profile.get("target", {}).get("name"),
                "yelp_categories": categories,
                "yelp_price": yelp_raw.get("price"),
                "google_price_level": google_raw.get("price_level"),
            },
        }

    keyword = category_hint or "restaurant"
    return {
        "category_key": "generic_restaurant",
        "cuisine": [keyword],
        "price_positioning": price,
        "occasion_positioning": "附近同类餐饮，类别证据不足时先按老板给出的类别或 Google 类别搜索",
        "target_customers": ["附近餐饮顾客"],
        "search_keywords": [keyword],
        "strong_terms": [normalize(keyword)],
        "adjacent_terms": [],
        "negative_terms": list(GENERIC_NEGATIVE_TERMS),
        "evidence": {
            "name": source_profile.get("target", {}).get("name"),
            "yelp_categories": categories,
            "yelp_price": yelp_raw.get("price"),
            "google_price_level": google_raw.get("price_level"),
        },
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


def is_network_gap(reason: str | None) -> bool:
    lower = (reason or "").lower()
    network_markers = [
        "无法解析外部服务域名",
        "禁止外部网络连接",
        "可重试网络问题",
        "dns 不可用",
        "operation not permitted",
        "nodename nor servname",
        "name or service not known",
        "urlopen error",
        "timed out",
        "timeout",
        "temporary failure in name resolution",
    ]
    return any(marker in lower for marker in network_markers)


def blocked_competitor_profile(
    source_profile: dict[str, Any],
    radius_miles: float,
    desired_count: int,
    category_hint: str | None,
    reason: str,
) -> dict[str, Any]:
    target_google = source_profile["sources"]["google"]
    return {
        "target": {
            "name": source_profile["target"]["name"],
            "address": source_profile["target"]["address"],
            "google_place_id": target_google.get("id"),
        },
        "settings": {
            "radius_miles": radius_miles,
            "desired_count": desired_count,
            "category_hint": category_hint,
            "target_profile": None,
            "confirmation_mode": "pending",
        },
        "suggested_competitors": [],
        "approved_competitors": [],
        "owner_decisions": [],
        "data_gaps": [
            {
                "platform": "competitor_discovery",
                "restaurant_name": None,
                "reason": reason,
                "retryable": True,
            }
        ],
        "runtime_diagnostics": credential_status(),
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }


def load_source_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing source profile: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def search_google_competitors(
    target: dict[str, Any],
    radius_miles: float,
    search_keyword: str,
    api_key: str,
) -> list[dict[str, Any]]:
    target_source = target["sources"]["google"]
    target_coordinates = target_source.get("coordinates")
    keyword = search_keyword or "restaurant"
    params: dict[str, Any] = {"type": "restaurant", "keyword": keyword, "key": api_key}

    if target_coordinates:
        params.update(
            {
                "location": f"{target_coordinates['lat']},{target_coordinates['lng']}",
                "radius": int(radius_miles * METERS_PER_MILE),
            }
        )
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    else:
        params["query"] = f"{keyword} near {target['target']['address']}"
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    result = get_json(url, params)
    candidates = result.get("results", [])
    return [item for item in candidates if is_viable_candidate(item, target_source)]


def search_google_competitor_pool(
    target: dict[str, Any],
    radius_miles: float,
    target_profile: dict[str, Any],
    api_key: str,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for keyword in target_profile["search_keywords"]:
        keyword_results = search_google_competitors(target, radius_miles, keyword, api_key)
        for item in keyword_results[:MAX_RAW_CANDIDATES_PER_KEYWORD]:
            key = item.get("place_id") or normalize(item.get("name"))
            if not key or key in seen:
                continue
            seen.add(key)
            item = dict(item)
            item["_matched_search_keyword"] = keyword
            results.append(item)
            if len(results) >= MAX_RAW_CANDIDATES_TOTAL:
                return results
    return results


def is_viable_candidate(candidate: dict[str, Any], target_google: dict[str, Any]) -> bool:
    if candidate.get("place_id") and candidate.get("place_id") == target_google.get("id"):
        return False
    if similarity(candidate.get("name"), target_google.get("name")) > 0.92:
        return False
    if candidate.get("business_status") and candidate.get("business_status") != "OPERATIONAL":
        return False
    types = set(candidate.get("types") or [])
    if types & BLOCKED_TYPES:
        return False
    if types and not (types & FOOD_TYPES):
        return False
    return True


def fetch_google_details(place_id: str, api_key: str) -> dict[str, Any]:
    details = get_json(
        "https://maps.googleapis.com/maps/api/place/details/json",
        {
            "place_id": place_id,
            "fields": "place_id,name,formatted_address,geometry,business_status,rating,user_ratings_total,url,website,formatted_phone_number,types,price_level",
            "key": api_key,
        },
    )
    return details.get("result") or {}


def discover_yelp(name: str, address: str, api_key: str | None) -> dict[str, Any]:
    if not api_key:
        return missing_source("Missing SERPAPI_API_KEY.")
    try:
        result = get_json(
            "https://serpapi.com/search.json",
            {
                "engine": "yelp",
                "find_desc": name,
                "find_loc": address,
                "api_key": api_key,
            },
        )
    except Exception as exc:
        return missing_source(provider_error("SerpApi Yelp", exc))
    candidates = result.get("organic_results") or result.get("results") or []
    if not candidates:
        return missing_source(result.get("error") or "No Yelp candidates returned through SerpApi.")
    best = max(candidates, key=lambda item: similarity(name, item.get("name") or item.get("title")) + similarity(address, str(item)))
    return compact_yelp(best, name, address)


def price_to_level(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    if "$" in text:
        return text.count("$")
    return as_int(value)


def candidate_relevance(
    google: dict[str, Any],
    yelp: dict[str, Any],
    target_profile: dict[str, Any],
    matched_keyword: str | None = None,
) -> tuple[float, list[str], list[str]]:
    raw_google = google.get("raw") or {}
    raw_yelp = yelp.get("raw") or {}
    categories = extract_yelp_categories(yelp)
    blob = text_blob(
        google.get("name"),
        google.get("address"),
        raw_google.get("types"),
        raw_google.get("website"),
        yelp.get("name"),
        categories,
        raw_yelp.get("snippet"),
    )
    strong_hits = [term for term in target_profile["strong_terms"] if term and term in blob]
    adjacent_hits = [term for term in target_profile["adjacent_terms"] if term and term in blob]
    negative_hits = [term for term in target_profile["negative_terms"] if term and term in blob]
    score = 0.18
    score += min(0.58, len(strong_hits) * 0.29)
    score += min(0.24, len(adjacent_hits) * 0.12)
    score -= min(0.45, len(negative_hits) * 0.15)
    score = max(0, min(1, score))

    reasons: list[str] = []
    if strong_hits:
        reasons.append(f"同类关键词：{', '.join(strong_hits[:3])}")
    if adjacent_hits and not strong_hits:
        reasons.append(f"相邻餐饮场景：{', '.join(adjacent_hits[:3])}")
    if categories:
        reasons.append(f"Yelp 类别：{', '.join(categories[:3])}")
    if negative_hits:
        reasons.append(f"相关性扣分：{', '.join(negative_hits[:3])}")
    if not reasons:
        reasons.append("类别证据有限")
    return round(score, 3), reasons, negative_hits


def shortlist_raw_candidates(
    candidates: list[dict[str, Any]],
    target_coordinates: dict[str, float] | None,
    target_profile: dict[str, Any],
    desired_count: int,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        google = compact_google(candidate, target_coordinates)
        relevance_score, _, negative_hits = candidate_relevance(google, missing_source("Yelp not checked during prefilter."), target_profile)
        distance = google.get("distance_miles")
        distance_score = max(0, 1 - ((distance or DEFAULT_RADIUS_MILES) / DEFAULT_RADIUS_MILES))
        review_count = google.get("review_count") or 0
        review_score = min(1, math.log10(review_count + 1) / 3)
        score = (relevance_score * 0.58) + (distance_score * 0.24) + (review_score * 0.18)
        if relevance_score < 0.2 and negative_hits:
            score *= 0.2
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    limit = max(desired_count * 4, min(MAX_DETAIL_CANDIDATES, desired_count + 8))
    return [candidate for _, candidate in scored[:limit]]


def price_fit_score(target_profile: dict[str, Any], google: dict[str, Any], yelp: dict[str, Any]) -> tuple[float, str | None]:
    target_price = price_to_level(target_profile.get("price_positioning"))
    candidate_price = price_to_level((yelp.get("raw") or {}).get("price") or (google.get("raw") or {}).get("price_level"))
    if target_price is None or candidate_price is None:
        return 0.55, None
    diff = abs(target_price - candidate_price)
    if diff == 0:
        return 1.0, f"价位相同（{'$' * candidate_price}）"
    if diff == 1:
        return 0.72, f"价位接近（目标 {'$' * target_price}，竞品 {'$' * candidate_price}）"
    return 0.25, f"价位差距较大（目标 {'$' * target_price}，竞品 {'$' * candidate_price}）"


def rank_candidate(
    candidate: dict[str, Any],
    target_coordinates: dict[str, float] | None,
    target_profile: dict[str, Any],
    yelp: dict[str, Any],
    matched_keyword: str | None = None,
) -> tuple[float, str, float | None, float]:
    coordinates = candidate.get("coordinates")
    distance = haversine_miles(target_coordinates, coordinates)
    distance_score = max(0, 1 - ((distance or DEFAULT_RADIUS_MILES) / DEFAULT_RADIUS_MILES))
    rating = candidate.get("rating") or 0
    review_count = candidate.get("review_count") or 0
    review_score = min(1, math.log10(review_count + 1) / 3)
    rating_score = min(1, rating / 5)
    relevance_score, relevance_reasons, negative_hits = candidate_relevance(candidate, yelp, target_profile, matched_keyword)
    price_score, price_reason = price_fit_score(target_profile, candidate, yelp)
    score = round(
        (relevance_score * 0.42)
        + (distance_score * 0.23)
        + (review_score * 0.17)
        + (rating_score * 0.1)
        + (price_score * 0.08),
        3,
    )
    if relevance_score < 0.3 and negative_hits:
        score = round(score * 0.55, 3)
    reason_parts = []
    reason_parts.extend(relevance_reasons[:2])
    if price_reason:
        reason_parts.append(price_reason)
    if distance is not None:
        reason_parts.append(f"{distance} miles away")
    if review_count:
        reason_parts.append(f"{review_count} Google reviews")
    if rating:
        reason_parts.append(f"{rating} Google rating")
    return score, ", ".join(reason_parts) or "Nearby restaurant candidate", distance, relevance_score


def build_competitors(
    source_profile: dict[str, Any],
    radius_miles: float,
    desired_count: int,
    category_hint: str | None,
    auto_select: bool,
) -> dict[str, Any]:
    load_dotenv_if_needed()
    google_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    serpapi_key = os.environ.get("SERPAPI_API_KEY")
    data_gaps: list[dict[str, Any]] = []

    target_google = source_profile["sources"]["google"]
    target_coordinates = target_google.get("coordinates")
    target_profile = infer_target_profile(source_profile, category_hint)
    target_google_reason = (target_google.get("raw") or {}).get("reason")
    if target_google.get("status") != "matched" and is_network_gap(target_google_reason):
        return blocked_competitor_profile(
            source_profile,
            radius_miles,
            desired_count,
            category_hint,
            f"竞品发现依赖 Google Places 地点匹配，但上一步网络访问失败：{target_google_reason}",
        )

    if not google_key:
        return blocked_competitor_profile(
            source_profile,
            radius_miles,
            desired_count,
            category_hint,
            "缺少 GOOGLE_PLACES_API_KEY，暂时无法自动发现附近竞品。",
        )

    try:
        raw_candidates = search_google_competitor_pool(source_profile, radius_miles, target_profile, google_key)
    except Exception as exc:
        return blocked_competitor_profile(
            source_profile,
            radius_miles,
            desired_count,
            category_hint,
            provider_error("Google Places 竞品发现", exc),
        )
    raw_candidates = shortlist_raw_candidates(raw_candidates, target_coordinates, target_profile, desired_count)
    competitors: list[dict[str, Any]] = []

    for raw in raw_candidates:
        try:
            details = fetch_google_details(raw.get("place_id"), google_key) if raw.get("place_id") else raw
        except Exception as exc:
            data_gaps.append(
                {
                    "platform": "google",
                    "restaurant_name": raw.get("name"),
                    "reason": provider_error("Google Places 竞品详情", exc),
                    "retryable": True,
                }
            )
            details = raw
        google = compact_google(details or raw, target_coordinates)
        yelp = discover_yelp(google.get("name") or "", google.get("address") or source_profile["target"]["address"], serpapi_key)
        score, reason, distance, relevance_score = rank_candidate(
            google,
            target_coordinates,
            target_profile,
            yelp,
            raw.get("_matched_search_keyword"),
        )
        if relevance_score < 0.25:
            data_gaps.append(
                {
                    "platform": "competitor_discovery",
                    "restaurant_name": google.get("name"),
                    "reason": "候选餐厅与目标餐厅画像相关性较低，已降权为备选或排除。",
                    "retryable": False,
                }
            )
            continue
        if yelp["status"] != "matched":
            data_gaps.append(
                {
                    "platform": "yelp",
                    "restaurant_name": google.get("name"),
                    "reason": yelp["raw"].get("reason", "Yelp 竞品匹配需要重试或人工确认。"),
                    "retryable": True,
                }
            )
        competitors.append(
            {
                "rank": 0,
                "rank_score": score,
                "status": "suggested",
                "distance_miles": distance,
                "selection_reason": reason,
                "google": without_distance(google),
                "yelp": yelp,
            }
        )
        time.sleep(0.2)

    competitors.sort(key=lambda item: item["rank_score"], reverse=True)
    for index, competitor in enumerate(competitors, start=1):
        competitor["rank"] = index
        if index > desired_count:
            competitor["status"] = "alternate"

    selected = [dict(item, status="approved") for item in competitors[:desired_count]] if auto_select else []
    decisions = (
        [
            {"action": "auto_selected", "restaurant_name": item["google"].get("name") or "Unknown", "note": "Top automatic competitor candidate."}
            for item in selected
        ]
        if auto_select
        else []
    )

    if not competitors:
        data_gaps.append(
            {
                "platform": "competitor_discovery",
                "restaurant_name": None,
                "reason": "Google Places 暂时没有返回可用的附近餐饮竞品。",
                "retryable": True,
            }
        )

    return {
        "target": {
            "name": source_profile["target"]["name"],
            "address": source_profile["target"]["address"],
            "google_place_id": target_google.get("id"),
        },
        "settings": {
            "radius_miles": radius_miles,
            "desired_count": desired_count,
            "category_hint": category_hint,
            "target_profile": target_profile,
            "confirmation_mode": "auto_selected" if auto_select else "pending",
        },
        "suggested_competitors": competitors,
        "approved_competitors": selected,
        "owner_decisions": decisions,
        "data_gaps": data_gaps,
        "runtime_diagnostics": credential_status(),
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }


def without_distance(source: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(source)
    cleaned.pop("distance_miles", None)
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-profile", default=str(DEFAULT_SOURCE_PROFILE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--radius-miles", type=float, default=DEFAULT_RADIUS_MILES)
    parser.add_argument("--desired-count", type=int, default=DEFAULT_DESIRED_COUNT)
    parser.add_argument("--category-hint")
    parser.add_argument("--auto-select", action="store_true", help="Approve the top candidates without owner edits.")
    args = parser.parse_args()

    source_profile = load_source_profile(Path(args.source_profile))
    competitors = build_competitors(
        source_profile=source_profile,
        radius_miles=args.radius_miles,
        desired_count=args.desired_count,
        category_hint=args.category_hint,
        auto_select=args.auto_select,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(competitors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
