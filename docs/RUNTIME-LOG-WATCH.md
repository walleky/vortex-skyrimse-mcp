# Runtime Log Watch

`skyrim_runtime_log_watch` lets OpenClaw poll Skyrim runtime logs without
rereading the same old Papyrus/SKSE/crash text every turn.

It is read-only. It never edits mods, Vortex profiles, MO2 profiles, plugins,
load order, INI files, or Skyrim.

## Why This Exists

OpenClaw called out that the MCP could only read logs on demand. That works, but
large logs make repeated checks slow and noisy. The watch tool adds a local
cursor file:

- First call reads a recent tail by default.
- Calls after that read only bytes appended since the previous cursor.
- `reset=true` moves all cursors to the current end of each log and returns no
  old findings.
- The same runtime error grouping, severity detection, filename extraction, and
  config candidate matching are reused from `skyrim_runtime_log_report`.

This is still polling. It is not a live SKSE event stream and it cannot see the
game window. It is a safe bridge until a separate OCR/SKSE telemetry helper
exists.

## Recommended OpenClaw Workflow

Use this when the user says a popup/crash/warning appears while testing:

```text
Use skyrim_runtime_log_watch with watch_id=playtest and reset=true. Tell me when the cursor is initialized. I will reproduce the issue, then call the same tool again and summarize only new critical/high/config findings.
```

After the user reproduces the problem:

```text
Use skyrim_runtime_log_watch with watch_id=playtest and my popup description. Read issueGroups, configCandidates, and hasNewCriticalOrHigh. If configCandidates appear, inspect them with config_file_report before proposing any dry-run patch.
```

For slow models or huge collections:

```text
Use skyrim_runtime_log_watch with watch_id=playtest, performance_mode=slow_model, max_runtime_findings=20, max_runtime_log_files=6.
```

## Direct CLI

Initialize the cursor:

```powershell
py -3 .\server.py --runtime-log-watch --watch-id playtest --reset-runtime-watch
```

Check new log evidence:

```powershell
py -3 .\server.py --runtime-log-watch --watch-id playtest --description "popup says file was not configured properly"
```

Write JSON for another agent:

```powershell
py -3 .\server.py --runtime-log-watch --watch-id playtest --output-json .\runtime-watch.json
```

## Important Fields

| Field | Meaning |
| --- | --- |
| `newFindingCount` | Number of new high-signal lines found since the cursor. |
| `hasNewCriticalOrHigh` | True when a new crash, SKSE DLL, runtime, or fatal clue appears. |
| `issueGroups` | Deduplicated root-cause patterns from new lines only. |
| `configCandidates` | Staged config/text files that may explain popup/config errors. |
| `statePath` | Local cursor JSON path. Safe to delete if you want a fresh cursor. |
| `files[].newBytes` | How many new bytes were read from each log. |

## Safety Rules

- Use `reset=true` before a clean reproduction.
- Treat Papyrus warnings as weak evidence unless repeated.
- Treat SKSE DLL, Address Library, fatal exception, and missing master findings
  as higher priority.
- Do not patch configs until `config_file_report` confirms the file and the
  exact replacement is obvious.
- Do not edit plugin records or delete mods from log evidence alone.
