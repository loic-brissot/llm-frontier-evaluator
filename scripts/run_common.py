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
) -> str:
    """Build `YYYY-MM-DD-<harness>-<model>-[<context>-]<reasoning>`.

    The context segment appears only for a Cursor harness, however the
    harness name is capitalised; it is never emitted for other harnesses.
    Context is optional even for Cursor: `None`, blank, or `null` emits
    no segment. Reasoning is optional too: `None`, blank, or `null`
    falls back to `unknown`, so the reasoning segment is always present.
    Uniqueness is checked inside runs/<prompt-id>/, so the same run id
    may exist once per prompt.
    """
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


def lookup_model_pricing(
    model_name: str,
    *,
    context: str | None = None,
    harness: str | None = None,
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

    result = {
        "model_id": matched["id"],
        "as_of": pricing.get("as_of"),
        "input": Decimal(str(matched.get("input", "0"))),
        "cache_write": Decimal(str(matched.get("cache_write", "0"))),
        "cache_read": Decimal(str(matched.get("cache_read", "0"))),
        "output": Decimal(str(matched.get("output", "0"))),
    }
    variants = matched.get("context_variants")
    if context and isinstance(variants, dict):
        ctx_key = context.strip().lower()
        variant = variants.get(ctx_key)
        if isinstance(variant, dict):
            for key in ("input", "cache_write", "cache_read", "output"):
                if key in variant:
                    result[key] = Decimal(str(variant[key]))
            result["context_variant"] = ctx_key
    return result


def estimate_token_cost(
    model_name: str,
    *,
    uncached_input_tokens: int | Decimal = 0,
    cache_write_tokens: int | Decimal = 0,
    cache_read_tokens: int | Decimal = 0,
    output_tokens: int | Decimal = 0,
    context: str | None = None,
    harness: str | None = None,
) -> dict | None:
    """Compute estimated USD cost from public per-1M-token rates."""
    rates = lookup_model_pricing(model_name, context=context, harness=harness)
    if rates is None:
        return None
    million = Decimal(1_000_000)
    u = Decimal(uncached_input_tokens or 0)
    cw = Decimal(cache_write_tokens or 0)
    cr = Decimal(cache_read_tokens or 0)
    out = Decimal(output_tokens or 0)
    cost = (
        u * rates["input"]
        + cw * rates["cache_write"]
        + cr * rates["cache_read"]
        + out * rates["output"]
    ) / million
    return {
        "as_of": rates["as_of"],
        "model_id": rates["model_id"],
        "context_variant": rates.get("context_variant"),
        "rates_per_1m_usd": {
            "input": str(rates["input"]),
            "cache_write": str(rates["cache_write"]),
            "cache_read": str(rates["cache_read"]),
            "output": str(rates["output"]),
        },
        "estimated_cost_usd": str(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }

