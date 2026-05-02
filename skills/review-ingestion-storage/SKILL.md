---
name: review-ingestion-storage
description: Ingest public Google Maps and Yelp reviews for the target restaurant and approved competitors, then save a deduplicated review store for Better Review.
---

# Review Ingestion Storage

Use this skill after `review-source-discovery` has created `data/source-profile.json` and `competitor-discovery-management` has created `data/competitors.json`.

The goal is to collect the public review data Better Review can access, preserve raw provider responses, normalize review records for analysis, and make future scans deduplicate reliably.

## Inputs

Use local data first:

- `data/source-profile.json` for the owner's restaurant and its Google/Yelp sources.
- `data/competitors.json` for approved competitors and their Google/Yelp sources.
- Optional ingestion settings such as max reviews per platform, scan mode, language, and sort order.

Do not ask the owner to upload, paste, or forward review files. If an API cannot return review text, record the gap and continue with snapshots.

## Required Services

- `SERPAPI_API_KEY` for Google Maps Reviews and Yelp Reviews ingestion.
- `GOOGLE_PLACES_API_KEY` only when refreshing Google rating/review-count snapshots is needed.

Never print or store raw API keys in agent files, logs, or saved review stores.

## Workflow

1. Load the target restaurant source profile.
2. Load approved competitors. If the owner has not confirmed competitors, use `approved_competitors`; do not silently promote unapproved suggestions unless they were marked `auto_selected`.
3. Build a monitoring set containing the target restaurant and approved competitors.
4. For each restaurant, inspect Google and Yelp source status.
5. For each matched platform source, request public reviews through SerpApi.
6. Normalize each visible review with platform, restaurant role, source ID, review ID, author, rating, date, text, review URL, owner response when available, and raw provider payload.
7. Generate a stable dedupe key for every review using provider ID when present, otherwise platform + source ID + author + rating + date + text hash.
8. Merge with any existing review store so repeated scans do not create duplicate review records.
9. Save rating/review-count snapshots for every platform source even when review text is unavailable.
10. Record API errors, rate limits, missing source IDs, empty review results, and text visibility limits in `data_gaps`.
11. Write `data/review-store.json` for downstream initial reporting, daily alerts, weekly reports, and reply coaching.

## Scan Modes

- `initial`: collect a wider recent review window for first report generation.
- `daily`: collect newest reviews first and mark only newly seen reviews for alerting.
- `weekly`: collect newest reviews first and preserve enough metadata for week-level summaries.

Use newest-first ordering when provider support is available. Stop after the configured max review count or when provider pagination is exhausted.

## Data Gap Rules

Keep automation moving when data is incomplete:

- Missing or ambiguous Google/Yelp source: record a retryable source gap and skip that platform.
- SerpApi error, timeout, or rate limit: record a retryable provider gap.
- Review count changed but review bodies are empty or hidden: record a visibility gap and keep the latest rating/review-count snapshot.
- Competitor platform gap: monitor the available platform and retry missing sources later.

Do not tell the owner to manually export review data.

## Output

The saved review store must include:

- Monitoring run metadata: scan mode, started/finished time, providers attempted, and result counts.
- Restaurant records for the target and approved competitors.
- Platform snapshots with rating, review count, source status, and provider visibility status.
- Deduplicated review records with raw provider payloads retained.
- `new_review_keys` for the current scan, so daily alerts can identify only newly seen reviews.
- `data_gaps` for missing sources, provider failures, empty review bodies, limits, or ambiguous matches.

Use `scripts/ingest_reviews.py` when command-line execution is available. It writes the normalized store to `data/review-store.json`.

## Owner-Facing Behavior

Summarize in business language:

- How many new reviews were found for the owner's restaurant.
- Which platforms were scanned.
- Whether competitor reviews were found.
- Any data gaps Better Review will retry automatically.

Do not describe SerpApi as an official Google Business Profile or Yelp Partner integration. Call it a public review data provider.
