# Better Review

Better Review is an agent pack for restaurant owners who want to monitor Google Maps and Yelp reviews, track nearby competitors, and turn public customer feedback into practical operating recommendations.

## What It Does

- Finds and verifies a restaurant's Google Maps and Yelp sources.
- Discovers five nearby competitors based on cuisine, price point, dining occasion, and target customers.
- Ingests public Google Maps and Yelp reviews through configured providers.
- Produces initial reputation analysis, daily review alerts, response suggestions, and weekly competitor reports.

## Required Credentials

The runtime expects these environment variables:

- `GOOGLE_PLACES_API_KEY`
- `SERPAPI_API_KEY`

Do not commit API keys or local runtime data.

## Contents

- `agent-pack.yaml` - pack manifest and publishing metadata
- `agent/` - shipped agent behavior files
- `skills/` - Better Review skills and supporting scripts
- `tests/` - mock and live integration test entry points
- `zip/better-review-0.1.0.zip` - current packaged release

## Validation

The latest local validation passed:

```bash
python3 -m unittest tests/test_api_integrations.py
```
