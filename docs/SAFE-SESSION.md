# Safe Session Report

`safe_session_report` is the easiest first button when Vortex, Skyrim, SKSE, deployment, profiles, or an in-game problem feels confusing.

It writes two files:

- `safe-session-YYYYMMDD-HHMMSS.md`: human-readable report.
- `safe-session-YYYYMMDD-HHMMSS.json`: agent-readable report for OpenClaw.

## What It Checks

- `validate_setup`: detected Vortex, Skyrim SE, staging folder, SKSE, and blockers.
- `vortex_profile_backup`: a backup of Skyrim SE Vortex profiles when Vortex CLI is available.
- `skyrim_modded_play_report`: deployment, plugins, INI, audio archive, SKSE, and profile health.
- `in_game_issue_report`: only when you pass a problem description, location, object, optional popup text, or FormID.
- `log_status`: recent MCP logs and channels.

In-game issue triage uses the balanced first scan by default. That means it
checks local names, plugins, readmes, plugin strings, important file paths, and
a small number of relevant config/text files before suggesting a slower deep
scan.

## What It Does Not Do

It does not deploy mods, disable mods, delete mods, edit plugins, write conflict rules, sort load order, or launch Skyrim. It is a report and optional profile backup only.

## Local Menu

Run:

```powershell
.\vortex_skyrimse_menu.ps1
```

Choose:

```text
11. Safe session report
```

Noninteractive:

```powershell
.\vortex_skyrimse_menu.ps1 -Action safe
```

Include an in-game issue:

```powershell
.\vortex_skyrimse_menu.ps1 -Action safe -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed"
```

For popups, a plain description is enough:

```powershell
.\vortex_skyrimse_menu.ps1 -Action safe -IssueDescription "annoying popup after loading a save"
```

If the report says the evidence is weak, rerun the narrower tool with
`scan_mode=deep` or provide screenshot/OCR text.

## Direct CLI

```powershell
py -3 .\server.py --safe-session
```

With exact issue evidence:

```powershell
py -3 .\server.py --safe-session --description "bad bed placement" --location "Whiterun Bannered Mare" --object "bed" --form-id "1200ABCD" --base-object "CommonBed01"
```

Skip profile backup if Vortex CLI is locked or unavailable:

```powershell
py -3 .\server.py --safe-session --no-profile-backup
```

## OpenClaw Prompt

```text
Use safe_session_report to write a no-change first report with setup validation, profile backup if possible, modded play health, logs, and this issue if relevant: <describe the problem>. Summarize the top findings and do not apply changes.
```

## How OpenClaw Should Read It

Start with:

1. `summary.highestSeverity`
2. `findings`
3. `sections.setupValidation.blockers`
4. `sections.skyrimModdedPlay.findings`
5. `sections.inGameIssue.candidates`
6. `sections.logStatus`

For a mod candidate, OpenClaw should recommend a cloned-profile disable test, not deletion. For deployment findings, the safest next action is usually to select the intended Vortex profile, click Deploy Mods, confirm plugins are enabled, then launch through SKSE.
