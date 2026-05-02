---
name: reputation-analysis-reporting
description: Generate owner-facing reputation reports from Better Review's ingested Google Maps and Yelp review store.
---

# Reputation Analysis Reporting

Use this skill after `review-ingestion-storage` has created `data/review-store.json`.

The goal is to turn public Google Maps and Yelp review data into a practical restaurant reputation report that the owner can act on. Reports should compare the target restaurant with approved competitors, identify recurring themes, explain platform differences, and clearly mark data gaps when review text is unavailable.

## Inputs

Use local data first:

- `data/review-store.json` from `review-ingestion-storage`.
- Optional report mode: `initial`, `weekly`, or `ad-hoc`.
- Optional date window for weekly or focused analysis.

Do not ask the owner to paste reviews manually. If review text is missing, use available rating/review-count snapshots and data gaps as the fallback basis.

## Workflow

1. Load the normalized review store.
2. Separate the target restaurant from competitor restaurants.
3. Filter reviews by report mode and date window when provided.
4. Summarize review volume, rating averages, platform mix, visible text coverage, and data gaps.
5. Classify review themes across practical restaurant dimensions:
   - service
   - food
   - atmosphere
   - price
   - wait time
   - delivery or takeout
   - cleanliness
   - staff
   - operations
6. For the target restaurant, identify strengths, complaints, risks, and opportunities.
7. For competitors, summarize rating position, review themes, frequent praise, frequent complaints, and signals worth watching.
8. Compare Google Maps and Yelp separately when both platforms have data.
9. If review text is unavailable, produce a snapshot-based fallback report using rating, review count, platform status, and recorded data gaps.
10. Save `data/reputation-report.json` for daily alerts, weekly reports, and reply coaching.

## Analysis Rules

Prefer evidence from visible review text, but keep the report usable when text coverage is partial.

- Treat recent low ratings, repeated complaints, and unresolved operational themes as risks.
- Treat repeated praise with strong ratings as stable advantages.
- Treat competitor complaints as opportunities only when they are relevant to the target restaurant's positioning.
- Do not overclaim from one review. Label single-review signals as early signals.
- Keep competitor analysis focused on business learning. Do not produce reply drafts for competitor reviews.
- Mark data limitations explicitly when SerpApi, Google Places, Yelp, or source matching could not provide complete data.

## Output

The saved report must include:

- Report metadata: mode, generated time, input store timestamp, date window, and data coverage.
- Target restaurant summary.
- Platform comparison for Google Maps and Yelp.
- Theme analysis by restaurant and platform.
- Competitor comparison.
- Strengths, risks, opportunities, and recommended owner actions.
- Data gaps and fallback notes.

Use `scripts/generate_report.py` when command-line execution is available. It writes the normalized report to `data/reputation-report.json`.

## Owner-Facing Behavior

Explain the report in business language:

- What customers most often praise.
- What customers most often complain about.
- How the restaurant compares with nearby competitors.
- Which issues should be handled first.
- What data was unavailable and will be retried by future scans.

Do not describe SerpApi as an official Google Business Profile or Yelp Partner integration. Call it a public review data provider.
