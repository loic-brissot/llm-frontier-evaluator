---
id: TASK-95
title: >-
  Price Claude Code runs by cache-write tier (5m vs 1h) so estimated cost
  matches what an API user pays
status: To Do
assignee: []
created_date: '2026-10-28 17:41'
updated_date: '2026-10-28 17:53'
labels: []
milestone: m-9
dependencies: []
priority: high
type: bug
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Headless Claude Code runs under-report cost by about 12%. Claude Code writes its prompt cache with the 1-hour TTL (usage.cache_creation.ephemeral_1h_input_tokens carries all cache writes), and Anthropic bills 1h cache writes at 2x the base input rate. reference/pricing-2026-10-18.json has one cache_write rate per model (1.25x input, the 5-minute tier), and estimate_token_cost() in scripts/run_common.py applies it to every cache write. Evidence from the 2026-10-26 campaign: france-road-accidents Opus 5.5 medium estimated $3.41 vs CLI total_cost_usd $3.84 (costBasis: list); the gap equals 141,955 cache-write tokens x ($8 - $5)/M.

Recommendation: price by the cache tier the run actually used, not by a per-harness price table. Add cache_write_1h (and keep cache_write as the 5m tier) to each Anthropic model in the pricing file, and split cache-write tokens by tier from the usage breakdown when it is present. This keeps one price per model and tier, so Cursor and Claude Code stay comparable at list prices, and the harness difference appears only because the harnesses use different cache tiers, which is what a user of that harness would really pay. Keep a harness-specific override only where a harness bills differently from the provider list price (e.g. Cursor first-party models).

Cursor: the team usage CSV has no 5m/1h split, but its Cost column shows which tier Cursor bills. Recomputing every Claude Opus 5.5 row in the repo's Cursor CSVs, Cost tracks list price at the 5m cache-write rate plus the $0.25/1M Cursor token rate (e.g. 11.43 vs 11.57 at 5m+fee vs 14.57 at 1h+fee; 9.93 vs 10.07 vs 10.74). Cursor runs therefore use the 5m tier as a validated basis, recorded as such (e.g. cache_tier 5m, source cursor_cost_column), not as an assumption. Older runs with no split and no cost column fall back to 5m with basis recorded as assumed. Only Opus rows carry a Cost value today; Sonnet and Haiku in Cursor are assumed to follow the same rule until a costed row confirms it.

Out of scope: Cursor Cost runs 1-4% below 5m+fee on every row (likely the $0.25/1M fee not applying to some tokens, or rounding). Track separately; it does not affect the tier decision.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 reference/pricing-2026-10-18.json gains a cache_write_1h rate for every Anthropic model, and docs/metrics.md documents how cache-write tiers are priced and which basis is used when the tier split is missing
- [ ] #2 estimate_token_cost() in scripts/run_common.py prices ephemeral_5m and ephemeral_1h cache-write tokens at their own rates and stores the tier split and pricing basis in run.json
- [ ] #3 A unit test checks that recomputed costs for the existing claude-code runs fall within 1% of the CLI total_cost_usd (list basis), and README.md / dashboard are re-synced with the corrected costs
- [ ] #4 A unit test checks that, for Cursor runs whose usage CSV has a numeric Cost, the recomputed list estimate at the 5m tier plus the Cursor token rate falls within 5% of the CSV Cost, so a switch to 1h-tier billing would be caught
<!-- AC:END -->
