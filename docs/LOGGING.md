# Logging

The MCP server logs to files because stdout is reserved for MCP JSON-RPC messages.

## Default Log Folder

Windows:

```text
%LOCALAPPDATA%\vortex-skyrimse-mcp\logs
```

Fallbacks:

```text
%APPDATA%\vortex-skyrimse-mcp\logs
~\.vortex-skyrimse-mcp\logs
```

Override:

```powershell
$env:VORTEX_SKYRIMSE_MCP_LOG_DIR = "D:\Logs\vortex-skyrimse-mcp"
```

## Log Files

The server writes daily JSONL files:

```text
server-YYYYMMDD.jsonl
tool-YYYYMMDD.jsonl
vortex-cli-YYYYMMDD.jsonl
support-YYYYMMDD.jsonl
scan-cache-YYYYMMDD.jsonl
```

MCP Doctor writes transcript logs:

```text
doctor-YYYYMMDD-HHMMSS.log
```

## Channels

`server`

- server start
- initialize
- tools/list
- unknown method
- JSON parse errors
- self-test

`tool`

- tool start
- tool success
- expected `ToolError`
- unexpected exception with traceback preview
- compact tool arguments/results with Nexus API keys and token-like fields redacted

`vortex-cli`

- Vortex executable lookup problems
- `Vortex.exe --get` and `--set` starts
- return code, duration, stdout/stderr byte counts
- stdout/stderr previews

`support`

- bug-report bundle creation
- safe-session report creation and per-section errors
- exact config-text patch application events, including backup path

`scan-cache`

- local scan-cache write failures
- cache errors are logged here instead of failing the diagnosis

`doctor`

- full PowerShell MCP Doctor transcript

## Inspect Logs From OpenClaw

Use:

```text
log_status
```

It returns the log folder, recent files, and channel counts.

For a full support report:

```text
safe_session_report
```

For an attachable bug bundle:

```text
bug_report_bundle
```

To inspect Skyrim's own runtime logs, use:

```text
skyrim_runtime_log_report
```

That is separate from MCP logs. It scans recent Papyrus/SKSE/crash logs for
game/mod errors and maps referenced files back to staged mods when possible.

The bundle includes recent log tails by default. For one attachable file:

```json
{
  "zip_output": true,
  "redact_user_paths": true
}
```

This writes a zip containing the JSON bundle, a short README, and recent log tails.

## Inspect Logs Manually

PowerShell:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\vortex-skyrimse-mcp\logs" | Sort-Object LastWriteTime -Descending
Get-Content "$env:LOCALAPPDATA\vortex-skyrimse-mcp\logs\tool-YYYYMMDD.jsonl" -Tail 20
```

## Privacy

Logs may include:

- local Windows paths
- mod names
- plugin names
- Vortex CLI stdout/stderr previews
- OpenClaw config paths

Logs must not include Nexus API keys. If you see a key in a log, treat that as a
security bug and rotate the key.

Review logs before posting them publicly.
