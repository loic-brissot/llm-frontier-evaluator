"""Shared helpers for benchmark run setup and finish scripts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import site
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
RUNS_DIR = ROOT / "runs"
TEMPLATES_DIR = ROOT / "templates"
PROMPTS_DIR = ROOT / "prompt"
SCHEMA_PATH = ROOT / "schema" / "run.schema.json"
PRICING_PATH = ROOT / "reference" / "pricing-2026-10-18.json"

# The run schema is the single source for enums and defaults below.
RUN_SCHEMA: dict = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_SCHEMA_DEFS: dict = RUN_SCHEMA["$defs"]


def _schema_enum(name: str) -> tuple[str, ...]:
    return tuple(value for value in _SCHEMA_DEFS[name]["enum"] if value is not None)


# A prompt id is the stem of a file in prompt/: prompt/<prompt-id>.txt.
DEFAULT_PROMPT_ID = "paris-3d-atlas"
_PROMPT_ID_RE = re.compile(RUN_SCHEMA["properties"]["prompt_id"]["pattern"])
RULES_VERSION = RUN_SCHEMA["properties"]["rules_version"]["default"]
HOOK_TIME_SOURCE = "wall_clock_minus_tool_time"

BUCKETS: tuple[str, ...] = tuple(RUN_SCHEMA["properties"]["tool_calls"]["required"])
# The four chart columns; `other` is printed under the table.
CHART_BUCKETS: tuple[str, ...] = tuple(name for name in BUCKETS if name != "other")
SPLIT_RULES = _schema_enum("splitRule")
TIME_SOURCES = _schema_enum("modelTimeSource")
CACHE_SOURCES = _schema_enum("cacheSource")


def prompt_path(prompt_id: str) -> Path:
    return PROMPTS_DIR / f"{prompt_id}.txt"


def is_valid_prompt_id(prompt_id: object) -> bool:
    return isinstance(prompt_id, str) and bool(_PROMPT_ID_RE.match(prompt_id))


def available_prompt_ids() -> list[str]:
    if not PROMPTS_DIR.is_dir():
        return []
    return sorted(path.stem for path in PROMPTS_DIR.glob("*.txt") if path.is_file())


def require_prompt_id(prompt_id: str) -> str:
    """Validate that `prompt_id` names an existing prompt/<prompt-id>.txt."""
    if not is_valid_prompt_id(prompt_id):
        raise ValueError(
            f"Prompt id {prompt_id!r} is invalid: use lowercase letters, digits, '-' or '_', "
            "starting with a letter or digit (it is the file name without .txt)."
        )
    if not prompt_path(prompt_id).is_file():
        known = ", ".join(available_prompt_ids()) or "(none)"
        raise ValueError(f"Unknown prompt id {prompt_id!r}. Available prompts: {known}")
    return prompt_id


def prompt_sha256(prompt_id: str) -> str:
    return hashlib.sha256(prompt_path(prompt_id).read_bytes()).hexdigest()


def run_dir_for(prompt_id: str, run_id: str) -> Path:
    return RUNS_DIR / prompt_id / run_id


def find_run_dir(run_id: str, prompt_id: str | None = None) -> Path:
    """Locate runs/<prompt-id>/<run-id>/, optionally scoped to one prompt.

    `run_id` may also be given as `<prompt-id>/<run-id>`.
    """
    if prompt_id is None and "/" in run_id:
        prompt_id, run_id = run_id.split("/", 1)
    if prompt_id is not None:
        candidate = run_dir_for(prompt_id, run_id)
        if (candidate / "run.json").is_file():
            return candidate
        raise FileNotFoundError(f"No run.json in {candidate}")
    matches = [
        path.parent
        for path in sorted(RUNS_DIR.glob(f"*/{run_id}/run.json"))
        if path.is_file()
    ]
    if not matches:
        raise FileNotFoundError(f"No run {run_id!r} found under runs/<prompt-id>/")
    if len(matches) > 1:
        listed = ", ".join(str(path.relative_to(ROOT)) for path in matches)
        raise ValueError(f"Run id {run_id!r} exists for several prompts ({listed}); pass --prompt.")
    return matches[0]


# Convenience handle for the default prompt; prefer prompt_path(prompt_id)
# whenever a run's own prompt is known.
PROMPT_PATH = prompt_path(DEFAULT_PROMPT_ID)
PROMPT_ID = DEFAULT_PROMPT_ID

HARNESS_NAMES = set(_schema_enum("harnessName"))

# Effort (reasoning) levels proposed for each harness, in the order the
# harness presents them. "Claude" is the `claude-code` harness.
CURSOR_REASONING_LEVELS = _schema_enum("cursorReasoning")
CLAUDE_REASONING_LEVELS = _schema_enum("claudeCodeReasoning")
# Harnesses without their own list keep the levels recorded before the
# per-harness lists existed, so older runs still validate.
DEFAULT_REASONING_LEVELS = _schema_enum("defaultReasoning")
REASONING_LEVELS_BY_HARNESS = {
    "cursor": CURSOR_REASONING_LEVELS,
    "claude-code": CLAUDE_REASONING_LEVELS,
}
# Reasoning is optional: it cannot be tuned or reported in every
# configuration. An unfilled reasoning level is recorded as this default;
# `None`/null is accepted as the same "not set" value.
UNKNOWN_REASONING: str = _SCHEMA_DEFS["reasoningLevel"]["default"]

# Every level a recorded run may hold, across all harnesses and older runs.
REASONING_LEVELS = set(_schema_enum("reasoningLevel"))

_HARNESS_ALIASES = {
    "claude": "claude-code",
    "claude code": "claude-code",
    "claude-code": "claude-code",
    "codex app": "codex",
}


def canonical_harness(harness: str) -> str:
    """Return the lowercase canonical harness name (``Cursor`` -> ``cursor``)."""
    value = harness.strip().lower()
    return _HARNESS_ALIASES.get(value, value)


def is_cursor_harness(harness: str) -> bool:
    return canonical_harness(harness) == "cursor"


def reasoning_levels_for_harness(harness: str) -> tuple[str, ...]:
    """Effort levels proposed for a harness, matched case-insensitively."""
    return REASONING_LEVELS_BY_HARNESS.get(
        canonical_harness(harness), DEFAULT_REASONING_LEVELS
    )

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "sk-[REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]+", re.I), "Bearer [REDACTED]"),
    (
        re.compile(
            r'("(?:api[_-]?key|authorization|token|secret|password)"\s*:\s*)"(?:[^"\\]|\\.)*"',
            re.I,
        ),
        r'\1"[REDACTED]"',
    ),
]


def slugify(value: str) -> str:
    text = value.lower().strip()
    text = text.replace(".", "-").replace(" ", "-").replace("_", "-")
    text = re.sub(r"[^a-z0-9-]+", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "model"


def infer_provider(model_name: str) -> str | None:
    if not model_name or not isinstance(model_name, str) or not model_name.strip():
        return None

    pricing_match = lookup_model_pricing(model_name)
    if pricing_match and pricing_match.get("provider"):
        prov = str(pricing_match["provider"]).strip().lower()
        if prov:
            return prov

    pricing_data = load_pricing()
    models = pricing_data.get("models")
    if isinstance(models, list):
        target_lower = model_name.strip().lower()
        target_slug = slugify(model_name)
        for entry in models:
            if not isinstance(entry, dict) or not entry.get("provider"):
                continue
            provider = str(entry["provider"]).strip().lower()
            names = [entry.get("id", "")] + list(entry.get("names") or [])
            for candidate in names:
                if not isinstance(candidate, str) or not candidate:
                    continue
                cand_lower = candidate.strip().lower()
                cand_slug = slugify(candidate)
                if (
                    cand_lower in target_lower
                    or target_lower in cand_lower
                    or cand_slug in target_slug
                    or target_slug in cand_slug
                ):
                    return provider

    lower = model_name.lower()
    if "composer" in lower:
        return "cursor"
    if any(token in lower for token in ("claude", "opus", "sonnet", "haiku")):
        return "anthropic"
    if any(token in lower for token in ("gpt", "codex", "o1", "o3", "o4")):
        return "openai"
    if "gemini" in lower:
        return "google"
    if "grok" in lower:
        return "xai"
    if any(token in lower for token in ("muse", "llama")):
        return "meta"
    if "kimi" in lower:
        return "moonshot"
    if "glm" in lower:
        return "zai"

    return None


def default_series_id(harness: str, prompt_id: str | None = None) -> str:
    for path in sorted(RUNS_DIR.glob("*/*/run.json"), reverse=True):
        try:
            run = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if prompt_id is not None and run.get("prompt_id") != prompt_id:
            continue
        # A series shares one rules_version (docs/protocol.md).
        if run.get("rules_version") != RULES_VERSION:
            continue
        if run.get("harness", {}).get("name") == harness and run.get("series_id"):
            return str(run["series_id"])
    return f"{prompt_id or DEFAULT_PROMPT_ID}-{harness}"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def preferred_python() -> str:
    """Return the workspace .venv interpreter when present, else sys.executable."""
    for rel in (Path(".venv/bin/python3"), Path(".venv/bin/python"), Path(".venv/Scripts/python.exe")):
        candidate = ROOT / rel
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _add_venv_site_packages() -> None:
    """Add workspace .venv site-packages to sys.path when running outside .venv."""
    venv_dir = ROOT / ".venv"
    if not venv_dir.is_dir():
        return
    for site_dir in sorted(venv_dir.glob("lib/python*/site-packages")):
        if site_dir.is_dir():
            site.addsitedir(str(site_dir))
    win_site = venv_dir / "Lib" / "site-packages"
    if win_site.is_dir():
        site.addsitedir(str(win_site))


@lru_cache(maxsize=1)
def _run_validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        _add_venv_site_packages()
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise RuntimeError(
                "Validating run.json needs the jsonschema package: "
                "python3 -m pip install -r requirements.txt"
            ) from exc
    Draft202012Validator.check_schema(RUN_SCHEMA)
    return Draft202012Validator(RUN_SCHEMA)


def run_schema_errors(run: object) -> list[str]:
    """Validate one run record against schema/run.schema.json."""
    errors = sorted(
        _run_validator().iter_errors(run),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '(root)'}: {error.message}"
        for error in errors
    ]


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def allocate_run_id(
    harness: str,
    model: str,
    reasoning: str | None,
    *,
    context: str | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    on_date: datetime | None = None,
    shot: str = "primary",
    parent_run_id: str | None = None,
) -> str:
    """Build `YYYY-MM-DD-<harness>-<model>-[<context>-]<reasoning>`.

    The context segment appears only for a Cursor harness, however the
    harness name is capitalised; it is never emitted for other harnesses.
    Context is optional even for Cursor: `None`, blank, or `null` emits
    no segment. Reasoning is optional too: `None`, blank, or `null`
    falls back to `unknown`, so the reasoning segment is always present.
    Uniqueness is checked inside runs/<prompt-id>/, so the same run id
    may exist once per prompt.

    On a follow-up run (shot="follow-up" or parent_run_id provided),
    the run id ends in `-follow-up` (e.g. `<parent_run_id>-follow-up`, or
    `<parent_run_id>-2-follow-up` if `<parent_run_id>-follow-up` exists).
    """
    if shot == "follow-up" or parent_run_id is not None:
        if not parent_run_id:
            raise ValueError("parent_run_id must be specified for follow-up runs")
        base = parent_run_id if parent_run_id.endswith("-follow-up") else f"{parent_run_id}-follow-up"
        candidate = base
        suffix = 2
        while run_dir_for(prompt_id, candidate).exists():
            if base.endswith("-follow-up"):
                candidate = f"{base[:-10]}-{suffix}-follow-up"
            else:
                candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    when = on_date or datetime.now()
    date_part = when.strftime("%Y-%m-%d")
    parts = [date_part, slugify(canonical_harness(harness)), slugify(model)]
    context_value = context.strip() if context else ""
    if is_cursor_harness(harness) and context_value and context_value.lower() != "null":
        parts.append(slugify(context_value))
    reasoning_value = reasoning.strip().lower() if reasoning else ""
    if reasoning_value in {"", "null"}:
        reasoning_value = UNKNOWN_REASONING
    parts.append(slugify(reasoning_value))
    base = "-".join(parts)
    candidate = base
    suffix = 2
    while run_dir_for(prompt_id, candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def scrub_text(text: str) -> tuple[str, int]:
    redactions = 0
    cleaned = text
    for pattern, replacement in SECRET_PATTERNS:
        cleaned, count = pattern.subn(replacement, cleaned)
        redactions += count
    return cleaned, redactions


def scrub_path(path: Path) -> int:
    if not path.is_file():
        return 0
    original = path.read_text(encoding="utf-8")
    cleaned, redactions = scrub_text(original)
    if cleaned != original:
        path.write_text(cleaned, encoding="utf-8")
    return redactions


def copy_usage_export(source: Path, usage_dir: Path) -> list[Path]:
    usage_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    if source.is_file():
        target = usage_dir / source.name
        shutil.copy2(source, target)
        copied.append(target)
        return copied
    if source.is_dir():
        for item in sorted(source.iterdir()):
            if item.is_file():
                target = usage_dir / item.name
                shutil.copy2(item, target)
                copied.append(target)
        return copied
    raise FileNotFoundError(f"Usage export not found: {source}")


def discover_run_dirs(prompt_id: str | None = None) -> list[Path]:
    if not RUNS_DIR.is_dir():
        return []
    pattern = f"{prompt_id}/*/run.json" if prompt_id else "*/*/run.json"
    dirs = [path.parent for path in RUNS_DIR.glob(pattern) if path.is_file()]
    return sorted(dirs, key=lambda path: (path.name, path.parent.name), reverse=True)


def utc_now_iso() -> str:
    now = datetime.now(timezone.utc)
    if now.microsecond == 0:
        return now.isoformat(timespec="seconds").replace("+00:00", "Z")
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    if not PRICING_PATH.is_file():
        return {}
    return load_json(PRICING_PATH)


def _parse_context_tokens(context: str | None) -> int | None:
    if not isinstance(context, str):
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([km])\s*$", context.strip().lower())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    return int(val * (1_000_000 if unit == "m" else 1_000))


def lookup_model_pricing(
    model_name: str,
    *,
    context: str | None = None,
    harness: str | None = None,
    total_input_tokens: int | Decimal | None = None,
    use_long_context: bool | None = None,
) -> dict | None:
    """Find the pricing entry in reference/pricing-2026-10-18.json for `model_name`."""
    pricing = load_pricing()
    models = pricing.get("models")
    if not isinstance(models, list) or not model_name:
        return None
    target_slug = slugify(model_name)
    target_lower = model_name.strip().lower()
    matched: dict | None = None
    for entry in models:
        if not isinstance(entry, dict):
            continue
        names = [entry.get("id", "")] + list(entry.get("names") or [])
        for candidate in names:
            if not isinstance(candidate, str) or not candidate:
                continue
            if candidate.strip().lower() == target_lower or slugify(candidate) == target_slug:
                matched = entry
                break
        if matched is not None:
            break
    if matched is None:
        # Prefix match fallback (e.g., gemini-4-argon-medium -> gemini-4-argon)
        for entry in models:
            if not isinstance(entry, dict):
                continue
            entry_id = slugify(str(entry.get("id", "")))
            if entry_id and target_slug.startswith(entry_id + "-"):
                matched = entry
                break
    if matched is None:
        return None

    input_rate = Decimal(str(matched.get("input", "0")))
    cache_write_rate = Decimal(str(matched.get("cache_write", "0")))
    cache_read_rate = Decimal(str(matched.get("cache_read", "0")))
    output_rate = Decimal(str(matched.get("output", "0")))

    context_variant_applied = None
    variants = matched.get("context_variants")
    if context and isinstance(variants, dict):
        ctx_key = context.strip().lower()
        variant = variants.get(ctx_key)
        if isinstance(variant, dict):
            if "input" in variant:
                input_rate = Decimal(str(variant["input"]))
            if "cache_write" in variant:
                cache_write_rate = Decimal(str(variant["cache_write"]))
            if "cache_read" in variant:
                cache_read_rate = Decimal(str(variant["cache_read"]))
            if "output" in variant:
                output_rate = Decimal(str(variant["output"]))
            context_variant_applied = ctx_key

    long_context_applied = False
    lc = matched.get("long_context")
    ctx_tokens = _parse_context_tokens(context)
    if isinstance(lc, dict):
        threshold = lc.get("threshold_input_tokens")
        if context_variant_applied is not None:
            if threshold is not None and ctx_tokens is not None and ctx_tokens > int(threshold):
                long_context_applied = True
        else:
            should_apply = False
            if use_long_context is True:
                should_apply = True
            elif use_long_context is not False and threshold is not None:
                if total_input_tokens is not None and Decimal(str(total_input_tokens)) > Decimal(str(threshold)):
                    should_apply = True
                elif ctx_tokens is not None and ctx_tokens > int(threshold):
                    should_apply = True
            if should_apply:
                if "input" in lc:
                    input_rate = Decimal(str(lc["input"]))
                if "cache_write" in lc:
                    cache_write_rate = Decimal(str(lc["cache_write"]))
                if "cache_read" in lc:
                    cache_read_rate = Decimal(str(lc["cache_read"]))
                if "output" in lc:
                    output_rate = Decimal(str(lc["output"]))
                long_context_applied = True

    harness_surcharge_rate = Decimal("0")
    canon_harness = canonical_harness(harness) if harness else None
    if canon_harness:
        harnesses_cfg = pricing.get("harnesses") or {}
        harness_info = harnesses_cfg.get(canon_harness) or {}
        third_party_rate = Decimal(str(harness_info.get("third_party_token_rate_per_1m", "0")))

        provider = str(matched.get("provider") or "").lower()
        first_party_providers = [
            str(p).lower() for p in (harness_info.get("first_party_providers") or [])
        ]
        is_first_party = (
            (canon_harness == "cursor" and matched.get("first_party_in_cursor") is True)
            or (provider in first_party_providers)
            or (provider == canon_harness)
        )
        if not is_first_party:
            harness_surcharge_rate = third_party_rate

    return {
        "as_of": pricing.get("as_of"),
        "model_id": matched["id"],
        "provider": matched.get("provider"),
        "input": input_rate,
        "cache_write": cache_write_rate,
        "cache_read": cache_read_rate,
        "output": output_rate,
        "context_variant": context_variant_applied,
        "long_context_applied": long_context_applied,
        "harness": canon_harness,
        "harness_token_rate_per_1m": harness_surcharge_rate,
    }


def estimate_token_cost(
    model_name: str,
    *,
    uncached_input_tokens: int | Decimal = 0,
    cache_write_tokens: int | Decimal = 0,
    cache_read_tokens: int | Decimal = 0,
    output_tokens: int | Decimal = 0,
    context: str | None = None,
    harness: str | None = None,
    total_input_tokens: int | Decimal | None = None,
    use_long_context: bool | None = None,
) -> dict | None:
    """Compute estimated USD cost from public per-1M-token rates and harness surcharges."""
    u = Decimal(uncached_input_tokens or 0)
    cw = Decimal(cache_write_tokens or 0)
    cr = Decimal(cache_read_tokens or 0)
    out = Decimal(output_tokens or 0)
    total_input = u + cw + cr
    total_tokens = total_input + out

    rates = lookup_model_pricing(
        model_name,
        context=context,
        harness=harness,
        total_input_tokens=total_input_tokens,
        use_long_context=use_long_context,
    )
    if rates is None:
        return None
    million = Decimal(1_000_000)
    base_cost = (
        u * rates["input"]
        + cw * rates["cache_write"]
        + cr * rates["cache_read"]
        + out * rates["output"]
    ) / million
    harness_surcharge = (total_tokens * rates["harness_token_rate_per_1m"]) / million
    total_cost_with_harness = base_cost + harness_surcharge

    est_base = base_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    est_surcharge = harness_surcharge.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    est_total = total_cost_with_harness.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "as_of": rates["as_of"],
        "model_id": rates["model_id"],
        "context_variant": rates.get("context_variant"),
        "long_context_applied": rates.get("long_context_applied", False),
        "harness": rates.get("harness"),
        "harness_token_rate_per_1m": str(rates["harness_token_rate_per_1m"]),
        "harness_surcharge_usd": str(est_surcharge),
        "rates_per_1m_usd": {
            "input": str(rates["input"]),
            "cache_write": str(rates["cache_write"]),
            "cache_read": str(rates["cache_read"]),
            "output": str(rates["output"]),
        },
        "estimated_cost_usd": str(est_base),
        "estimated_cost_with_harness_usd": str(est_total),
    }

