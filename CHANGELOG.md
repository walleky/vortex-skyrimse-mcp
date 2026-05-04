# Changelog

## v0.2.2

- Adds central MCP file logging for server lifecycle, tool calls, Vortex CLI calls, and support bundle creation.
- Adds `log_status` for OpenClaw-readable log discovery.
- Adds `bug_report_bundle` for JSON bug reports with environment/play/deployment/plugin/INI checks plus recent log tails.
- Adds architecture, OpenClaw agent, logging, and bug-reporting docs.
- Adds a GitHub bug-report issue template.
- MCP Doctor now writes a transcript log to the MCP log folder.

## v0.2.1

- Adds MCP Doctor PowerShell and double-click CMD launchers.
- MCP Doctor runs self-tests, writes a ready-to-copy config snippet, prints an OpenClaw registration command, optionally registers through `openclaw mcp set`, and can open the OpenClaw config folder.
- CI now runs MCP Doctor in addition to server compile, self-test, and stdio smoke tests.

## v0.2.0

- Initial standalone GitHub release.
- Adds a dependency-free stdio MCP server for Windows Vortex + Skyrim SE diagnostics.
- Includes environment detection, mod inventory, conflict reports, redundant mod checks, plugin reports, INI checks, profile inspection, profile cloning, profile mod toggles, deployment checks, and one-shot modded play reports.
- Includes a PowerShell installer that prints a ready-to-copy MCP config snippet.
- Includes smoke tests for JSON-RPC initialization, tool listing, and basic environment detection.
