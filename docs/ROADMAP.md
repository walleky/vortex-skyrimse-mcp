# Improvement Notes

These are useful next steps, ordered by value and risk.

## Best Next Improvements

1. Add a live Skyrim evidence bridge: screenshot/OCR for popups, plus optional SKSE/console telemetry for current cell and clicked FormID.
2. Add Nexus GraphQL file-content search behind an explicit read-only flag for "which Nexus mod contains this plugin/script/mesh?" questions.
3. Add more plugin metadata parsing for ESP/ESM headers beyond masters, such as plugin version and record counts.
4. Add a tiny local HTML report viewer for generated JSON/Markdown/CSV outputs.
5. Add richer Vortex collection detection if Vortex exposes more stable CLI paths.
6. Add a synthetic Vortex profile fixture so profile/deployment behavior can be tested without a real Vortex install.
7. Add a profile restore apply helper in the local menu only after the preview UX is clear enough for nontechnical users.

## Recently Added

- Read-only xEdit/SSEEdit target hints from FormIDs and plugin names.
- Read-only xEdit/SSEEdit inspection script generation plus CSV result parsing.
- Read-only Vortex collection-state inspection and collection manifest matching.
- Local mod-summary scan cache for repeated large-collection diagnostics.
- Conflict risk explanations and safer next-action text.

## What Not To Automate Yet

- Do not auto-delete redundant mods.
- Do not auto-sort load order.
- Do not auto-write Vortex conflict rules.
- Do not auto-disable mods from broad guesses.
- Do not trigger deployment, installs, updates, removals, load-order writes, or Nexus account actions from outside Vortex until there is a stable supported API path.
- Do not read, copy, or reuse Vortex's Nexus API key.
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
- Teach OpenClaw to prefer `skyrim_diagnostics_report` for the broadest no-hassle first pass.
- Teach OpenClaw to use `nexus_validate_key` and `nexus_update_report` only as read-only metadata helpers.
- Teach OpenClaw to use `scan_cache_status` when repeated scans are slow or stale.
- Teach OpenClaw to use `xedit_diagnostics_report` as a read-only inspection target helper, then `xedit_inspection_script` and `xedit_inspection_result_report` when record evidence is needed.
- Teach OpenClaw to use `vortex_collection_report` and `collection_local_match_report` for collection drift context, not automatic updates.
- Teach slower OpenClaw models to use `performance_mode=slow_model` and read summary/findings before nested sections.
- Teach OpenClaw to call `validate_setup` before diagnosis and `vortex_profile_backup` before profile experiments.
- Teach OpenClaw to call `mod_knowledge_report` before suggesting collection cleanup.
- Teach OpenClaw to call `in_game_issue_report` when the user asks about a visible object, location-specific problem, or popup.
- Teach OpenClaw to run popup triage from natural language first, then ask for screenshot/OCR or exact text only when candidates are weak.
- Teach OpenClaw to read `docs/OPENCLAW-AGENT-GUIDE.md` before applying any profile or INI write.
- Prefer one-shot `skyrim_modded_play_report` for first diagnosis, then narrower tools.
- Keep direct CLI commands working for no-OpenClaw recovery and report generation.
- Keep final answers short and action-oriented for nontechnical users.
