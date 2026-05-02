#!/usr/bin/env python3
"""Generate Better Review reply suggestions and competitor review signals.

Usage:
  python skills/review-response-coaching/scripts/generate_response_suggestions.py \
    --mode daily
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REVIEW_STORE = ROOT / "data" / "review-store.json"
DEFAULT_REPORT = ROOT / "data" / "reputation-report.json"
DEFAULT_OUTPUT = ROOT / "data" / "response-suggestions.json"

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


def load_json(path: Path, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing required input: {path}")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def review_text(review: dict[str, Any]) -> str:
    return (review.get("text") or "").strip()


def review_themes(review: dict[str, Any]) -> list[str]:
    text = review_text(review).lower()
    themes = [theme for theme, keywords in THEME_KEYWORDS.items() if any(keyword in text for keyword in keywords)]
    return themes or (["general experience"] if text else [])


def theme_label(theme: str) -> str:
    return THEME_LABELS.get(theme, theme)


def theme_phrase(themes: list[str], fallback: str = "顾客体验") -> str:
    return "、".join(theme_label(theme) for theme in themes[:2]) or fallback


def sentiment(review: dict[str, Any]) -> str:
    rating = review.get("rating")
    text = review_text(review).lower()
    positive_hits = sum(1 for word in POSITIVE_WORDS if word in text)
    negative_hits = sum(1 for word in NEGATIVE_WORDS if word in text)
    if negative_hits > positive_hits:
        return "negative"
    if positive_hits > negative_hits:
        return "positive"
    if isinstance(rating, (int, float)):
        if rating >= 4:
            return "positive"
        if rating <= 2:
            return "negative"
        return "neutral"
    return "unknown"


def select_reviews(store: dict[str, Any], start: str | None, end: str | None) -> tuple[list[dict[str, Any]], str]:
    reviews = store.get("reviews", [])
    by_key = {review["review_key"]: review for review in reviews}
    selected = [by_key[key] for key in store.get("new_review_keys", []) if key in by_key]
    if selected:
        return selected, "new_review_keys"
    windowed = [review for review in reviews if in_window(review, start, end)]
    if start or end:
        return windowed, "date_window"
    return windowed, "all_reviews"


def rating_label(rating: float | None) -> str:
    if rating is None:
        return "未显示星级"
    if rating >= 4:
        return f"{rating:g} 星好评"
    if rating <= 2:
        return f"{rating:g} 星差评"
    return f"{rating:g} 星中评"


def target_reply(review: dict[str, Any], themes: list[str], item_sentiment: str) -> tuple[str | None, str, str, list[str], bool, list[str]]:
    rating = review.get("rating")
    text = review_text(review)
    author = review.get("author") or "您好"
    platform = "Google Maps" if review.get("platform") == "google" else "Yelp"
    notes: list[str] = []
    guidance: list[str] = []

    if not text:
        draft = f"{author}，感谢您在 {platform} 上留下反馈。我们目前只能看到{rating_label(rating)}，暂时看不到具体内容；我们会继续关注并尽快根据完整信息跟进。"
        guidance.append("等待下次自动扫描补全评论正文；正文可见前不要假设具体投诉或表扬点。")
        if isinstance(rating, (int, float)) and rating <= 3:
            guidance.append("如果平台后台能看到完整评论，建议先由经理核查后再公开回复。")
        notes.append("评论正文不可见；草稿只基于平台和星级生成。")
        return draft, "谨慎、克制", "low", guidance, True, notes

    public_theme_phrase = theme_phrase(themes, "用餐体验")
    if item_sentiment == "negative":
        draft = f"{author}，感谢您告诉我们这次体验中的问题。很抱歉这次在{public_theme_phrase}上没有达到期待，我们会把这条反馈交给当天团队复盘，并尽快改进。也欢迎您通过店内电话或私信联系我们，方便我们进一步了解情况。"
        guidance.extend(
            [
                "先核查评论日期、班次、订单或预订记录，再决定是否需要私下联系顾客。",
                "把涉及的主题交给对应负责人复盘，避免公开承诺无法确认的补偿。",
            ]
        )
        return draft, "负责、真诚、不过度辩解", "medium", guidance, True, notes
    if item_sentiment == "neutral":
        draft = f"{author}，谢谢您的反馈。我们很重视您提到的{public_theme_phrase}，会继续调整细节，希望下次能给您更稳定、更满意的体验。"
        guidance.append("把中评作为改进线索处理；如评论中有具体问题，安排对应负责人跟进。")
        return draft, "感谢、开放、具体", "medium", guidance, False, notes

    draft = f"{author}，谢谢您的支持和分享。很高兴您喜欢我们的{public_theme_phrase}，我们会继续保持，也期待下次再见到您。"
    guidance.append("好评可直接回复；如提到具体菜品或员工，可在发布前补充一句更个性化的感谢。")
    return draft, "温暖、简洁、不模板化", "high", guidance, False, notes


def target_suggestion(review: dict[str, Any]) -> dict[str, Any]:
    themes = review_themes(review)
    item_sentiment = sentiment(review)
    draft, tone, confidence, guidance, needs_review, notes = target_reply(review, themes, item_sentiment)
    return {
        "review_key": review["review_key"],
        "platform": review["platform"],
        "restaurant_name": review["restaurant_name"],
        "author": review.get("author"),
        "rating": review.get("rating"),
        "published_at": review.get("published_at"),
        "relative_date": review.get("relative_date"),
        "text_available": bool(review_text(review)),
        "sentiment": item_sentiment,
        "themes": themes,
        "tone": tone,
        "confidence": confidence,
        "public_reply_draft": draft,
        "internal_guidance": guidance,
        "needs_owner_review": needs_review,
        "reasoning_notes": notes,
    }


def competitor_signal(review: dict[str, Any]) -> dict[str, Any]:
    themes = review_themes(review)
    item_sentiment = sentiment(review)
    if not review_text(review):
        signal = f"{review['restaurant_name']} 在 {review['platform']} 出现一条{rating_label(review.get('rating'))}信号，但评论正文暂时不可见。"
    elif item_sentiment == "negative":
        signal = f"关注竞品在{theme_phrase(themes)}上的短板。"
    elif item_sentiment == "positive":
        signal = f"竞品在{theme_phrase(themes)}上获得表扬，可能代表本商圈顾客的基础期待。"
    else:
        signal = f"竞品中性反馈提到{theme_phrase(themes)}。"
    return {
        "review_key": review["review_key"],
        "platform": review["platform"],
        "restaurant_name": review["restaurant_name"],
        "rating": review.get("rating"),
        "published_at": review.get("published_at"),
        "relative_date": review.get("relative_date"),
        "text_available": bool(review_text(review)),
        "sentiment": item_sentiment,
        "themes": themes,
        "signal": signal,
    }


def report_reuse_notes(report: dict[str, Any] | None) -> list[str]:
    if not report:
        return ["没有可用的口碑报告；本次建议只使用 review-store 数据。"]
    notes = [f"已参考口碑报告 {report.get('report_id', 'unknown')}，生成时间 {report.get('generated_at', 'unknown')}。"]
    recommendations = report.get("recommendations", [])
    if recommendations:
        areas = "、".join(item.get("area", "unknown") for item in recommendations[:3])
        notes.append(f"已参考当前报告的优先事项：{areas}。")
    if report.get("coverage", {}).get("fallback_used"):
        notes.append("最近一次口碑报告因可见评论正文不足使用了降级数据。")
    return notes


def missing_text_gaps(reviews: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    gaps = []
    for review in reviews:
        if review_text(review):
            continue
        gaps.append(
            {
                "platform": review["platform"],
                "restaurant_key": review["restaurant_key"],
                "restaurant_name": review["restaurant_name"],
                "reason": f"选中的评论 {review['review_key']} 只有评分元数据，暂时没有可见正文。",
                "retryable": True,
                "recorded_at": generated_at,
            }
        )
    return gaps


def build_suggestions(
    store: dict[str, Any],
    report: dict[str, Any] | None,
    mode: str,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    generated_at = utc_now()
    selected, selection_source = select_reviews(store, start, end)
    target_reviews = [review for review in selected if review.get("restaurant_role") == "target"]
    competitor_reviews = [review for review in selected if review.get("restaurant_role") == "competitor"]
    target_items = [target_suggestion(review) for review in target_reviews]
    competitor_items = [competitor_signal(review) for review in competitor_reviews]
    data_gaps = list(store.get("data_gaps", [])) + missing_text_gaps(selected, generated_at)
    return {
        "version": "0.1.0",
        "suggestion_run_id": f"{mode}:{stable_hash(generated_at)}",
        "mode": mode,
        "generated_at": generated_at,
        "input_store_last_checked_at": store.get("last_checked_at"),
        "date_window": {"start": start, "end": end} if start or end else None,
        "selection": {
            "selected_review_count": len(selected),
            "target_review_count": len(target_reviews),
            "competitor_review_count": len(competitor_reviews),
            "source": selection_source,
        },
        "target_review_suggestions": target_items,
        "competitor_review_signals": competitor_items,
        "data_gaps": data_gaps,
        "reuse_notes": report_reuse_notes(report),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-store", default=str(DEFAULT_REVIEW_STORE))
    parser.add_argument("--reputation-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", choices=["daily", "weekly", "ad-hoc"], default="daily")
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()

    store = load_json(Path(args.review_store), required=True)
    report = load_json(Path(args.reputation_report), required=False)
    suggestions = build_suggestions(store, report, args.mode, args.start, args.end)
    write_json(Path(args.output), suggestions)
    print(f"Wrote {args.output}")
    print(f"Selected reviews: {suggestions['selection']['selected_review_count']}")
    print(f"Target reply suggestions: {len(suggestions['target_review_suggestions'])}")
    print(f"Competitor signals: {len(suggestions['competitor_review_signals'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
