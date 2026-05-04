# Architecture

This repo is intentionally small: one dependency-free Python MCP/CLI server, PowerShell helpers, and tests.

## Runtime Shape

```text
OpenClaw or MCP client
  -> stdio JSON-RPC
  -> server.py
      -> detect local Steam/Vortex/Skyrim paths
      -> inspect staging folders, plugins, INIs, profiles, conflicts
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
- `mcp_doctor.ps1`: runs self-tests, smoke tests, config generation, optional OpenClaw registration, and writes a doctor transcript log.
- `MCP-Doctor.cmd`: double-click wrapper around `mcp_doctor.ps1`.
- `make_mod_knowledge.ps1`: direct PowerShell wrapper for writing the Markdown collection knowledge report.
- `Make-Mod-Knowledge.cmd`: double-click wrapper around `make_mod_knowledge.ps1`.
- `vortex_skyrimse_menu.ps1`: local helper menu for common diagnosis/report actions plus profile backup and restore preview.
- `Vortex-SkyrimSE-Menu.cmd`: double-click wrapper around `vortex_skyrimse_menu.ps1`.
- `tests/smoke_mcp.py`: verifies JSON-RPC initialize, tools/list, and a basic tools/call.
- `tests/fixture_mcp.py`: synthetic Skyrim/Vortex fixture for plugin, staging, conflict, logging, and bug-report behavior.
- `tests/check_powershell.ps1`: parses PowerShell helpers and exercises the menu's noninteractive action list.
- `openclaw.mcp.example.json`: static example config.
- `docs/MOD-KNOWLEDGE.md`: explains the collection knowledge report and safe removal-review flow.
- `docs/SAMPLE-BUG-BUNDLE.md`: shortened sanitized support bundle example for agents and humans.

## server.py Code Map

- constants and helpers: server identity, path expansion, logging helpers, text IO.
- Steam/Vortex path detection: `find_steam_root`, `steam_libraries`, `find_skyrim_dir`, `default_vortex_appdata`, `find_vortex_exe`.
- Vortex CLI helpers: `run_vortex_cli`, `vortex_state_get`, `vortex_state_set`.
- filesystem and mod inspection: `safe_walk`, `mod_summary`, `inventory_mods`, `analyze_conflicts`, `redundant_mod_report`, `mod_knowledge_report`.
- in-game issue triage: `in_game_issue_report`, `scan_mod_for_issue`, `extract_plugin_strings`.
- plugin/load-order checks: `parse_plugin_list`, `plugin_report`, `plugin_masters`.
- INI checks and writes: `ini_report`, `apply_ini_fixes`.
- setup validation: `validate_setup`.
- profile tools: `vortex_profile_report`, `vortex_profile_mods`, `vortex_compare_profiles`, `vortex_profile_deployment_report`, `vortex_profile_backup`, `vortex_profile_restore_plan`, `vortex_clone_profile`, `vortex_set_profile_mods`.
- play readiness: `skyrim_modded_play_report`, `suggest_conflict_fixes`.
- support/report tools: `mod_knowledge_report`, `log_status`, `bug_report_bundle`, `write_report`.
- MCP registration, CLI, and loop: `TOOLS`, `tool_list`, `handle_call`, `cli_main`, `handle_message`, `serve_stdio`.

## Safety Model

Most tools are read-only. The write tools are narrow and opt-in:

- `apply_ini_fixes` writes only when `dry_run=false`.
- `vortex_clone_profile` writes only when `apply=true`.
- `vortex_set_profile_mods` writes only when `apply=true`.
- `vortex_clone_profile` and `vortex_set_profile_mods` write a profile backup before `apply=true` unless `backup_before_apply=false`.
- `vortex_profile_restore_plan` writes only when `apply=true` and previews by default.
- `in_game_issue_report` is read-only and heuristic. It does not edit plugins,
  delete placed objects, or disable mods.
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

For a bug, OpenClaw should call:

```text
log_status
bug_report_bundle with zip_output=true and redact_user_paths=true
```

`bug_report_bundle` writes a JSON file with environment data, play/deployment/plugin/INI reports, and recent log tails. With `zip_output=true`, it also writes one attachable zip containing the JSON, recent log tails, and a short README. With `redact_user_paths=true`, user profile, AppData, and LocalAppData paths are replaced before writing the bundle.
