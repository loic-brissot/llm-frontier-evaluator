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
| `combined_output_as_visible` | Non-interactive CSV/CLI ingestion where the export provides a single combined `Output Tokens` count without a reasoning split (`reasoning_tokens` recorded as `0`, `visible_tokens` recorded as total output). | the combined output total |
| `unavailable` | The export has no split (or no output token count is available). | null |

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

### Headless Claude Code (`claude-code`)

`claude -p --output-format stream-json` lines carry no timestamps. `scripts/tool_events.py` reads three logs a `run_benchmark.py` run leaves behind:

| Log | Gives |
| --- | --- |
| `tool-events/cli-stream.jsonl` | Tokens, tool calls, thinking block count, `duration_api_ms`, `total_cost_usd`. One attempt per `system`/`init` event. |
| `claude-sessions/*.jsonl` (Claude Code session transcripts) | A timestamp per content block: attempt bounds, `tool_use` → `tool_result` intervals, thinking block durations. |
| `hook-events/*.jsonl` (`.claude/settings.json` hooks) | `logged_at` per `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`: attempt bounds and `PreToolUse` → `PostToolUse` tool intervals. |

1. Each attempt runs from its prompt submission (the frozen prompt, then `Continue.` on a resume) to its last logged event. Wall clock runs from the first prompt to the last event. The idle gap between attempts (stall plus retry cooldown) is stored as `retry_gap_seconds` and kept out of active time.
2. A tool interval is `PreToolUse` → `PostToolUse` for its `tool_use_id`. Without that pair it is the transcript `tool_use` → `tool_result`. Intervals are merged as above. Wall clock minus tool time is active time minus merged tool time.
3. `harness_model_time` is the sum of `result.duration_api_ms` over the attempts. It is used only when every attempt ended with a `result` event. An attempt that stalled or was killed reports no API time, so the run then falls back to `wall_clock_minus_tool_time`. Both figures are kept in `model_time.raw.tool_events` (`duration_api_seconds`, `wall_clock_minus_tool_seconds`), with `attempts` and `attempts_without_result`.
   Tokens of an attempt that stalled, timed out, or was killed (no `result` event) are not read from `cli-stream.jsonl`: its assistant `usage.output_tokens` is a snapshot taken as each message starts (single digits to tens), not the final count. Those runs take their token totals from the final per-message usage in `claude-sessions/*.jsonl`, which spans every attempt, and the observation says so. Without a transcript the stream totals are kept.
4. A thinking block lasts from the previous transcript entry to the block's own entry. This upper bound includes request latency. Blocks are counted from the transcript, or from the stream when there is no transcript.

Tokens come from each finished attempt's `result.usage`. For an attempt without a `result`, assistant `message.usage` is counted once per message id. Claude reports no reasoning-token count, so `finish_run.py --non-interactive` records the output total as `combined_output_as_visible`. These whole-run totals replace the last attempt's `cli-result.json`. A usage export passed with `--usage-export` still wins. The harness-reported `total_cost_usd` and the aggregate are stored in `tokens.raw.claude_code`.

### Interactive Claude Code (`claude` without `-p`)

An interactive session writes no `cli-stream.jsonl` or `cli-result.json`. When both are absent and `claude-sessions/` or `hook-events/` exist, `scripts/tool_events.py` takes everything from those two logs:

- Tokens: assistant entries of `claude-sessions/*.jsonl`, one usage per Anthropic message id (the largest value per field, because one message's usage repeats on each content block). Input, uncached input, cache read, cache write, and output follow the headless rules, and the list-price estimate lands in `tokens.raw.pricing`. There is no harness-reported cost, so `tokens.raw.claude_code.total_cost_usd` is null.
- Tool calls: `tool_use` / `tool_result` blocks of the transcript; without transcripts, `PreToolUse` (call) and `PostToolUseFailure` or failed `PostToolUse` (failure) from the hook log, in which case tokens stay null.
- Time and thinking: as for headless runs. Idle time between a follow-up turn and the previous one counts as gap, not active time.
- Prompt check: the first `UserPromptSubmit` record and the first transcript prompt are compared with `prompt/<prompt-id>.txt` through `prompt_sha256`. A pasted prompt that differs only by trailing newline or line endings is accepted and flagged in `observations`. A changed prompt, a `[Pasted text #n]` placeholder, or a log-capped prompt that is not a prefix of the frozen file is reported as unverified. The result is stored in `tokens.raw.claude_code.prompt_check`.
- Interventions: every later `UserPromptSubmit` (a follow-up turn) and every `[Request interrupted by user]` entry is written to `observations`, because the run is then not a single user message. Tool calls denied by the `.claude` isolation hook are listed there too.

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

Set `source` to `provider_cache_read` when the export or hook log has a cache-read field, or `cursor_usage_csv` when populated from a Cursor billing CSV export in non-interactive/backfill mode. Set `unavailable` and leave `cache_read_tokens` null when it does not.

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

- **Public API list-price `Est. cost`**: Computed by `scripts/run_common.py` (`estimate_token_cost()`) and recorded in `tokens.raw.pricing`. It uses public per-1M-token API list prices from `reference/pricing-2026-10-18.json`. It applies context variants (e.g., `500k`, `1m`) and long-context input token thresholds (`threshold_input_tokens`). For local runs, `Est. cost` uses `estimated_cost_with_harness_usd` (which includes any applicable harness token surcharge such as Cursor's `$0.25/1M` rate on third-party models, while first-party models like `composer-*` and `grok-*` have no surcharge).
- **Actual harness-billed CSV cost**: Recorded in `tokens.raw.usage_csv.cost` directly from harness exports (e.g. Cursor team usage CSV). It reflects actual account billing, including harness third-party token surcharges, team/enterprise plan rates, and provider rounding.
- **Hook vs. usage CSV token deltas**: Stop-hook token totals (`cursor_stop_hook`) and Cursor usage CSV token totals may differ slightly (typically <1% due to system/wrapper framing tokens billed in the CSV export). `Est. cost` calculated from hook tokens thus matches billed CSV cost within cents (e.g. $1.76 est. cost vs $1.75 billed CSV cost).

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
