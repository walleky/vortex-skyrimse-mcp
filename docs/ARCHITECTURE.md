# Architecture

This repo is intentionally small: one dependency-free Python MCP/CLI server, PowerShell helpers, and tests.

## Runtime Shape

```text
OpenClaw or MCP client
  -> stdio JSON-RPC
  -> server.py
      -> detect local Steam/Vortex/Skyrim paths
      -> when running in WSL2, map Windows drive paths to /mnt/<drive>
      -> inspect staging folders, plugins, INIs, profiles, conflicts
      -> inspect MO2 instance/profile files and approximate virtual Data views
      -> optionally recommend a safe workflow from a plain-language problem
      -> optionally inspect Skyrim/Papyrus/SKSE/crash runtime logs
      -> optionally poll newly appended runtime log text with saved cursors
      -> optionally enrich reports with read-only Nexus Mods metadata
      -> optionally use local scan cache, xEdit target hints, and collection diagnostics
      -> optionally call Vortex.exe --get/--set for profile state
      -> return structured JSON to the MCP client

PowerShell or cmd
  -> server.py --tool NAME / --mod-knowledge
      -> same tool functions
      -> JSON result on stdout and optional report files on disk
```

The server must never write normal logs to stdout because stdout is the MCP protocol stream. Logs go to files, and unexpected diagnostics go to stderr.

## Main Files

- `server.py`: MCP server, direct CLI, tool implementations, logging, and stdio loop.
- `server.py --tool ...`: direct CLI mode for no-MCP workflows.
- `install_windows.ps1`: finds Python and prints a ready-to-copy MCP config snippet.
- `install_wsl.sh`: finds WSL Python and prints a ready-to-copy OpenClaw config for WSL2.
- `mcp_doctor.ps1`: runs self-tests, smoke tests, config generation, optional OpenClaw registration, and writes a doctor transcript log.
- `MCP-Doctor.cmd`: double-click wrapper around `mcp_doctor.ps1`.
- `make_mod_knowledge.ps1`: direct PowerShell wrapper for writing the Markdown collection knowledge report.
- `Make-Mod-Knowledge.cmd`: double-click wrapper around `make_mod_knowledge.ps1`.
- `vortex_skyrimse_menu.ps1`: local helper menu for common diagnosis/report actions plus profile backup, restore preview, and read-only xEdit inspection script/result actions.
- `Vortex-SkyrimSE-Menu.cmd`: double-click wrapper around `vortex_skyrimse_menu.ps1`.
- `scripts/capture_popup_evidence.ps1`: optional Windows screenshot/OCR helper that writes evidence JSON into a case `incoming` folder.
- `Capture-Popup-Evidence.cmd`: double-click wrapper around `scripts/capture_popup_evidence.ps1`.
- `tests/smoke_mcp.py`: verifies JSON-RPC initialize, tools/list, and a basic tools/call.
- `tests/fixture_mcp.py`: synthetic Skyrim/Vortex fixture for plugin, staging, conflict, logging, and bug-report behavior.
- `tests/config_runtime_mcp.py`: focused config/runtime regression tests for parsing, patch suggestions, root restrictions, stale logs, and issue grouping.
- `tests/run_all.py`: one-command local test runner used by humans and CI.
- `tests/check_powershell.ps1`: parses PowerShell helpers and exercises the menu's noninteractive action list.
- `openclaw.mcp.example.json`: static example config.
- `openclaw.mcp.wsl.example.json`: static WSL2/OpenClaw example config.
- `docs/SAFE-SESSION.md`: explains the one-call safe-session report flow.
- `docs/SKYRIM-DIAGNOSTICS.md`: explains the broad one-button diagnostics report.
- `docs/LAUNCH-DOCTOR.md`: explains the SKSE vs Steam/vanilla launch-route report.
- `docs/SKSE-RUNTIME-DOCTOR.md`: explains Skyrim runtime/SKSE/Address Library compatibility checks.
- `docs/WSL-OPENCLAW.md`: explains OpenClaw-in-WSL2 path bridging for Windows Vortex/Steam/Skyrim.
- `docs/MO2-SUPPORT.md`: explains MO2 instance/profile diagnostics and virtual Data behavior.
- `docs/REVERSIBLE-AUTOMATION.md`: explains the safety gate for risky automation requests.
- `docs/SKYRIM-RUNTIME-LOGS.md`: explains runtime log scanning and safe config patching.
- `docs/RUNTIME-LOG-WATCH.md`: explains cursor-backed runtime log polling for OpenClaw.
- `docs/POPUP-CAPTURE.md`: explains the optional screenshot/OCR evidence helper.
- `docs/VERCEL.md`: explains the static public docs site and local/privacy boundary.
- `docs/TESTING.md`: explains local and CI test commands.
- `docs/MOD-KNOWLEDGE.md`: explains the collection knowledge report and safe removal-review flow.
- `docs/KNOWN-MOD-RULES.md`: explains built-in conflict/dependency rules for common Skyrim SE stacks.
- `docs/NEXUS-API.md`: explains optional read-only Nexus Mods API metadata support.
- `docs/ADR-0001-NEXUS-API-KEYS.md`: records why this MCP uses its own explicit Nexus API key.
- `docs/SCAN-CACHE.md`: explains the local derived mod-summary cache.
- `docs/XEDIT-DIAGNOSTICS.md`: explains read-only xEdit/SSEEdit target hints.
- `docs/COLLECTION-DIAGNOSTICS.md`: explains collection state and manifest matching.
- `docs/CONFLICT-EXPLAINER.md`: explains conflict risk output.
- `docs/SAMPLE-BUG-BUNDLE.md`: shortened sanitized support bundle example for agents and humans.

## server.py Code Map

- constants and helpers: server identity, WSL/Windows path expansion, logging helpers, text IO.
- Steam/Vortex path detection: `find_steam_root`, `steam_libraries`, `find_skyrim_dir`, `default_vortex_appdata`, `find_vortex_exe`.
- MO2 path/profile detection: `mo2_detect_environment`, `mo2_instance_paths`, `mo2_profile_report`, `parse_mo2_modlist`, `mo2_inventory_mods`, `mo2_plugin_report`, `mo2_file_conflict_report`, `mo2_modded_play_report`.
- WSL bridge: `is_wsl_environment`, `windows_path_to_wsl_path`, `windows_env_map`, `wsl_bridge_status`, `wsl_bridge_report`.
- Vortex CLI helpers: `run_vortex_cli`, `vortex_state_get`, `vortex_state_set`.
- filesystem and mod inspection: `safe_walk`, `mod_summary`, `inventory_mods`, `analyze_conflicts`, `redundant_mod_report`, `mod_knowledge_report`.
- known mod rules: `known_mod_rule_report`, `evaluate_known_mod_rules`, and the built-in `KNOWN_MOD_RULES` catalog.
- scan cache: `scan_cache_status`, `mod_summary_cached`, `load_scan_cache`, `write_scan_cache`, `prune_scan_cache`; cache files are compact, bounded, and rewritten only after dirty/missed summaries.
- Nexus metadata: `nexus_validate_key`, `nexus_mod_lookup`, `nexus_mod_files`, `nexus_file_info`, `nexus_file_by_md5`, `nexus_parse_nxm_link`, `nexus_update_report`.
- xEdit/SSEEdit read-only tooling: `xedit_diagnostics_report`, `xedit_inspection_script`, `xedit_inspection_result_report`, `xedit_candidates`, `form_id_load_order_hint`.
- issue case packets: `skyrim_issue_case_packet`, `skyrim_issue_case_status`, `skyrim_issue_case_note`, `skyrim_case_evidence_import`, `skyrim_case_inbox_import`, `skyrim_case_evidence_report`, `skyrim_case_bundle`, `skyrim_safe_experiment_plan`, `skyrim_case_what_now`, `skyrim_live_bridge_status`, `issue_case_default_dir`, `issue_case_markdown`, `issue_case_status_markdown`, `case_evidence_summary`.
- collection diagnostics: `vortex_collection_report`, `collection_local_match_report`, `extract_manifest_mod_refs`.
- in-game issue triage: `in_game_issue_report`, `scan_mod_for_issue`, `extract_plugin_strings`.
- runtime log diagnosis: `skyrim_runtime_log_report`, `skyrim_runtime_log_watch`, `collect_skyrim_runtime_log_files`, `runtime_issue_groups`, `match_runtime_references_to_staged_files`, `runtime_config_candidates`, runtime watch cursor helpers.
- performance shaping: `apply_performance_defaults`, `compact_issue_report`, `compact_play_report`.
- plugin/load-order checks: `parse_plugin_list`, `plugin_report`, `plugin_masters`.
- INI/config checks and writes: `ini_report`, `config_file_report`, `config_patch_suggestions`, `apply_ini_fixes`, `read_text_file`, `apply_config_text_patch`.
- setup validation: `validate_setup`.
- workflow routing: `workflow_guide`, `workflow_catalog`, `workflow_score`.
- profile/deployment tools: `vortex_profile_report`, `vortex_profile_mods`, `vortex_compare_profiles`, `vortex_profile_deployment_report`, `deployment_doctor_report`, `skyrim_launch_doctor_report`, `skse_runtime_doctor_report`, `vortex_reversible_automation_plan`, `vortex_profile_backup`, `vortex_profile_restore_plan`, `vortex_clone_profile`, `vortex_set_profile_mods`, `vortex_safe_profile_fix`.
- play readiness: `skyrim_modded_play_report`, `skyrim_launch_doctor_report`, `skse_runtime_doctor_report`, `suggest_conflict_fixes`.
- support/report tools: `safe_session_report`, `skyrim_diagnostics_report`, `mod_knowledge_report`, `log_status`, `report_viewer_index`, `bug_report_bundle`, `write_report`.
- MCP registration, CLI, and loop: `TOOLS`, `tool_list`, `handle_call`, `cli_main`, `handle_message`, `serve_stdio`.

## Safety Model

Most tools are read-only. The write tools are narrow and opt-in:

- `apply_ini_fixes` writes only when `dry_run=false`.
- `apply_config_text_patch` writes only when `apply=true` or `dry_run=false`, replaces exact text only, restricts paths to detected roots by default, and backs up before writing.
- `vortex_clone_profile` writes only when `apply=true`.
- `vortex_set_profile_mods` writes only when `apply=true`.
- `vortex_safe_profile_fix` writes only when `apply=true`; it creates a cloned profile and applies exact mod-id fixes to that clone only.
- `vortex_reversible_automation_plan` is always read-only; it plans risky requests and routes apply-capable pieces through dry-run-first clone/profile tools.
- `vortex_clone_profile`, `vortex_set_profile_mods`, and `vortex_safe_profile_fix` write a profile backup before `apply=true` unless `backup_before_apply=false`.
- `skyrim_safe_experiment_plan` is always dry-run and writes only plan files.
- `skyrim_issue_case_note` appends case notes only.
- `skyrim_case_evidence_import` appends evidence files only.
- `skyrim_case_inbox_import` imports helper files into case evidence only and de-dupes by SHA-256.
- `scripts/capture_popup_evidence.ps1` writes screenshots and JSON evidence only under a case folder's `incoming` directory.
- `skyrim_case_evidence_report` reads append-only case evidence and writes a
  Markdown/JSON summary only.
- `skyrim_case_bundle` writes a zip copy of case files only.
- `vortex_profile_restore_plan` writes only when `apply=true` and previews by default.
- MO2 tools are read-only. They do not edit `ModOrganizer.ini`, `modlist.txt`,
  `plugins.txt`, `loadorder.txt`, or priorities. They infer the selected
  profile's virtual view from files on disk.
- `in_game_issue_report` is read-only and heuristic. It does not edit plugins,
  delete placed objects, or disable mods.
- Nexus API tools are read-only. They use this MCP's configured key and must not
  copy or reuse Vortex's key.
- xEdit/SSEEdit tools are read-only helpers. They can write generated scripts/CSV summaries, but they do not launch xEdit, clean plugins, or save plugin edits.
- Collection diagnostics are read-only. They do not install, update, remove, or deploy collection mods.
- Scan-cache write failures are logged and do not fail diagnostics.
- Vortex profile writes refuse to run while `Vortex.exe` is open unless `allow_running_vortex=true`.
- Profile writes use `Vortex.exe --set`, not direct database edits.

## Tool Lifecycle

1. MCP client sends `tools/call`.
2. `handle_call` creates a call id and writes a `tool` log start event.
3. The tool function runs.
4. Success writes a compact result summary to `tool-YYYYMMDD.jsonl`.
5. `ToolError` returns a clean MCP tool error and writes a `tool_error` event.
6. Unexpected exceptions return a traceback-limited tool error and write an `exception` event.

## Vortex Profile Flow

Profile-aware tools call Vortex's own CLI:

```text
vortex_profile_report
  -> load_vortex_profile_state
  -> vortex_state_get
  -> run_vortex_cli
  -> Vortex.exe --get persistent.profiles ...
```

Writes follow the same idea in reverse:

```text
vortex_clone_profile or vortex_set_profile_mods
  -> optionally write profile backup JSON
  -> create exact state changes
  -> split into safe CLI batches
  -> Vortex.exe --set path=value
```

Large collection profiles can have many mods, so writes are batched to avoid Windows command length failures.

Undo flow:

```text
vortex_profile_backup
  -> load_vortex_profile_state
  -> write JSON backup

vortex_profile_restore_plan
  -> load backup JSON
  -> load current Vortex profile state
  -> compare backed-up state to current state
  -> preview exact state changes
  -> optionally Vortex.exe --set path=value when apply=true
```

## Bug Report Flow

For a low-friction first pass, OpenClaw should call:

```text
skyrim_diagnostics_report
```

`skyrim_diagnostics_report` writes a Markdown report plus JSON. It calls setup
validation, optional profile backup, modded play health, optional in-game issue
triage, Skyrim runtime log scanning, optional Nexus metadata, and log status. It
is no-change except for writing report files and a profile backup JSON.

For a bug, OpenClaw should call:

```text
log_status
bug_report_bundle with zip_output=true and redact_user_paths=true
```

`bug_report_bundle` writes a JSON file with environment data, play/deployment/plugin/INI reports, and recent log tails. With `zip_output=true`, it also writes one attachable zip containing the JSON, recent log tails, and a short README. With `redact_user_paths=true`, user profile, AppData, and LocalAppData paths are replaced before writing the bundle.

`report_viewer_index` writes a static HTML file for a reports folder. It scans
report-shaped files, extracts small summaries, and links back to the local
source files. It is read-only except for writing the viewer HTML snapshot.
