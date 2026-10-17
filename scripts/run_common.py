"""Shared helpers for benchmark run setup and finish scripts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
TEMPLATES_DIR = ROOT / "templates"
PROMPTS_DIR = ROOT / "prompt"

# A prompt id is the stem of a file in prompt/: prompt/<prompt-id>.txt.
DEFAULT_PROMPT_ID = "paris-3d-atlas"
_PROMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RULES_VERSION = 1


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

HARNESS_NAMES = {"cursor", "claude-code", "codex", "other"}

# Effort (reasoning) levels proposed for each harness, in the order the
# harness presents them. "Claude" is the `claude-code` harness.
CURSOR_REASONING_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
CLAUDE_REASONING_LEVELS = ("low", "medium", "high", "ultra", "max", "ultracode")
# Harnesses without their own list keep the levels recorded before the
# per-harness lists existed, so older runs still validate.
DEFAULT_REASONING_LEVELS = ("low", "medium", "high", "xhigh", "none", "unknown")
REASONING_LEVELS_BY_HARNESS = {
    "cursor": CURSOR_REASONING_LEVELS,
    "claude-code": CLAUDE_REASONING_LEVELS,
}
# Every level a recorded run may hold, across all harnesses and older runs.
REASONING_LEVELS = {
    *CURSOR_REASONING_LEVELS,
    *CLAUDE_REASONING_LEVELS,
    *DEFAULT_REASONING_LEVELS,
}

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
        if run.get("harness", {}).get("name") == harness and run.get("series_id"):
            return str(run["series_id"])
    return f"{prompt_id or DEFAULT_PROMPT_ID}-{harness}"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def allocate_run_id(
    harness: str,
    model: str,
    reasoning: str,
    *,
    context: str | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    on_date: datetime | None = None,
) -> str:
    """Build `YYYY-MM-DD-<harness>-<model>-[<context>-]<reasoning>`.

    The context segment appears only for a Cursor harness, however the
    harness name is capitalised; it is never emitted for other harnesses.
    Uniqueness is checked inside runs/<prompt-id>/, so the same run id may
    exist once per prompt.
    """
    when = on_date or datetime.now()
    date_part = when.strftime("%Y-%m-%d")
    parts = [date_part, slugify(canonical_harness(harness)), slugify(model)]
    if is_cursor_harness(harness) and context and slugify(context):
        parts.append(slugify(context))
    parts.append(slugify(reasoning))
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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
