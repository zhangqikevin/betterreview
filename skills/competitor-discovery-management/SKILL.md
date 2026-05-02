---
name: competitor-discovery-management
description: Discover nearby restaurant competitors, guide owner confirmation, and save the approved competitor set for Better Review.
---

# Competitor Discovery Management

Use this skill during onboarding after `review-source-discovery` has created `data/source-profile.json`, and whenever the owner wants to refresh or change competitors.

The goal is to find a practical competitive set for review monitoring without asking the owner to gather review files.

## Inputs

Ask only for missing information:

- Confirmed target restaurant source profile from `data/source-profile.json`
- Optional cuisine or category focus if the Google place categories are too broad
- Optional owner edits to the suggested competitor list: approve, remove, replace, or add a restaurant

Do not ask the owner to upload, paste, or forward reviews.

## Required Services

- `GOOGLE_PLACES_API_KEY` for nearby restaurant discovery and place details.
- `SERPAPI_API_KEY` for Yelp source lookup on approved competitors when available.

Never print or store raw API keys in agent files, logs, or saved competitor records.

## Workflow

1. Load the target restaurant from `data/source-profile.json`.
2. Use the target Google coordinates when available; otherwise use the target address for text search.
3. Infer the target restaurant profile from its name, Google details, Yelp categories, Yelp price tier, and visible snippets. Capture cuisine/category, price positioning, occasion, and likely customer segments.
4. Search Google Places with multiple profile-specific keywords within the configured radius, defaulting to 10 miles. For example, a shabu/hot pot restaurant should search for shabu shabu, hot pot, Japanese hot pot, sukiyaki, and similar terms instead of generic "restaurant".
5. Remove the target restaurant itself and weak candidates such as closed businesses, non-restaurant venues, hotels, grocery stores, and convenience stores when type data makes that clear.
6. Rank competitors by cuisine/category relevance first, then proximity, review-count visibility, rating, and price fit. Strongly downrank restaurants with mismatched categories such as steakhouse, burger, American bar, pizza, or cafe when the target is a hot pot restaurant.
7. Return the strongest 5 candidates by default, with a few alternates when available.
8. For each suggested competitor, fetch Google details and attempt Yelp source matching through SerpApi.
9. Explain the list in business language and ask the owner to confirm, remove, replace, or add competitors.
10. Save `data/competitors.json` with target profile, all suggested candidates, owner decisions, approved competitors, platform source IDs, rating/review-count snapshots, and data gaps.

## Ranking Rules

Prefer competitors that are:

- Near the target restaurant and in the same customer catchment area.
- Similar enough in category, cuisine, price positioning, or occasion.
- Similar enough in target customer intent. A premium shabu restaurant should compare against hot pot, shabu, sukiyaki, Japanese hot pot, Korean BBQ, or similar experience-driven Asian meat restaurants before generic nearby restaurants.
- Actively operating.
- Review-visible, with enough review count to make comparison meaningful.

Avoid ranking a competitor highly only because it has a high rating. A popular nearby restaurant with mixed reviews may be more useful than a perfect but tiny listing.

Avoid choosing cross-category restaurants only because they are close. For example, an American steakhouse, burger shop, wine bar, or sandwich restaurant is not a strong default competitor for a hot pot restaurant unless the owner explicitly wants broad same-plaza dining alternatives.

## Owner Confirmation

Treat the first generated list as a draft. The owner can:

- Approve all suggestions.
- Remove irrelevant competitors.
- Replace a suggestion with another restaurant.
- Add a known local competitor by name and address.
- Ask for a new scan with a different category or radius.

If the owner does not want to choose manually, keep the top 5 automatic candidates and mark the confirmation mode as `auto_selected`.

## Output

The saved competitor profile must include:

- Target restaurant reference and discovery settings.
- Inferred target restaurant profile: cuisine/category, price tier, occasion positioning, likely customer segments, evidence, and search keywords.
- Suggested competitors and alternates.
- Approved competitors used for monitoring.
- For each competitor: Google source details, Yelp source details when available, rating, review count, coordinates, distance, rank score, and match status.
- Owner decisions such as approved, removed, replaced, or added.
- `data_gaps` for missing Yelp matches, API limits, ambiguous matches, or insufficient category data.
- `last_checked_at` in ISO 8601 UTC.

Use `scripts/discover_competitors.py` when command-line execution is available. It writes the normalized competitor set to `data/competitors.json`.

## Owner-Facing Behavior

Keep the interaction short:

- Present the recommended competitors with names, neighborhoods/addresses, rating, review count, and why each was selected.
- Ask one confirmation question for the list.
- Do not force the owner to upload supporting material.
- If API data is incomplete, mark the gap and continue with the best available competitor set.
