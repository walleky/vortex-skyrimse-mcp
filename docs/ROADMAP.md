# Improvement Notes

These are useful next steps, ordered by value and risk.

## Best Next Improvements

1. Add a live Skyrim evidence bridge: screenshot/OCR for popups, plus optional SKSE/console telemetry for current cell and clicked FormID.
2. Add richer Vortex collection detection if Vortex exposes collection state through stable CLI paths.
3. Add more plugin metadata parsing for ESP/ESM headers beyond masters, such as plugin version and record counts.
4. Add a read-only xEdit/SSEEdit integration for cell, reference, quest, and message lookup.
5. Add a tiny local HTML report viewer for generated JSON/Markdown outputs.
6. Add Nexus/Vortex collection manifest detection if stable local collection metadata is available.
7. Add a synthetic Vortex profile fixture so profile/deployment behavior can be tested without a real Vortex install.
8. Add a profile restore apply helper in the local menu only after the preview UX is clear enough for nontechnical users.

## What Not To Automate Yet

- Do not auto-delete redundant mods.
- Do not auto-sort load order.
- Do not auto-write Vortex conflict rules.
- Do not auto-disable mods from broad guesses.
- Do not trigger deployment, installs, updates, removals, load-order writes, or Nexus account actions from outside Vortex until there is a stable supported API path.
- Do not edit plugin records or delete placed references automatically from a natural-language in-game report.

Those actions can break saves. Keep them as reports or dry-run plans until the evidence is strong and the user approves.

## Code Health Improvements

- Split `server.py` into modules once it becomes painful to navigate:
  - `paths.py`
  - `logging_support.py`
  - `vortex_cli.py`
  - `mods.py`
  - `plugins.py`
  - `profiles.py`
  - `mcp_server.py`
- Keep the current single-file shape while rapid iteration is more useful than packaging polish.
- Expand `tests/smoke_mcp.py` into fixture-based tests before making larger refactors.

## OpenClaw Experience Improvements

- Teach OpenClaw to call `bug_report_bundle` automatically after any tool exception.
- Teach OpenClaw to call `safe_session_report` as the default first response for broad "something is broken" requests.
- Teach OpenClaw to call `validate_setup` before diagnosis and `vortex_profile_backup` before profile experiments.
- Teach OpenClaw to call `mod_knowledge_report` before suggesting collection cleanup.
- Teach OpenClaw to call `in_game_issue_report` when the user asks about a visible object, location-specific problem, or popup.
- Teach OpenClaw to run popup triage from natural language first, then ask for screenshot/OCR or exact text only when candidates are weak.
- Teach OpenClaw to read `docs/OPENCLAW-AGENT-GUIDE.md` before applying any profile or INI write.
- Prefer one-shot `skyrim_modded_play_report` for first diagnosis, then narrower tools.
- Keep direct CLI commands working for no-OpenClaw recovery and report generation.
- Keep final answers short and action-oriented for nontechnical users.
