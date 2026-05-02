#!/usr/bin/env python3
"""Generate a structured Better Review reputation report.

Usage:
  python skills/reputation-analysis-reporting/scripts/generate_report.py \
    --mode initial
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REVIEW_STORE = ROOT / "data" / "review-store.json"
DEFAULT_OUTPUT = ROOT / "data" / "reputation-report.json"
PLATFORMS = ("google", "yelp")
THEME_KEYWORDS = {
    "service": ("service", "server", "waiter", "waitress", "host", "friendly", "rude", "attentive"),
    "food": ("food", "dish", "meal", "taste", "flavor", "fresh", "cold", "overcooked", "undercooked", "portion"),
    "atmosphere": ("atmosphere", "ambience", "ambiance", "music", "decor", "noise", "cozy", "crowded"),
    "price": ("price", "value", "expensive", "cheap", "worth", "bill", "cost"),
    "wait time": ("wait", "line", "slow", "fast", "reservation", "seated", "delay"),
    "delivery/takeout": ("delivery", "takeout", "to go", "pickup", "driver", "order online"),
    "cleanliness": ("clean", "dirty", "sanitary", "bathroom", "restroom", "hygiene"),
    "staff": ("staff", "manager", "employee", "team", "cashier", "chef"),
    "operations": ("order", "wrong", "missing", "refund", "menu", "hours", "closed", "busy"),
}
THEME_LABELS = {
    "service": "服务",
    "food": "菜品",
    "atmosphere": "环境",
    "price": "价格",
    "wait time": "等位/出餐速度",
    "delivery/takeout": "外卖/自取",
    "cleanliness": "卫生",
    "staff": "员工表现",
    "operations": "运营流程",
    "general experience": "整体体验",
}
POSITIVE_WORDS = ("great", "excellent", "amazing", "best", "friendly", "fresh", "delicious", "fast", "clean", "love", "perfect")
NEGATIVE_WORDS = ("bad", "terrible", "awful", "rude", "slow", "cold", "dirty", "wrong", "missing", "expensive", "wait", "disappointed")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def rating_bucket(rating: float | None) -> str:
    if rating is None:
        return "unknown"
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "mixed"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def in_window(review: dict[str, Any], start: str | None, end: str | None) -> bool:
    if not start and not end:
        return True
    published = parse_date(review.get("published_at")) or parse_date(review.get("first_seen_at"))
    if not published:
        return True
    start_dt = parse_date(start)
    end_dt = parse_date(end)
    if start_dt and published < start_dt:
        return False
    if end_dt and published > end_dt:
        return False
    return True


def latest_snapshots(store: dict[str, Any]) -> dict[tuple[str | None, str], dict[str, Any]]:
    snapshots: dict[tuple[str | None, str], dict[str, Any]] = {}
    source_to_restaurant: dict[tuple[str | None, str], str] = {}
    for review in store.get("reviews", []):
        source_to_restaurant[(review.get("source_id"), review["platform"])] = review["restaurant_key"]
    for snapshot in store.get("platform_snapshots", []):
        key = (snapshot.get("source_id"), snapshot["platform"])
        restaurant_key = source_to_restaurant.get(key)
        if restaurant_key:
            snapshots[(restaurant_key, snapshot["platform"])] = snapshot
    ordered_restaurants = store.get("restaurants", [])
    ordered_snapshots = store.get("platform_snapshots", [])
    expected_count = len(ordered_restaurants) * len(PLATFORMS)
    if ordered_restaurants and len(ordered_snapshots) >= expected_count:
        index = 0
        for restaurant in ordered_restaurants:
            for platform in PLATFORMS:
                snapshot = ordered_snapshots[index]
                index += 1
                if snapshot.get("platform") == platform:
                    snapshots.setdefault((restaurant["restaurant_key"], platform), snapshot)
    return snapshots


def review_themes(review: dict[str, Any]) -> list[str]:
    text = (review.get("text") or "").lower()
    return [theme for theme, keywords in THEME_KEYWORDS.items() if any(keyword in text for keyword in keywords)]


def theme_label(theme: str) -> str:
    return THEME_LABELS.get(theme, theme)


def sentiment(review: dict[str, Any]) -> str:
    text = (review.get("text") or "").lower()
    rating_sentiment = rating_bucket(review.get("rating"))
    positive_hits = sum(1 for word in POSITIVE_WORDS if word in text)
    negative_hits = sum(1 for word in NEGATIVE_WORDS if word in text)
    if negative_hits > positive_hits:
        return "negative"
    if positive_hits > negative_hits:
        return "positive"
    return rating_sentiment


def platform_report(platform: str, reviews: list[dict[str, Any]], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    platform_reviews = [review for review in reviews if review["platform"] == platform]
    visible_text = [review for review in platform_reviews if review.get("text")]
    avg = average([review["rating"] for review in platform_reviews if isinstance(review.get("rating"), (int, float))])
    snapshot_rating = snapshot.get("rating") if snapshot else None
    snapshot_review_count = snapshot.get("review_count") if snapshot else None
    platform_name = "Google Maps" if platform == "google" else "Yelp"
    if platform_reviews:
        summary = f"{platform_name} 在本报告窗口内有 {len(platform_reviews)} 条可分析评论。"
    elif snapshot_review_count is not None:
        summary = f"{platform_name} 评论正文覆盖不足，本次使用评分和评论数快照做降级判断。"
    else:
        summary = f"{platform_name} 暂时没有可用评论数据。"
    return {
        "platform": platform,
        "review_count": len(platform_reviews),
        "visible_text_reviews": len(visible_text),
        "average_rating": avg,
        "snapshot_rating": snapshot_rating,
        "snapshot_review_count": snapshot_review_count,
        "summary": summary,
    }


def top_theme_phrases(reviews: list[dict[str, Any]], wanted: str) -> list[str]:
    phrases = []
    for review in reviews:
        if wanted in review_themes(review) and review.get("text"):
            phrases.append(f"{wanted}: {sentiment(review)} signal from {review['platform']}")
    return phrases[:3]


def restaurant_report(
    restaurant: dict[str, Any],
    reviews: list[dict[str, Any]],
    snapshots: dict[tuple[str | None, str], dict[str, Any]],
) -> dict[str, Any]:
    restaurant_reviews = [review for review in reviews if review["restaurant_key"] == restaurant["restaurant_key"]]
    ratings = [review["rating"] for review in restaurant_reviews if isinstance(review.get("rating"), (int, float))]
    visible = [review for review in restaurant_reviews if review.get("text")]
    theme_counts = Counter(theme for review in visible for theme in review_themes(review))
    negative_theme_counts = Counter(theme for review in visible if sentiment(review) == "negative" for theme in review_themes(review))
    positive_theme_counts = Counter(theme for review in visible if sentiment(review) == "positive" for theme in review_themes(review))
    platform_items = [
        platform_report(platform, restaurant_reviews, snapshots.get((restaurant["restaurant_key"], platform)))
        for platform in PLATFORMS
    ]
    if visible:
        top_themes = "、".join(theme_label(theme) for theme, _count in theme_counts.most_common(3)) or "整体体验"
        summary = f"{restaurant['name']} 本次纳入 {len(restaurant_reviews)} 条评论；可见正文最常提到：{top_themes}。"
    else:
        summary = f"{restaurant['name']} 的可见评论正文有限，本次主要依赖评分和评论数快照。"
    strengths = [f"{theme_label(theme)}维度有正面顾客信号。" for theme, _count in positive_theme_counts.most_common(3)]
    complaints = [f"{theme_label(theme)}维度出现投诉模式。" for theme, _count in negative_theme_counts.most_common(3)]
    risks = [f"持续关注{theme_label(theme)}；重复负面提及会影响新客转化。" for theme, _count in negative_theme_counts.most_common(2)]
    opportunities = [f"用{theme_label(theme)}反馈优化运营细节和本地定位。" for theme, _count in theme_counts.most_common(3)]
    return {
        "restaurant_key": restaurant["restaurant_key"],
        "role": restaurant["role"],
        "name": restaurant["name"],
        "review_count": len(restaurant_reviews),
        "visible_text_reviews": len(visible),
        "average_rating": average(ratings),
        "platforms": platform_items,
        "summary": summary,
        "strengths": strengths,
        "complaints": complaints,
        "risks": risks,
        "opportunities": opportunities,
    }


def theme_reports(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        if not review.get("text"):
            continue
        themes = review_themes(review) or ["general experience"]
        for theme in themes:
            grouped[theme].append(review)
    reports = []
    for theme, items in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True):
        positive = [review for review in items if sentiment(review) == "positive"]
        negative = [review for review in items if sentiment(review) == "negative"]
        restaurants = sorted({review["restaurant_name"] for review in items})
        reports.append(
            {
                "theme": theme,
                "mentions": len(items),
                "positive_mentions": len(positive),
                "negative_mentions": len(negative),
                "restaurants": restaurants,
                "summary": f"{theme_label(theme)}出现在 {len(items)} 条可见评论中，覆盖 {len(restaurants)} 家餐厅。",
            }
        )
    return reports


def recommendations(target: dict[str, Any], themes: list[dict[str, Any]], fallback_used: bool) -> list[dict[str, Any]]:
    items = []
    for theme in themes:
        if theme["negative_mentions"] > 0:
            priority = "high" if theme["negative_mentions"] >= 3 else "medium"
            items.append(
                {
                    "priority": priority,
                    "area": theme["theme"],
                    "action": f"复盘近期{theme_label(theme['theme'])}相关投诉，并指定一名运营负责人跟进。",
                    "reason": theme["summary"],
                }
            )
    if target["visible_text_reviews"] == 0 or fallback_used:
        items.append(
            {
                "priority": "medium",
                "area": "数据覆盖",
                "action": "继续自动扫描；当前判断先以评分和评论数变化为主。",
                "reason": "当前数据里的可见评论正文覆盖不足。",
            }
        )
    if not items:
        items.append(
            {
                "priority": "low",
                "area": "口碑维护",
                "action": "继续监控新评论，并保持当前正面表现。",
                "reason": "本报告窗口内没有看到重复出现的负面主题。",
            }
        )
    return items[:8]


def build_report(store: dict[str, Any], mode: str, start: str | None, end: str | None) -> dict[str, Any]:
    generated_at = utc_now()
    reviews = [review for review in store.get("reviews", []) if in_window(review, start, end)]
    restaurants = store.get("restaurants", [])
    snapshots = latest_snapshots(store)
    target_restaurant = next((item for item in restaurants if item["role"] == "target"), restaurants[0] if restaurants else {"restaurant_key": "target", "role": "target", "name": "Target restaurant"})
    target = restaurant_report(target_restaurant, reviews, snapshots)
    competitors = [restaurant_report(item, reviews, snapshots) for item in restaurants if item["role"] == "competitor"]
    themes = theme_reports(reviews)
    visible_text_reviews = len([review for review in reviews if review.get("text")])
    fallback_used = visible_text_reviews == 0 and bool(store.get("platform_snapshots") or store.get("data_gaps"))
    platforms = sorted({review["platform"] for review in reviews} | {snapshot["platform"] for snapshot in store.get("platform_snapshots", [])})
    return {
        "version": "0.1.0",
        "report_id": f"{mode}:{stable_hash(generated_at)}",
        "mode": mode,
        "generated_at": generated_at,
        "input_store_last_checked_at": store.get("last_checked_at"),
        "date_window": {"start": start, "end": end} if start or end else None,
        "coverage": {
            "restaurants": len(restaurants),
            "reviews": len(reviews),
            "visible_text_reviews": visible_text_reviews,
            "platforms": platforms,
            "fallback_used": fallback_used,
        },
        "target": target,
        "platform_comparison": target["platforms"],
        "themes": themes,
        "competitors": competitors,
        "recommendations": recommendations(target, themes, fallback_used),
        "data_gaps": store.get("data_gaps", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-store", default=str(DEFAULT_REVIEW_STORE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", choices=["initial", "weekly", "ad-hoc"], default="initial")
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()

    store = load_json(Path(args.review_store))
    report = build_report(store, args.mode, args.start, args.end)
    write_json(Path(args.output), report)
    print(f"Wrote {args.output}")
    print(f"Reviews analyzed: {report['coverage']['reviews']}")
    print(f"Visible text reviews: {report['coverage']['visible_text_reviews']}")
    print(f"Recommendations: {len(report['recommendations'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
