"""Harness adapters for LLM frontier evaluator.

Provides a unified interface across supported benchmark execution harnesses
(Cursor and Claude Code), encapsulating CLI command construction, clean-room
hook installation, session setup, stream/transcript normalization, and token/usage extraction.
"""

from __future__ import annotations

from harnesses.base import HarnessAdapter
from harnesses.claude_code import (
    CLAUDE_AUTH_CACHE_DIR_NAME,
    CLAUDE_AUTH_STATE_KEYS,
    CLAUDE_CONTAINER_CONFIG_DIR,
    CLAUDE_CREDENTIALS_FILE,
    CLAUDE_DOCKER_IMAGE,
    CLAUDE_GLOBAL_STATE_FILE,
    CLAUDE_HOOK_DIR_NAME,
    CLAUDE_LAUNCH_MODES,
    ClaudeCodeAdapter,
    build_claude_launcher_script,
    claude_auth_failure_in_stream,
    claude_cli_model_id,
    claude_oauth_credentials_available,
    claude_state_dir_for_run,
    claude_uses_oauth_token,
    create_claude_clean_room_launcher,
    default_claude_auth_cache_dir,
    filter_claude_global_state,
    install_claude_hook,
    persist_claude_auth_state,
    resolve_claude_code_model_and_effort,
    seed_claude_auth_state,
)
from harnesses.cursor import (
    CURSOR_HOOK_DIR_NAME,
    CursorAdapter,
    create_clean_room_launcher,
    fetch_cursor_available_models,
    install_cursor_hook,
    resolve_cursor_model_slug,
)

_ADAPTERS: dict[str, HarnessAdapter] = {
    "cursor": CursorAdapter(),
    "claude-code": ClaudeCodeAdapter(),
}


def get_harness_adapter(harness: str | None) -> HarnessAdapter:
    """Return the HarnessAdapter for the given harness name or alias (default: Cursor)."""
    if not harness:
        return _ADAPTERS["cursor"]
    canonical = harness.strip().lower()
    if canonical in _ADAPTERS:
        return _ADAPTERS[canonical]
    for adapter in _ADAPTERS.values():
        if canonical in adapter.aliases:
            return adapter
    # Fallback to cursor adapter for cursor-like / unknown harnesses
    return _ADAPTERS["cursor"]


def register_harness_adapter(adapter: HarnessAdapter) -> None:
    """Register a new HarnessAdapter instance."""
    _ADAPTERS[adapter.name] = adapter


__all__ = [
    "CLAUDE_AUTH_CACHE_DIR_NAME",
    "CLAUDE_AUTH_STATE_KEYS",
    "CLAUDE_CONTAINER_CONFIG_DIR",
    "CLAUDE_CREDENTIALS_FILE",
    "CLAUDE_DOCKER_IMAGE",
    "CLAUDE_GLOBAL_STATE_FILE",
    "CLAUDE_HOOK_DIR_NAME",
    "CLAUDE_LAUNCH_MODES",
    "CURSOR_HOOK_DIR_NAME",
    "ClaudeCodeAdapter",
    "CursorAdapter",
    "HarnessAdapter",
    "build_claude_launcher_script",
    "claude_auth_failure_in_stream",
    "claude_cli_model_id",
    "claude_oauth_credentials_available",
    "claude_state_dir_for_run",
    "claude_uses_oauth_token",
    "create_claude_clean_room_launcher",
    "create_clean_room_launcher",
    "default_claude_auth_cache_dir",
    "fetch_cursor_available_models",
    "filter_claude_global_state",
    "get_harness_adapter",
    "install_claude_hook",
    "install_cursor_hook",
    "persist_claude_auth_state",
    "register_harness_adapter",
    "resolve_claude_code_model_and_effort",
    "resolve_cursor_model_slug",
    "seed_claude_auth_state",
]
