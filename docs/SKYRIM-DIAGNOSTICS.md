# Skyrim Diagnostics

`skyrim_diagnostics_report` is the broadest no-hassle first report. It is a
safe wrapper around the existing setup, profile, deployment, play-health,
in-game issue, log, local scan-cache, read-only xEdit target, collection, and
optional Nexus metadata checks.

It writes:

- Markdown for humans.
- JSON for OpenClaw or another agent.

It does not deploy mods, disable mods, update mods, sort plugins, edit INIs,
edit plugins, delete files, or launch Skyrim.

## When To Use It

Use it when the user says:

- mods are downloaded but not working
- Vortex has the wrong profile active
- SKSE is confusing
- audio is missing
- deployment failed
- there is a weird object in game
- a popup keeps appearing
- a huge collection needs a first-pass health check
- a FormID needs an xEdit/SSEEdit inspection target
- collection state might not match what is staged locally

## OpenClaw Prompt

```text
Use skyrim_diagnostics_report to write a no-change Skyrim SE diagnostics report. Include Nexus metadata if available. Summarize the highest-risk findings, the safest next action, and whether anything was changed.
```

For slower models:

```text
Use skyrim_diagnostics_report with performance_mode=slow_model. Read summary, findings, and nextActions first. Do not apply changes.
```

For an in-game object:

```text
Use skyrim_diagnostics_report with this issue: there is a bed outside the tavern room in the Whiterun Bannered Mare. Do not apply changes.
```

For a popup:

```text
Use skyrim_diagnostics_report with this issue: annoying popup after loading a save. Do not ask me to type the exact popup unless the first scan is weak.
```

## Direct CLI

```powershell
py -3 .\server.py --skyrim-diagnostics
```

With Nexus metadata:

```powershell
py -3 .\server.py --skyrim-diagnostics --include-nexus-metadata
```

With read-only xEdit target hints:

```powershell
py -3 .\server.py --skyrim-diagnostics --include-xedit-report --form-id "0100ABCD"
```

With Vortex collection-state hints:

```powershell
py -3 .\server.py --skyrim-diagnostics --include-collection-report
```

With an issue:

```powershell
py -3 .\server.py --skyrim-diagnostics --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed"
```

## Local Menu

Double-click:

```text
Vortex-SkyrimSE-Menu.cmd
```

Choose:

```text
12. Skyrim diagnostics report
```

Noninteractive:

```powershell
.\vortex_skyrimse_menu.ps1 -Action diagnostics
```

With optional Nexus metadata:

```powershell
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeNexusMetadata
```

With optional xEdit or collection context:

```powershell
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeXeditReport -FormId "0100ABCD"
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeCollectionReport
```

## What The Report Checks

- setup validation
- Vortex executable and staging folder detection
- Skyrim SE install detection
- SKSE loader detection
- optional Vortex profile backup
- Vortex profile/deployment state when the Vortex CLI works
- enabled plugins in `plugins.txt`
- plugins missing from Skyrim `Data`
- missing plugin masters
- Skyrim INI settings
- audio archive presence
- SKSE plugin/file evidence
- in-game issue candidates when a description is provided
- read-only xEdit/SSEEdit target hints when requested or a FormID/plugin is provided
- Vortex collection-like state when requested
- local scan-cache status
- recent MCP logs
- optional Nexus metadata health and update/source review

## How OpenClaw Should Read It

Read in this order:

1. `summary`
2. `findings`
3. `nextActions`
4. `sections.setupValidation`
5. `sections.skyrimModdedPlay`
6. `sections.inGameIssue`, if present
7. `sections.xeditDiagnostics`, if present
8. `sections.vortexCollection`, if present
9. `sections.nexusUpdateReport`, if present
10. `sections.logStatus`

If a finding points to a mod candidate, the safe next step is a cloned-profile
disable test, not deletion. If a finding points to deployment, the safe next step
is usually to select the intended Vortex profile, click Deploy Mods in Vortex,
confirm plugins are enabled, then launch through SKSE.

## Nexus Metadata In This Report

If a Nexus API key is configured, the report can add:

- how many local mods were mapped to Nexus ids
- version-review candidates
- hidden/unavailable source mods
- staged mods missing Nexus source metadata
- skipped lookups when the collection exceeds `nexus_max_lookup_mods`

A version mismatch is not an instruction to update. Large collections often pin
specific mod versions. Review collection notes and changelogs first.
