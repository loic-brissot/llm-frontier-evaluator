# Metrics

These four columns match the gallery heading **How each model worked**. `scripts/compare_runs.py` prints local runs with the rounding rules below. The reference rows use the published labels, which `reference/README.md` transcribes.

`rules_version` for this file is 2. The changes from version 1 are listed under [Version history](#version-history).

## Where a number comes from

Use the usage report for that run. Save the report under `runs/<prompt-id>/<run-id>/usage/` when the harness can write one. When the harness only shows the figures, copy them into `run.json`. Name the field you copied.

Leave the matching JSON field null when the report has no such figure.

## Terms

| Term | Meaning |
| --- | --- |
| Reasoning tokens | Tokens the provider reports as reasoning or thinking. |
| Visible tokens | Generated tokens that are not reasoning tokens. |
| Tokens generated | Reasoning tokens plus visible tokens. Input tokens are excluded. |
| Model time | Time the model spent generating. Tool time is excluded. |
| Tool call | One invocation of one tool. |
| Failure | A tool call the harness or the tool reports as failed. |
| Context re-read | Input tokens served from the prompt cache. |
| Wall clock | Time from the sent prompt to the model stop. This is not model time. |

## 1. Tokens generated

Store integers in `tokens.reasoning_tokens` and `tokens.visible_tokens`.

Copy the provider usage object into `tokens.raw` first. Then set `tokens.split_rule` from the export you have:

| `split_rule` | When to use it | Visible tokens |
| --- | --- | --- |
| `output_includes_reasoning` | The output total includes reasoning tokens. OpenAI `completion_tokens` is this kind of total. `completion_tokens_details.reasoning_tokens` is the reasoning part. | output total minus reasoning tokens |
| `output_excludes_reasoning` | The output total already omits reasoning tokens, and reasoning is a separate field. | the output total |
| `harness_pre_split` | The harness export already gives reasoning and visible as two final counts. | the visible count from the export |
| `unavailable` | The export has no split. | null |

Leave both token fields null when the split is `unavailable`. Do not estimate a split. A single output total, including Cursor `Output Tokens`, is this case. Keep that total in `tokens.raw`.

The chart cell is:

`round(total / 1000)` + `k · ` + `round(reasoning / total × 100)` + `%`

`total` is reasoning plus visible. Round half away from zero, to the nearest integer.

Read a cell such as `107k · 48%` as 107 thousand generated tokens, of which 48 percent are reasoning tokens.

## 2. Model time

Store `model_time.generating_seconds`.

| `source` | What to store |
| --- | --- |
| `harness_model_time` | A harness field that already means model generation time, with tool time excluded. |
| `sum_of_llm_request_durations` | The sum of LLM request durations. Exclude every tool duration. |
| `wall_clock_minus_tool_time` | Wall clock minus the time inside tool calls, read from the Cursor hook log. `rules_version` 2 only. |
| `unavailable` | Null. Use this when the only clock you have is wall clock and no tool log. |

Wall clock goes in `wall_clock` only.

Prefer the sources in table order. A harness or usage export that reports generation time directly wins over `wall_clock_minus_tool_time`.

### Wall clock minus tool time

`scripts/tool_events.py` reads `runs/<prompt-id>/<run-id>/tool-events/*.jsonl`:

1. Wall clock runs from the first `beforeSubmitPrompt` to the first `stop` after it.
2. Each `postToolUse` or `postToolUseFailure` is logged when the tool returns. Its interval is `logged_at` minus `duration` milliseconds, up to `logged_at`, clipped to the wall clock.
3. Overlapping intervals are merged, so parallel tool calls count once. The merged length is tool time.
4. `generating_seconds` is wall clock minus tool time, in seconds to one decimal. Per-tool durations in milliseconds preserve floating-point precision before rounding.

When any tool event has no `duration`, the figure is not taken from the log and the source stays a manual choice.

This is an upper bound on generation. It also holds network and queue latency, time to first token, harness overhead, hook execution, and any approval wait, because Cursor does not report LLM request durations to hooks. It is not comparable with a `harness_model_time` or `sum_of_llm_request_durations` cell, including the reference series.

The hook also logs `afterAgentThought`, whose `duration_ms` is the length of one thinking block. Duplicate thought records (such as dual base and step-suffixed `generation_id` events for the same block) are deduplicated. Their sum is a lower bound, because visible output is not in it. `finish_run.py` stores both figures, and the summed and merged tool time, under `model_time.raw.tool_events`. Thinking time is not a score.

The chart cell is the number of minutes, to one decimal, with the suffix ` min`. Round half away from zero.

## 3. Tool calls

Count calls and failures in four buckets: `shell`, `files`, `visual_checks`, and `web`. The bucket rules are in `docs/tool-buckets.md`.

The chart total is the sum of those four buckets. Failures are included in that total. Failures are not an extra bar.

The chart cell is the total. When the failure count is greater than zero, the cell also shows that count and `✗`. A zero-failure row shows the total alone. The gallery’s Sonnet row is `101`, with no red mark.

`other` is every remaining model tool call. Print it under the table. Keep it out of the four-column total.

For each bucket, `by_tool` names the harness tools and their counts. The sum of `by_tool` must equal the bucket.

`scripts/finish_run.py` counts `runs/<prompt-id>/<run-id>/tool-events/*.jsonl` when those files exist. Each `postToolUse` or `postToolUseFailure` line is one call, classified with `docs/tool-buckets.md`. A missing log leaves the counts null. When the log contains the prompt submission and the agent stop, those two timestamps are `wall_clock`. The same log gives model time under `wall_clock_minus_tool_time`, as described in section 2.

## 4. Context re-read

Store `context_reread.cache_read_tokens`.

| Provider field | Where it goes |
| --- | --- |
| Anthropic `cache_read_input_tokens` | `cache_read_tokens` |
| OpenAI `prompt_tokens_details.cached_tokens` | `cache_read_tokens` |
| Cache creation or cache write | `cache_write_tokens` |
| Uncached input | `uncached_input_tokens` |
| Cursor `Cache Read` / `stop` hook `cache_read_tokens` | `cache_read_tokens` |
| Cursor `Input (w/ Cache Write)` / `stop` hook `cache_write_tokens` | `cache_write_tokens`. This column is the cache write alone. |
| Cursor `Input (w/o Cache Write)` / `stop` hook `input_tokens - cache_read_tokens - cache_write_tokens` | `uncached_input_tokens` |

Set `source` to `provider_cache_read` when the export has a cache-read field. Set `unavailable` and leave `cache_read_tokens` null when it does not.

Cursor `Total Tokens` is a checksum of cache write, uncached input, cache read, and output. It is not tokens generated. The usage CSV section below is the full reading.

The chart cell is millions of tokens, to one decimal, with the suffix `M`. Round half away from zero.

## Usage CSV

`scripts/finish_run.py` reads a usage CSV by header name and sums the selected rows. A JSON usage object is still read the same way. When both are present, a provider JSON split fills the token split. CSV column sums fill cache figures the JSON does not already contain. When both reports include a cache-read count and the counts differ, the script says so and the prompts default to the CSV sum.

A team export can contain other models, other people, and other times. The default selection keeps rows whose model name matches `model.name`, including a more specific export name such as `composer-2.5-fast` for `composer-2-5`, and whose timestamp falls inside `wall_clock` (preserving millisecond precision with a clock-skew grace window) when those timestamps exist. The script asks for confirmation when that selection leaves rows out, when the export model name is shorter than `model.name`, or when the selected rows contain more than one model, user, or kind.

| Header | Where it goes |
| --- | --- |
| `Cache Read`, `cache_read_input_tokens`, `cached_tokens` | `context_reread.cache_read_tokens` |
| `cache_write_tokens`, `cache_creation_input_tokens`, Cursor `Input (w/ Cache Write)` | `context_reread.cache_write_tokens` |
| `uncached_input_tokens`, Cursor `Input (w/o Cache Write)` | `context_reread.uncached_input_tokens` |
| `reasoning_tokens` and `visible_tokens` together | `harness_pre_split` |
| `Output Tokens`, `output_tokens`, `completion_tokens` | `tokens.raw` when no reasoning split is present |
| `generating_seconds`, `model_time_seconds` | `model_time.generating_seconds`, source `sum_of_llm_request_durations` |
| `Total Tokens` | Checksum only. This is not tokens generated. |

On a Cursor row, `Total Tokens` equals cache write, uncached input, cache read, and output. A mismatch is reported and is not repaired. That export has request timestamps and no generation duration, so model time stays `unavailable`. A numeric `Cost` is printed and copied into `tokens.raw`. It is not one of the four scores. Cells that read `-` or `Free` are left out of that sum.

This reading does not change `rules_version`.

## Cost estimation (`Est. cost`) vs harness-billed cost

- **Public API list-price `Est. cost`**: Computed by `scripts/run_common.py` (`estimate_token_cost()`) and recorded in `tokens.raw.pricing`. It uses public per-1M-token API list prices from `reference/pricing-2026-10-18.json`. It applies context variants (e.g., `500k`, `1m`) and long-context input token thresholds (`threshold_input_tokens`). When third-party harness surcharges apply (such as Cursor's `$0.25/1M` rate on third-party models), `estimate_token_cost()` calculates both `estimated_cost_usd` (base API list price) and `estimated_cost_with_harness_usd` (base API cost + harness surcharge).
- **Actual harness-billed CSV cost**: Recorded in `tokens.raw.usage_csv.cost` directly from harness exports (e.g. Cursor team usage CSV). It reflects actual account billing, including harness third-party token surcharges, team/enterprise plan rates, and provider rounding.

## Rounding

Local rows use this function: round half away from zero.

| Column | Step |
| --- | --- |
| Tokens generated | 1,000 tokens, and 1 percentage point |
| Model time | 0.1 minute |
| Tool calls | 1 call. These counts are exact. |
| Context re-read | 100,000 tokens (0.1 million) |

The reference token, time, and cache labels are already rounded. Their bar flex values are a transcription aid, not raw provider counts. Tool counts in the reference tooltips are exact integers.

## Outcome

`outcome` is not a fifth score.

| Field | Values |
| --- | --- |
| `model_stopped` | true when the model ended the run by itself |
| `operator_saw_a_page` | true, false, or null when nobody has opened the page |
| `summary` | One sentence |

## Observations

`observations` is a string on the run record. Use it for remarks that are not one of the four scores: a tool whose bucket was hard to choose, what a failure report said, and any fact that puts the row outside its series. Leave it empty when there is nothing to add. It is not a score.

## Worked reading of a reference cell

Claude Fable 5.1 high, from the gallery chart:

| Column | Published cell | Tooltip |
| --- | --- | --- |
| Tokens generated | `107k · 48%` | 52k reasoning out of 107k generated |
| Model time | `24.9 min` | 24.9 min generating |
| Tool calls | `60 3✗` | `shell 37, files 2, visual checks 16, web and publishing 5; 3 failed` |
| Context re-read | `6.4M` | 6.4M tokens read from the prompt cache |

The bar flex for that token row is 51.799 and 55.43 (thousands). Their sum rounds to 107k. The reasoning share rounds to 48%. The title’s `52k` is the reasoning bar rounded to thousands. Use the cell `107k · 48%` as the comparison figure.

## Version history

| `rules_version` | Change |
| --- | --- |
| 1 | First rules. Model time needs a harness or usage-export duration. |
| 2 | Adds the model time source `wall_clock_minus_tool_time`, read from the Cursor hook log. The tool buckets did not change. |

A version 1 record keeps `rules_version` 1 and cannot use the version 2 source. A series holds one `rules_version`, so version 2 runs start a new series.
