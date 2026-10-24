---
id: m-6
title: "Headless Claude Code CLI Harness Integration"
---

## Description

Enable and verify end-to-end headless (`claude -p`) and interactive / subscription-authenticated (`claude` without `ANTHROPIC_API_KEY`) benchmark runs using the Claude Code CLI harness, including model alias resolution, clean-room `.claude/settings.json` isolation hooks, scripted Docker/host launchers, `stream-json` and session-transcript timing/thinking/tool telemetry in `tool_events.py`, and session resume on stalls.
