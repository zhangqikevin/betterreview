---
name: review-response-coaching
description: Generate owner-ready public reply drafts and internal handling guidance for Better Review target-restaurant reviews.
---

# Review Response Coaching

Use this skill after `review-ingestion-storage` has created `data/review-store.json`. Use `data/reputation-report.json` when available to keep reply guidance aligned with the latest reputation analysis.

The goal is to help a restaurant owner respond to new Google Maps and Yelp reviews without sounding generic. The skill creates public reply drafts only for the target restaurant. Competitor reviews are summarized as operational signals, but never receive reply drafts.

## Inputs

Use local data first:

- `data/review-store.json` from `review-ingestion-storage`.
- Optional `data/reputation-report.json` from `reputation-analysis-reporting`.
- Optional mode: `daily`, `weekly`, or `ad-hoc`.
- Optional date window for focused response coaching.

Do not ask the owner to paste reviews manually. If review text is unavailable, generate only a cautious rating-based suggestion or mark that the review should be revisited after the next scan.

## Workflow

1. Load the normalized review store.
2. Load the latest reputation report if it exists.
3. Select new reviews from `new_review_keys`; if none are present and a date window is provided, select reviews in that window.
4. Separate target restaurant reviews from competitor reviews.
5. For each target review:
   - classify rating as positive, neutral, negative, or unknown
   - infer practical themes from visible text
   - identify whether the review needs owner follow-up before posting
   - write a concise public reply draft in Chinese
   - write internal handling guidance when the review is negative, operational, or missing text
6. For competitor reviews:
   - summarize platform, restaurant, rating, date, and visible text
   - extract business signals only
   - do not generate reply drafts
7. Include data gaps from ingestion and any missing-text notes from the selected reviews.
8. Save `data/response-suggestions.json` for daily alerts, weekly reports, and future owner review.

## Reply Rules

- Reply drafts must be in Chinese unless the owner has explicitly requested another language.
- Use the platform and reviewer name when available, but avoid over-personalization.
- Keep positive-review replies warm, specific, and short.
- For negative reviews, acknowledge the issue, apologize without admitting unverifiable facts, invite direct contact when appropriate, and mention one concrete next step.
- For neutral reviews, thank the guest and invite a specific improvement opportunity.
- Never invent details that are not present in the review, store profile, or report.
- If review text is missing, do not pretend to know the complaint or praise. Mention that the visible data only shows the platform and rating.
- Do not offer refunds, discounts, or compensation as a public promise unless the owner has configured that policy elsewhere.
- Do not produce competitor reply drafts.

## Output

The saved suggestions must include:

- Run metadata: mode, generated time, input store timestamp, selected review count, and optional date window.
- Target review suggestions with public reply draft, tone, themes, confidence, and internal guidance.
- Competitor review signals without reply drafts.
- Data gaps and missing-text follow-up notes.
- Reuse notes that explain whether `data/reputation-report.json` influenced the advice.

Use `scripts/generate_response_suggestions.py` when command-line execution is available. It writes suggestions to `data/response-suggestions.json`.

## Owner-Facing Behavior

Explain suggestions in practical owner language:

- Which reviews need a reply now.
- Which replies can be posted as-is.
- Which reviews need manager or staff follow-up before posting.
- Which competitor comments reveal useful service, menu, price, wait-time, or operations signals.
- What data was unavailable and will be retried by future scans.
