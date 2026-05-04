# Architecture

This repo is intentionally small: one dependency-free Python MCP server, one PowerShell installer, one PowerShell doctor, and tests.

## Runtime Shape

```text
OpenClaw or MCP client
  -> stdio JSON-RPC
  -> server.py
      -> detect local Steam/Vortex/Skyrim paths
      -> inspect staging folders, plugins, INIs, profiles, conflicts
      -> optionally call Vortex.exe --get/--set for profile state
      -> return structured JSON to the MCP client
```

The server must never write normal logs to stdout because stdout is the MCP protocol stream. Logs go to files, and unexpected diagnostics go to stderr.

## Main Files

- `server.py`: MCP server, tool implementations, logging, and stdio loop.
- `install_windows.ps1`: finds Python and prints a ready-to-copy MCP config snippet.
- `mcp_doctor.ps1`: runs self-tests, smoke tests, config generation, optional OpenClaw registration, and writes a doctor transcript log.
- `MCP-Doctor.cmd`: double-click wrapper around `mcp_doctor.ps1`.
- `tests/smoke_mcp.py`: verifies JSON-RPC initialize, tools/list, and a basic tools/call.
- `tests/fixture_mcp.py`: synthetic Skyrim/Vortex fixture for plugin, staging, conflict, logging, and bug-report behavior.
- `openclaw.mcp.example.json`: static example config.
- `docs/SAMPLE-BUG-BUNDLE.md`: shortened sanitized support bundle example for agents and humans.

## server.py Code Map

- constants and helpers: server identity, path expansion, logging helpers, text IO.
- Steam/Vortex path detection: `find_steam_root`, `steam_libraries`, `find_skyrim_dir`, `default_vortex_appdata`, `find_vortex_exe`.
- Vortex CLI helpers: `run_vortex_cli`, `vortex_state_get`, `vortex_state_set`.
- filesystem and mod inspection: `safe_walk`, `mod_summary`, `inventory_mods`, `analyze_conflicts`, `redundant_mod_report`.
- plugin/load-order checks: `parse_plugin_list`, `plugin_report`, `plugin_masters`.
- INI checks and writes: `ini_report`, `apply_ini_fixes`.
- profile tools: `vortex_profile_report`, `vortex_profile_mods`, `vortex_compare_profiles`, `vortex_clone_profile`, `vortex_set_profile_mods`.
- play readiness: `skyrim_modded_play_report`, `suggest_conflict_fixes`.
- support tools: `log_status`, `bug_report_bundle`, `write_report`.
- MCP registration and loop: `TOOLS`, `tool_list`, `handle_call`, `handle_message`, `serve_stdio`.

## Safety Model

Most tools are read-only. The write tools are narrow and opt-in:

- `apply_ini_fixes` writes only when `dry_run=false`.
- `vortex_clone_profile` writes only when `apply=true`.
- `vortex_set_profile_mods` writes only when `apply=true`.
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
  -> create exact state changes
  -> split into safe CLI batches
  -> Vortex.exe --set path=value
```

Large collection profiles can have many mods, so writes are batched to avoid Windows command length failures.

## Bug Report Flow

For a bug, OpenClaw should call:

```text
log_status
bug_report_bundle with zip_output=true and redact_user_paths=true
```

`bug_report_bundle` writes a JSON file with environment data, play/deployment/plugin/INI reports, and recent log tails. With `zip_output=true`, it also writes one attachable zip containing the JSON, recent log tails, and a short README. With `redact_user_paths=true`, user profile, AppData, and LocalAppData paths are replaced before writing the bundle.
