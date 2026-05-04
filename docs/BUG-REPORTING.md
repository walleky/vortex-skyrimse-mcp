# Bug Reporting

Good bug reports should let OpenClaw or a maintainer answer three questions:

1. What did the user ask the MCP to do?
2. Which layer failed?
3. What exact evidence did the MCP see?

## Fast Path

Ask OpenClaw:

```text
Use the vortex-skyrimse MCP to run log_status and bug_report_bundle. Then summarize the highest-risk findings and tell me where the bundle was written. Do not apply changes.
```

Or run MCP Doctor:

```powershell
.\mcp_doctor.ps1
```

## What To Attach

Attach:

- the JSON file from `bug_report_bundle`
- the exact OpenClaw prompt that failed
- a screenshot of the Vortex error, if there was one
- whether Vortex was open or closed
- whether the issue happened after installing a collection, changing profiles, updating SKSE, or deploying mods

## Manual Bundle Tool

OpenClaw can call:

```text
bug_report_bundle
```

Useful arguments:

```json
{
  "include_logs": true,
  "include_vortex_profiles": true,
  "include_vortex_deployment": true,
  "include_play_report": true,
  "include_conflicts": false
}
```

Use `include_conflicts=true` only when the bug is about conflicts or crashes. It can be slower on large collections.

## What The Bundle Contains

- server name/version
- environment detection
- modded play report
- Vortex profile report if available
- Vortex profile deployment report if available
- plugin report
- INI report
- recent log file summaries and tails
- a bug-report template
- OpenClaw agent instructions

## Privacy Warning

The bundle may include local paths, mod names, plugin names, and recent logs. Review it before posting publicly.

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

Common next actions:

- close Vortex and retry if the Vortex CLI says the database is locked
- pass explicit `vortex_exe` if Vortex cannot be found
- pass explicit `staging_dir` if the staging folder is custom
- ask the user to deploy mods if enabled profile plugins are missing from Skyrim `Data`
- ask the user to enable plugins if profile plugins are present but disabled in `plugins.txt`
