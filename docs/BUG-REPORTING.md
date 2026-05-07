# Bug Reporting

Good bug reports should let OpenClaw or a maintainer answer three questions:

1. What did the user ask the MCP to do?
2. Which layer failed?
3. What exact evidence did the MCP see?

## Fast Path

Ask OpenClaw:

```text
Use skyrim_diagnostics_report to write a no-change first report, summarize the highest-risk findings, and tell me where the Markdown and JSON files were written. Do not apply changes.
```

If a maintainer needs the full attachable bundle:

```text
Use the vortex-skyrimse MCP to run log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Then summarize the highest-risk findings and tell me where the zip was written. Do not apply changes.
```

For a slower OpenClaw model, add `performance_mode=slow_model` to either
`safe_session_report` or `bug_report_bundle`. The bundle still keeps important
diagnostic sections, but compact issue/play details are easier to read.

Or run MCP Doctor:

```powershell
.\mcp_doctor.ps1
```

To browse everything already generated on the machine:

```powershell
.\vortex_skyrimse_menu.ps1 -Action report-viewer
```

This writes `report-viewer.html` in the reports folder. It is useful for local
triage, but attach the redacted bug zip when sharing outside your machine.

## What To Attach

Attach:

- the zip file from `bug_report_bundle` with `zip_output=true`
- the Markdown/JSON files from `safe_session_report`, if you ran it first
- the exact OpenClaw prompt that failed
- a screenshot of the Vortex error, if there was one
- whether Vortex was open or closed
- whether the issue happened after installing a collection, changing profiles, updating SKSE, or deploying mods
- the profile backup path if a profile write or restore was involved
- for in-game object/popup issues, the location, object/FormID if known, and screenshots/OCR or exact popup text if available
- for config popups, run the game once until the popup appears so `skyrim_runtime_log_report` has fresh Papyrus/SKSE/crash evidence

## Manual Bundle Tool

OpenClaw can call:

```text
bug_report_bundle
```

Useful arguments:

```json
{
  "include_logs": true,
  "redact_user_paths": true,
  "zip_output": true,
  "include_vortex_profiles": true,
  "include_vortex_deployment": true,
  "include_play_report": true,
  "include_conflicts": false,
  "include_xedit_report": false,
  "include_collection_report": false,
  "include_runtime_logs": true,
  "performance_mode": "slow_model"
}
```

Use `include_conflicts=true` only when the bug is about conflicts or crashes. It can be slower on large collections.

Use `zip_output=true` when you want one attachable file. The zip contains:

- `README-BUG-REPORT.txt`
- the JSON bundle
- recent log tails under `logs/`

`redact_user_paths=true` is the default. It replaces user profile, AppData, and LocalAppData paths before writing the bundle.

## What The Bundle Contains

- server name/version
- setup validation blockers
- environment detection
- Nexus API configuration status, and optional update/source metadata when requested
- scan-cache status
- optional xEdit/SSEEdit target hints when requested or FormID/plugin evidence is supplied
- optional Vortex collection state when requested
- Skyrim runtime log issue groups, freshness status, findings, and config candidates when enabled
- modded play report
- Vortex profile report if available
- Vortex profile deployment report if available
- plugin report
- INI report
- in-game issue report output if the bundle is given `description`, `location`, `object`, or optional `popup_text`
- recent log file summaries and tails
- a bug-report template
- OpenClaw agent instructions

For in-game issue reports, start with `diagnosticQuality`, `scan.timedOut`, and
`nextBestInputs` before asking the user for more details.

## Privacy Warning

With `redact_user_paths=true`, normal user profile paths are replaced before the files are written. The bundle may still include mod names, plugin names, custom non-user paths, and recent logs. Review it before posting publicly.

## Good GitHub Issue Template

```text
Summary:

What I expected:

What happened:

OpenClaw prompt or MCP tool:

Was Vortex open?

Active Vortex profile:

Recent change:
Collection install / SKSE update / Vortex update / profile switch / deploy / other

Bundle attached:
Yes / No
```

## Maintainer Triage

Start with:

- `skyrimModdedPlay.findings`
- `vortexProfileDeployment.issues`
- `pluginsError`
- `vortexProfilesError`
- recent `tool_error` or `exception` log events
- recent `vortex-cli` nonzero return codes or timeouts
- `nexusUpdateReport` errors, stale mods, missing source metadata, or lookup-limit skips
- `xeditDiagnostics` target hints for FormID/plugin issues
- `skyrimRuntimeLogs.issueGroups`, `freshLogStatus`, `configCandidates`, and any `suggestedTextPatches` for popup/config/crash issues
- `vortexCollection` collection-state context for collection drift
- `backupPath` fields from any profile write result

Common next actions:

- close Vortex and retry if the Vortex CLI says the database is locked
- pass explicit `vortex_exe` if Vortex cannot be found
- pass explicit `staging_dir` if the staging folder is custom
- ask the user to deploy mods if enabled profile plugins are missing from Skyrim `Data`
- ask the user to enable plugins if profile plugins are present but disabled in `plugins.txt`
