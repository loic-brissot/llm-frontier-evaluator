# Benchmark Results

Full per-series comparison tables, screenshots, and hosted live demo links for the LLM Frontier Evaluator benchmark runs across all evaluated prompts and agent harnesses.

- **Interactive Web Dashboard & Pareto Frontier Explorer**: [loic-brissot.github.io/llm-frontier-evaluator](https://loic-brissot.github.io/llm-frontier-evaluator/)
- **Hosted Live Demos Showcase**: [loic-brissot.github.io/llm-frontier-evaluator-demos](https://loic-brissot.github.io/llm-frontier-evaluator-demos/)
- **Benchmark Tool & Methodology Overview**: [`README.md`](README.md)
- **Evaluation Protocol**: [`docs/protocol.md`](docs/protocol.md)
- **Metrics & Tool Buckets**: [`docs/metrics.md`](docs/metrics.md) | [`docs/tool-buckets.md`](docs/tool-buckets.md)

## Comparisons

Rows compare only inside one series, so each series has its own table ([`docs/protocol.md`](docs/protocol.md)). Metric details and tool classifications are documented in [`docs/metrics.md`](docs/metrics.md) and [`docs/tool-buckets.md`](docs/tool-buckets.md); pricing rates use [`reference/pricing-2026-10-18.json`](reference/pricing-2026-10-18.json).

### `adaptive-endurance-coach`

![adaptive-endurance-coach — Grok 4.7 high (2026-10-28-cursor-grok-4-7-high)](runs/adaptive-endurance-coach/2026-10-28-cursor-grok-4-7-high/artifacts/screenshot.png)

**Local series `adaptive-endurance-coach-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Grok 4.7 high | Cursor | 247k | n/a | 154 ✓<br>1 ✗ | 8.0M | $6.19 | UI ✓<br>Data 5/5 ✓<br>1 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/adaptive-endurance-coach/2026-10-28-cursor-grok-4-7-high/index.html) |
| claude-haiku-5-5 high | Cursor | 83k | 6.5 min | 67 ✓<br>0 ✗ | 4.6M | $1.31 | UI ✓<br>Data 5/5 ✓<br>0 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/adaptive-endurance-coach/2026-10-30-cursor-claude-haiku-5-5-high/index.html) |
| composer-2.5 high | Cursor | 29k | 2.3 min<br>0.1 min thinking | 63 ✓<br>3 ✗ | 0.9M | $0.26 | UI ✗<br>Data 4/5 ✓<br>177 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/adaptive-endurance-coach/2026-10-30-cursor-composer-2-5-high/index.html) |
| kimi-k3 high | Cursor | 69k | 5.2 min<br>2.4 min thinking | 28 ✓<br>3 ✗ | 1.8M | $2.24 | UI ✓<br>Data 5/5 ✓<br>0 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/adaptive-endurance-coach/2026-10-30-cursor-kimi-k3-high/index.html) |
| muse-wonder high | Cursor | 21k | 2.2 min | 8 ✓<br>0 ✗ | 0.2M | $0.63 | UI ✓<br>Data 5/5 ✓<br>0 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/adaptive-endurance-coach/2026-10-30-cursor-muse-wonder-high/index.html) |
| gemini-3.8-flash high | Cursor | 109k | 13.7 min<br>8.9 min thinking | 59 ✓<br>3 ✗ | 4.5M | $2.28 | UI ✓<br>Data 5/5 ✓<br>221 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/adaptive-endurance-coach/2026-10-31-cursor-gemini-3-8-flash-high/index.html) |

### `france-electricity-carbon-flow`

![france-electricity-carbon-flow — Gemini 4 Argon 1m medium (2026-10-19-cursor-gemini-4-argon-1m-medium)](runs/france-electricity-carbon-flow/2026-10-19-cursor-gemini-4-argon-1m-medium/artifacts/screenshot.png)

**Local series `france-electricity-carbon-flow-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini 4 Argon 1m medium | Cursor | 73k | 17.7 min<br>14.6 min thinking | 23 ✓<br>5 ✗ | 1.0M | $2.55 | UI ✓<br>Data 4/4 ✓<br>3.5k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-electricity-carbon-flow/2026-10-19-cursor-gemini-4-argon-1m-medium/index.html) |

### `france-rail-24h-pulse`

![france-rail-24h-pulse — Claude Opus 5.5 300k high (2026-10-19-cursor-claude-opus-5-5-high-300k-high)](runs/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/artifacts/screenshot.png)

**Local series `france-rail-24h-pulse-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 300k high | Cursor | 90k | 20.1 min<br>7.7 min thinking | 47 ✓<br>3 ✗ | 5.5M | $6.53 | UI ✓<br>Data 3/3 ✓<br>820k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-19-cursor-claude-opus-5-5-high-300k-high/index.html) |
| Gemini 3.8 Flash high | Cursor | 119k | 18.1 min<br>5.8 min thinking | 122 ✓<br>8 ✗ | 11.0M | $4.76 | UI ✗<br>Data 3/3 ✓<br>828k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-22-cursor-gemini-3-8-flash-high/index.html) |
| GLM 5.3 high | Cursor | 79k | 10.4 min<br>3.9 min thinking | 78 ✓<br>2 ✗ | 5.1M | $3.16 | UI ✗<br>Data 3/3 ✓<br>827k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-22-cursor-glm-5-3-high/index.html) |
| GPT-5.6 Sol medium | Cursor | 15k | 2.8 min<br>0.2 min thinking | 13 ✓<br>0 ✗ | 0.2M | $0.63 | UI ✗<br>Data 0/3 ⚠<br>118 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-22-cursor-gpt-5-6-sol-medium/index.html) |
| Grok 4.7 high | Cursor | 213k | 60.1 min<br>49.8 min thinking | 138 ✓<br>4 ✗ | 9.8M | $7.11 | UI ✗<br>Data 3/3 ✓<br>888k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-22-cursor-grok-4-7-high/index.html) |
| Muse Wonder medium | Cursor | 26k | 3.4 min | 18 ✓<br>1 ✗ | 0.6M | $0.98 | UI ✓<br>Data 0/3 ⚠<br>0 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-22-cursor-muse-wonder-medium/index.html) |

**Local series `france-rail-24h-pulse-claude-code`**: Claude Code, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 high | Claude Code | 231k | 26.9 min<br>16.6 min thinking | 98 ✓<br>1 ✗ | 17.9M | $5.42 | UI ✓<br>Data 3/3 ✓<br>830k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-rail-24h-pulse/2026-10-25-claude-code-claude-sonnet-5-5-high/index.html) |

### `france-road-accidents`

![france-road-accidents — Muse Wonder 300k medium (2026-10-19-cursor-muse-wonder-300k-medium)](runs/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/artifacts/screenshot.png)

**Local series `france-road-accidents-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Muse Wonder 300k medium | Cursor | 26k | 4.8 min | 37 ✓<br>4 ✗ | 1.7M | $1.81 | UI ✓<br>Data 2/2 ✓<br>394k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-road-accidents/2026-10-19-cursor-muse-wonder-300k-medium/index.html) |

**Local series `france-road-accidents-claude-code`**: Claude Code, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 medium | Claude Code | 91k | 14.1 min<br>6.3 min thinking | 44 ✓<br>2 ✗ | 4.4M | $3.84 | UI ✓<br>Data 2/2 ✓<br>1.2M records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-road-accidents/2026-10-26-claude-code-claude-opus-5-5-medium/index.html) |
| Claude Sonnet 5.5 high | Claude Code | 321k | 37.4 min<br>22.7 min thinking | 143 ✓<br>6 ✗ | 38.9M | $8.93 | UI ✓<br>Data 2/2 ✓<br>1.1M records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/france-road-accidents/2026-10-26-claude-code-claude-sonnet-5-5-high/index.html) |

### `paris-1910-flood-simulator`

![paris-1910-flood-simulator — Claude Opus 5.5 high (2026-10-20-cursor-claude-opus-5-5-high)](runs/paris-1910-flood-simulator/2026-10-20-cursor-claude-opus-5-5-high/artifacts/screenshot.png)

**Local series `paris-1910-flood-simulator-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 high | Cursor | 228k | 42.2 min<br>19.6 min thinking | 134 ✓<br>8 ✗ | 12.9M | $12.08 | UI ✓<br>Data 6/6 ✓<br>351k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-1910-flood-simulator/2026-10-20-cursor-claude-opus-5-5-high/index.html) |
| Claude Opus 5.5 medium | Cursor | 198k | 39.2 min<br>15.4 min thinking | 171 ✓<br>1 ✗ | 16.0M | $13.81 | UI ✓<br>Data 6/6 ✓<br>142k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-1910-flood-simulator/2026-10-21-cursor-claude-opus-5-5-medium/index.html) |
| Gemini 4 Argon medium | Cursor | 133k | 32.4 min<br>17.4 min thinking | 91 ✓<br>9 ✗ | 6.0M | $4.29 | UI ✓<br>Data 6/6 ✓<br>9.5k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-1910-flood-simulator/2026-10-22-cursor-gemini-4-argon-medium/index.html) |

**Local series `paris-1910-flood-simulator-claude-code`**: Claude Code, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 high | Claude Code | 358k | 43.1 min<br>29.1 min thinking | 169 ✓<br>8 ✗ | 32.2M | $8.86 | UI ✓<br>Data 6/6 ✓<br>146k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-1910-flood-simulator/2026-10-26-claude-code-claude-sonnet-5-5-high-2/index.html) |

### `paris-tree-canopy`

![paris-tree-canopy — Claude Sonnet 5.5 high (2026-10-24-cursor-claude-sonnet-5-5-high)](runs/paris-tree-canopy/2026-10-24-cursor-claude-sonnet-5-5-high/artifacts/screenshot.png)

**Local series `paris-tree-canopy-cursor`**: Cursor, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Haiku 5.5 high | Cursor | 80k | 6.4 min | 94 ✓<br>1 ✗ | 7.6M | $2.07 | UI ✗<br>Data 3/3 ✓<br>177k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-24-cursor-claude-haiku-5-5-high/index.html) |
| Claude Sonnet 5.5 high | Cursor | 200k | 23.2 min<br>10.3 min thinking | 72 ✓<br>3 ✗ | 9.9M | $6.20 | UI ✗<br>Data 3/3 ✓<br>254k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-24-cursor-claude-sonnet-5-5-high/index.html) |
| Composer 2.5 high | Cursor | 27k | 2.2 min<br>0.4 min thinking | 58 ✓<br>3 ✗ | 0.6M | $0.22 | UI ✗<br>Data 3/3 ✓<br>220k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-24-cursor-composer-2-5-high/index.html) |
| Gemini 3.8 Flash high | Cursor | 100k | 14.1 min<br>8.0 min thinking | 78 ✓<br>9 ✗ | 5.5M | $2.58 | UI ✗<br>Data 3/3 ✓<br>441k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-24-cursor-gemini-3-8-flash-high/index.html) |
| GPT-5.6 Luna high | Cursor | 20k | 2.7 min<br>0.3 min thinking | 14 ✓<br>0 ✗ | 0.2M | $0.10 | UI ✓<br>Data 0/3 ⚠<br>0 records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-24-cursor-gpt-5-6-luna-high/index.html) |

**Local series `paris-tree-canopy-claude-code`**: Claude Code, recorded with this repository ([`runs/`](runs/README.md)).

| Model | Harness | Output tokens (k) | Model time (min, tools excluded) | Tool calls (✓ / ✗) | Context re-read (M cached tokens) | Est. cost (USD) | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 medium | Claude Code | 105k | 16.2 min<br>6.1 min thinking | 73 ✓<br>6 ✗ | 7.9M | $5.14 | UI ✓<br>Data 2/3 ✓<br>34k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-26-claude-code-claude-opus-5-5-medium-2/index.html) |
| Claude Sonnet 5.5 high | Claude Code | 195k | 22.1 min<br>12.3 min thinking | 82 ✓<br>2 ✗ | 11.7M | $4.28 | UI ✓<br>Data 2/3 ✓<br>8.0k records<br>[Live Demo](https://loic-brissot.github.io/llm-frontier-evaluator-demos/demos/paris-tree-canopy/2026-10-26-claude-code-claude-sonnet-5-5-high-3/index.html) |
