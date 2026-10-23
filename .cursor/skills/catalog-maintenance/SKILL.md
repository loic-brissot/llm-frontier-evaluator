---
name: catalog-maintenance
description: >-
  Maintain the prompt catalog, data-pipeline probe specifications, and model pricing
  reference data. Use when adding, updating, or removing a frozen prompt in prompt/,
  configuring verification probes in reference/prompt-probes.json, or adding/updating
  model token rates and providers in reference/pricing-2026-10-18.json.
---

# Catalog Maintenance Skill

This skill details how to maintain the prompt catalog (`prompt/`), data-pipeline probe specifications (`reference/prompt-probes.json`), and model pricing reference data (`reference/pricing-2026-10-18.json`).

---

## 1. Adding, Updating, or Removing a Frozen Prompt

A prompt file in `prompt/<prompt-id>.txt` is frozen. Once benchmark runs exist for a prompt, its content must **never** be edited in place. Changing prompt text requires creating a new prompt with a new prompt ID.

### Synchronized 4-File Checklist

When adding or removing a prompt, all 4 of the following files must be updated simultaneously:

1. **`prompt/<prompt-id>.txt`**:
   - Save the exact frozen prompt bytes. Use lowercase, hyphenated slug names (e.g., `france-road-accidents.txt`).

2. **`prompt/README.md`**:
   - Add/remove a row in the `## Current prompts` markdown table:
     - `Prompt id`: `` `<prompt-id>` ``
     - `File`: `` `<prompt-id>.txt` ``
     - `SHA-256`: Hash of exact bytes (`sha256sum prompt/<prompt-id>.txt` or `python3 -c "import hashlib; print(hashlib.sha256(open('prompt/<prompt-id>.txt','rb').read()).hexdigest())"`)
     - `Bytes`: Exact byte count (`wc -c prompt/<prompt-id>.txt`)
     - `Final newline`: `Yes` if the file ends with `\n`, otherwise `No`.

3. **`reference/prompt-probes.json`**:
   - Add/remove the prompt's probe specification object keyed by `<prompt-id>`:
     ```json
     "<prompt-id>": {
       "prompt_id": "<prompt-id>",
       "type": "open_data", // or "domain_model"
       "description": "Short description of target application",
       "checks": [
         {
           "id": "check_id",
           "description": "What this check verifies",
           "file_patterns": ["*pattern*"],
           "required_markers": ["marker1", "marker2"],
           "min_records": 100
         }
       ],
       "synthetic_patterns": [
         "generateMockData",
         "fakeData"
       ]
     }
     ```

4. **`README.md`**:
   - Add/remove entry under the `## Prompts` numbered list:
     `N. [`<prompt-id>`](prompt/<prompt-id>.txt): Short summary of prompt objectives.`

### Checking Default Prompt References
If the repository default prompt changes:
- Check `DEFAULT_PROMPT_ID` in `scripts/run_common.py`.
- Update prompt references in `templates/run.json` if applicable.

---

## 2. Adding or Updating Model Pricing (`reference/pricing-2026-10-18.json`)

Model rates and providers live in `reference/pricing-2026-10-18.json`. `scripts/finish_run.py` uses this file to compute token pricing and harness surcharges.

### Required Model Entry Fields
Each entry in `"models": [...]` requires:
- `id`: Unique model identifier slug (e.g. `claude-opus-5-5`, `gemini-4-argon`, `grok-4-7`).
- `names`: List of alternative display names and slugs matched case-insensitively.
- `provider`: Provider ID (`anthropic`, `openai`, `google`, `xai`, `cursor`, `meta`, `moonshot`, `zai`, etc.).
- `harnesses`: List of supported harnesses (`["cursor", "claude-code"]`, `["codex", "cursor"]`, etc.).
- Token rates per 1M USD (formatted as fixed-decimal strings):
  - `input`: Rate per 1M uncached input tokens.
  - `cache_write`: Rate per 1M cache-write tokens.
  - `cache_read`: Rate per 1M cache-read tokens.
  - `output`: Rate per 1M output tokens.

### Optional Pricing Fields
- `first_party_in_cursor`: `true` for Cursor first-party models (`grok-4-7`, `composer-2-5`) exempt from the $0.25/1M Cursor Token Rate surcharge.
- `context_variants`: Object mapping context keys (e.g., `"500k"`, `"1m"`) to rate overrides.
- `long_context`: Object defining `"threshold_input_tokens"` (e.g., `200000`) and rate overrides when input tokens exceed the threshold.

### Code Verification
When adding or modifying a model entry:
- Check provider inference in `infer_provider()` (`scripts/run_common.py`).
- Check model lookup in `lookup_model_pricing()` (`scripts/run_common.py`).

---

## 3. Verification Commands

After performing catalog maintenance, run the complete suite of verification tools:

```bash
# Check prompt catalog hashes and model pricing consistency
uv run python3 scripts/compare_runs.py

# Check README comparison table sync
uv run python3 scripts/compare_runs.py --check-readme

# Run unit tests
uv run python3 -m unittest discover -s tests -v
uv run pytest

# Code formatting and linting
uv run ruff check scripts tests
# Or inside Cursor sandbox:
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --index-url https://pypi.org/simple ruff check scripts tests
```
