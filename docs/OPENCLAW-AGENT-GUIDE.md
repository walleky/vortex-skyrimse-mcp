# OpenClaw Agent Guide

This guide is written for an OpenClaw agent that has access to the `vortex-skyrimse` MCP server.

The same repo also has direct CLI mode. If MCP registration fails, tell the user they can still run `.\vortex_skyrimse_menu.ps1`, `.\make_mod_knowledge.ps1`, or `py -3 .\server.py --mod-knowledge` from the project folder.

## Default Posture

Start read-only. Do not apply INI fixes or Vortex profile writes unless the user explicitly asks you to apply changes.

First call `validate_setup`. If it returns blockers, explain those blockers before running write-capable tools.

When the user says mods are not working, first decide which layer is failing:

```text
environment detection
  -> Vortex profile state
  -> Vortex deployment into Skyrim Data
  -> plugins.txt enabled state
  -> SKSE/audio/INI health
  -> in-game issue evidence
  -> conflicts/redundant mods
```

## First Tool Calls

For a broad first pass:

```text
validate_setup
detect_environment
skyrim_modded_play_report
```

For "Vortex has two Skyrims" or "wrong profile":

```text
vortex_profile_report
vortex_profile_deployment_report
```

For "mods downloaded but not active":

```text
vortex_profile_deployment_report
plugin_report
```

For "crash or missing masters":

```text
plugin_report
analyze_conflicts
suggest_conflict_fixes
```

For "what does this mod do?":

```text
mod_evidence
```

For "what does this whole collection do?" or "what can I remove?":

```text
mod_knowledge_report
```

For "why is this object here?", "which mod added this?", or annoying popups:

```text
in_game_issue_report
```

Ask the user for exact location, object name, popup text, and if possible the console-clicked FormID.

For "make me a safe test profile":

```text
vortex_profile_backup with include_all_profiles=true
vortex_clone_profile with apply=false
```

Only after the user approves:

```text
vortex_clone_profile with apply=true
```

## Bug Report Flow

When a tool fails or the user says OpenClaw got confused:

```text
log_status
bug_report_bundle with zip_output=true and redact_user_paths=true
```

Use plain JSON output only if the user cannot share zip attachments. Leave `redact_user_paths=true` unless the user explicitly needs raw local paths.

Then tell the user:

- where the zip was written
- what privacy-sensitive data it may contain
- which finding or error looks most important

Do not paste the whole bundle into chat unless the user asks. Summarize the key findings first.

## How To Interpret Common Issues

`Vortex.exe was not found`

Ask for `vortex_exe`, or tell the user to run Vortex once and rerun MCP Doctor.

`Vortex CLI timed out`

Tell the user to close Vortex completely. Then rerun the same tool. Vortex profile state can be locked while the app is open.

`staging folder was not found`

Ask for `staging_dir`. In Vortex, this is Settings > Mods > Mod Staging Folder.

`plugins.txt was not found`

Tell the user to launch Skyrim once, then let Vortex deploy plugins. Also check `%LOCALAPPDATA%\Skyrim Special Edition`.

`enabled profile plugins are not in Skyrim Data`

Tell the user to click Deploy Mods in Vortex and confirm the active Vortex profile is the intended one.

`enabled profile plugins are not enabled in plugins.txt`

Tell the user to enable plugins in Vortex's Plugins tab, then deploy.

`plugins.txt has enabled plugins not seen in selected profile`

This usually means stale deployment or the wrong active profile.

`in_game_issue_report returns weak candidates`

Ask for stronger evidence: exact popup text, screenshot/OCR text, current cell/location, and console-clicked FormID/base object. Then rerun `in_game_issue_report`.

If the first pass is still too weak, rerun with `deep_scan_files=true`. Warn the user that it is slower on large collections.

## Safe Write Rules

Before `apply_ini_fixes dry_run=false`:

- show the dry-run result
- explain the exact INI keys
- keep `make_backup=true`

Before `vortex_clone_profile apply=true`:

- call `vortex_profile_backup` first, or confirm the dry-run result already shows a `backupPath`
- show the dry-run plan
- tell the user to close Vortex
- give the new profile name/id

Before `vortex_set_profile_mods apply=true`:

- call `vortex_profile_backup` first, or confirm the dry-run result already shows a `backupPath`
- call `vortex_profile_mods` first
- use exact mod ids
- do not guess ids from display names
- tell the user to deploy mods afterward

Before `vortex_profile_restore_plan apply=true`:

- run the same tool with `apply=false`
- explain the planned change count
- keep `disable_extra_mods=false` unless the user clearly wants extra currently enabled mods disabled
- tell the user to close Vortex

Before fixing an in-game object or popup:

- run `in_game_issue_report`
- explain that it is heuristic unless there is FormID or exact popup-text evidence
- create a Vortex profile backup
- prefer cloned-profile disable tests over deletion
- do not edit plugin records or conflict rules automatically

## Good Final Answer Shape

Use this order:

1. Highest-risk finding.
2. What it means in plain English.
3. The safest next action.
4. Any command or Vortex UI click needed.
5. Whether anything was changed.

Avoid telling the user to delete mods from a redundancy report. Say "candidate" unless hashes and plugin evidence are strong.

## Large Collection Review

When the user has a massive Nexus Collection, call `mod_knowledge_report` before recommending removals. Read the Markdown sections in this order:

1. Removal Review Shortlist.
2. Sensitive Conflict Examples.
3. Plugin Master Problems.
4. Mod Index.
5. Mod Details for the specific mods you want to discuss.

For unwanted mods, prefer this wording: "disable in a cloned profile and test" instead of "delete." Use `vortex_clone_profile apply=false` first if the user wants a safe experiment profile. Use `vortex_set_profile_mods apply=false` to preview exact disable operations, and only use `apply=true` after the user explicitly approves.

## In-Game Issue Review

For misplaced objects, ask the user to open the console, click the object, and provide the shown reference/base FormID and name. For popups, ask for exact text. Then run:

```text
in_game_issue_report with description, location, object, popup_text if available
```

Include `form_id`, `cell`, and `base_object` when the user provides console evidence. If the top candidate has a Vortex mod id, preview disabling it only in a cloned profile. Tell the user to deploy and test the cloned profile before changing their main profile.

## Undo Flow

If a profile change makes things worse:

```text
vortex_profile_restore_plan with backup_path=<backup file> and apply=false
```

Read the preview. If it looks correct and the user approves, tell the user to close Vortex and rerun with `apply=true`. Reopen Vortex afterward and deploy mods.
