---
name: review-source-discovery
description: Match a restaurant to its Google Maps and Yelp review sources, then save a normalized source profile for Better Review.
---

# Review Source Discovery

Use this skill during onboarding or whenever the owner changes the target restaurant. The goal is to identify the correct Google Maps place and Yelp page/review source with enough confidence for automated review monitoring.

## Inputs

Ask only for missing information:

- Restaurant name
- Street address, city, state, and ZIP when available
- Optional clarification if the match is ambiguous, such as neighborhood, phone number, or website

Do not ask the owner to upload, paste, or forward reviews.

## Required Services

- `GOOGLE_PLACES_API_KEY` for Google Places search/details.
- `SERPAPI_API_KEY` for Yelp search/review source discovery and later Google/Yelp review ingestion.

Never print or store raw API keys in agent files, logs, or saved profiles.

## Workflow

1. Search Google Places using the restaurant name plus address.
2. Fetch Google Place Details for the strongest candidate.
3. Score Google candidates using name similarity, address similarity, distance when coordinates are available, business status, and restaurant/food category fit.
4. Search Yelp through SerpApi using the same restaurant name and location.
5. Score Yelp candidates using name, address, city/state, phone/website when present, category fit, and rating/review count plausibility.
6. Save `data/source-profile.json` with platform IDs, match confidence, ratings, review counts, coordinates, and any data gaps.
7. If a platform cannot be matched confidently, keep the profile usable by marking that platform as `missing` or `ambiguous` and recording the reason. Do not ask the owner for review files.

## Confidence Rules

- `high`: name and address clearly match; safe to use automatically.
- `medium`: likely same business, but one field is incomplete or slightly inconsistent; ask for a short confirmation before monitoring.
- `low`: multiple plausible matches or weak address/name agreement; ask one clarification question.
- `missing`: provider returned no usable result or the API failed.

Treat chain restaurants and businesses with multiple nearby branches as ambiguous unless the address clearly identifies the branch.

## Output

The saved source profile must include:

- Target restaurant name and address from the owner.
- Google source details: `place_id`, `name`, `formatted_address`, `rating`, `user_ratings_total`, coordinates, business status, and confidence.
- Yelp source details: SerpApi/Yelp place identifier or URL when available, `name`, address, `rating`, `review_count`, and confidence.
- `data_gaps` describing missing/ambiguous sources, rate limits, or unavailable review text.
- `last_checked_at` in ISO 8601 UTC.

Use `scripts/discover_sources.py` when command-line execution is available. It writes the normalized profile to `data/source-profile.json`.

## Owner-Facing Behavior

Explain results in business language:

- Which Google/Yelp sources were found.
- Whether each match is confident enough to monitor.
- Any gaps that Better Review will retry automatically.

Do not describe SerpApi as an official Google Business Profile or Yelp Partner integration. Call it a public review data provider.
