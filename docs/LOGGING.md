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

`vortex-cli`

- Vortex executable lookup problems
- `Vortex.exe --get` and `--set` starts
- return code, duration, stdout/stderr byte counts
- stdout/stderr previews

`support`

- bug-report bundle creation

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
bug_report_bundle
```

The bundle includes recent log tails by default.

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

Review logs before posting them publicly.
