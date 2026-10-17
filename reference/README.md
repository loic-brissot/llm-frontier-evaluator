# Reference series `lassence-2026-10`

This file is a transcription of the gallery chart, read on 17 October 2026. It is the external baseline. It is not a local run.

Sources:

- [Building a 3D atlas of Paris as model benchmark](https://lassence.net/posts/personal-benchmark-3d-atlas-of-paris/), 11 October 2026
- [bench.lassence.net](https://bench.lassence.net/)

The machine copy is `lassence-2026-10.json`. `scripts/compare_runs.py` checks that the labels, the bar flex values, and the tool tooltips agree.

## How each model worked

Rows follow the chart order. Anthropic first, then OpenAI.

| Model | Harness | Tokens generated | Model time | Tool calls | Context re-read |
| --- | --- | --- | --- | --- | --- |
| Claude Fable 5.1 high | Claude Code | 107k · 48% | 24.9 min | 60 3✗ | 6.4M |
| Claude Opus 5.5 high | Claude Code | 187k · 47% | 31.6 min | 94 2✗ | 15.5M |
| Claude Opus 5.5 medium | Claude Code | 77k · 37% | 12.2 min | 54 4✗ | 5.7M |
| Claude Sonnet 5.5 high | Claude Code | 253k · 52% | 32.5 min | 101 | 22.4M |
| Claude Haiku 5.5 high | Claude Code | 157k · 64% | 12.9 min | 52 3✗ | 7.7M |
| GPT-6 Astra high | Codex app | 31k · 20% | 13.0 min | 81 6✗ | 5.7M |
| GPT-6.1 Sol high | Codex app | 43k · 36% | 27.5 min | 109 11✗ | 11.8M |
| GPT-6 Luna high | Codex app | 65k · 63% | 12.2 min | 77 8✗ | 11.0M |

The percent is the reasoning share of tokens generated. The red count is failed tool calls, and those calls are inside the total. Sonnet shows no red count because the tooltip says 0 failed.

### Tool calls behind the totals

| Model | Shell | Files | Visual checks | Web | Failed |
| --- | --- | --- | --- | --- | --- |
| Claude Fable 5.1 high | 37 | 2 | 16 | 5 | 3 |
| Claude Opus 5.5 high | 61 | 2 | 28 | 3 | 2 |
| Claude Opus 5.5 medium | 36 | 2 | 13 | 3 | 4 |
| Claude Sonnet 5.5 high | 54 | 17 | 29 | 1 | 0 |
| Claude Haiku 5.5 high | 39 | 4 | 9 | 0 | 3 |
| GPT-6 Astra high | 53 | 0 | 21 | 7 | 6 |
| GPT-6.1 Sol high | 65 | 0 | 32 | 12 | 11 |
| GPT-6 Luna high | 52 | 0 | 22 | 3 | 8 |

The gallery tooltip calls the web column “web and publishing”. The legend calls it “web”.

## Limits of this transcription

- Token, time, and cache figures on the chart are rounded. The JSON keeps the CSS bar flex beside each label. Those flex values are not raw provider token counts.
- Tool counts are integers from the tooltips.
- The Opus 5.5 medium label says `12.2 min`. The bar flex is `12.25`. The label is the published figure. Half-up rounding of 12.25 would print `12.3 min`, so the flex is not a higher-precision source for that cell.
- The Anthropic harness is Claude Code because the post says every model ran through Claude Code or Codex. The gallery does not repeat that label on each Anthropic card. OpenAI cards do say Codex app.
- The post says seven models. This file has eight rows, because Opus 5.5 medium and Opus 5.5 high are separate rows of one model.
- The post says a follow-up fixed a minor Luna bug. The gallery does not say whether the Luna metrics include that follow-up.
- The post names Opus 5.5 high as the author’s favorite. The gallery tier list below is a different ranking. This framework does not score visual quality.

## Gallery tiers

These tiers are copied from the gallery. They are not process metrics.

| Tier | Gallery label | Rows, in gallery order |
| --- | --- | --- |
| S | Star | GPT-6 Astra high, Claude Fable 5.1 high |
| A | High-end | Claude Opus 5.5 medium, Claude Opus 5.5 high, GPT-6.1 Sol high |
| B | Mid-range | Claude Sonnet 5.5 high |
| C | Low-end | Claude Haiku 5.5 high, GPT-6 Luna high |
