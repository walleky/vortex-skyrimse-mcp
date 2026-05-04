# Scan Cache

The scan cache speeds up repeated diagnostics on large Skyrim SE collections.
It stores derived summaries of local staged mod folders, not Nexus API keys and
not full downloaded archives.

## What It Caches

Cached mod summaries include:

- mod folder name and path
- file counts and total bytes
- detected plugin, archive, SKSE DLL, readme, FOMOD, and metadata hints
- optional file lists when a tool requested them

The cache lives by default under:

```text
%LOCALAPPDATA%\vortex-skyrimse-mcp\scan-cache\mod-summary-cache.json
```

Override it with:

```powershell
$env:VORTEX_SKYRIMSE_MCP_SCAN_CACHE_DIR = "D:\vortex-skyrimse-mcp-cache"
```

or one call at a time:

```powershell
py -3 .\server.py --tool scan_cache_status --scan-cache-dir "D:\vortex-skyrimse-mcp-cache"
```

## When To Use It

Use the cache by default. It helps when OpenClaw runs several reports in one
session, such as:

```text
skyrim_diagnostics_report
mod_knowledge_report
in_game_issue_report
nexus_update_report
```

For a completely fresh pass:

```powershell
py -3 .\server.py --skyrim-diagnostics --no-scan-cache
```

In MCP arguments, set:

```json
{
  "use_scan_cache": false
}
```

## Safety Notes

The cache is a speed hint. If the cache folder is locked or unwritable, the MCP
logs the cache error and continues with a live scan.

The cache key includes the MCP version, mod folder path, file-list mode, scan
limits, and a lightweight folder signature. If a diagnostic result looks stale,
rerun with `use_scan_cache=false` or `--no-scan-cache`.

## Agent Guidance

For slower OpenClaw models:

1. Keep the cache on.
2. Start with `skyrim_diagnostics_report performance_mode=slow_model`.
3. Read `scan_cache_status` only when performance is confusing.
4. Use `--no-scan-cache` only when the user just installed, removed, or edited
   many files and the diagnosis looks inconsistent.
