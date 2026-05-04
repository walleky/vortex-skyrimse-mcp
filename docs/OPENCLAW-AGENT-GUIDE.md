# OpenClaw Agent Guide

This guide is written for an OpenClaw agent that has access to the `vortex-skyrimse` MCP server.

The same repo also has direct CLI mode. If MCP registration fails, tell the user they can still run `.\vortex_skyrimse_menu.ps1`, `.\make_mod_knowledge.ps1`, `py -3 .\server.py --skyrim-diagnostics`, `py -3 .\server.py --safe-session`, or `py -3 .\server.py --mod-knowledge` from the project folder.

## Default Posture

Start read-only. Do not apply INI fixes or Vortex profile writes unless the user explicitly asks you to apply changes.

For a confused or frustrated user, first call `skyrim_diagnostics_report` when
available, or `safe_session_report` if you need the older narrower baseline.
Both are no-change Markdown/JSON reports with setup validation, optional profile
backup, modded play health, optional in-game issue triage, and logs.

Prefer `skyrim_diagnostics_report` when the user wants the easiest broad
Skyrim/Vortex answer. It wraps the same no-change safety posture, defaults to
slow-model-friendly output, and includes Nexus metadata automatically when a
Nexus key is configured.

If you are a slower model, or the user's collection is huge, call
`skyrim_diagnostics_report` with `performance_mode=slow_model`. Read `summary`,
`findings`, and `nextActions` before opening nested sections. Only ask for
deeper scans after `diagnosticQuality` or `nextBestInputs` says more evidence is
needed.

For a narrower setup-only request, first call `validate_setup`. If it returns blockers, explain those blockers before running write-capable tools.

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
skyrim_diagnostics_report
```

When the user's request is vague and you need routing help:

```text
workflow_guide with problem=<the user's plain-language issue>
```

Read the returned `workflows[0].tools`, `whatToRead`, and `humanSteps`, then run
the first listed diagnostic tool. Do not treat `workflow_guide` as evidence; it
is only a safe routing helper.

For a broad first pass on a slower model:

```text
skyrim_diagnostics_report with performance_mode=slow_model
```

For a broad first pass without writing report files:

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

For Nexus source/update metadata:

```text
nexus_validate_key
nexus_update_report
```

Use this MCP's own configured Nexus key only. Do not ask for, scrape, or reuse
Vortex's API key. Nexus metadata is helpful context, not an instruction to
update a working collection.

For scan performance:

```text
scan_cache_status
```

The scan cache is on by default. Disable it only when a result looks stale after
the user installed, removed, or manually edited many mod files.

For xEdit/SSEEdit read-only target hints:

```text
xedit_diagnostics_report with form_id or plugin_name
```

Use this to point the user at the likely plugin or record to inspect. Do not
tell the MCP to clean plugins or save xEdit edits.

For collection drift or collection membership:

```text
vortex_collection_report
collection_local_match_report
```

Use collection reports as context. Do not install, update, disable, or remove
collection mods from collection diagnostics alone.

For "why is this object here?", "which mod added this?", or annoying popups:

```text
safe_session_report with description/location/object/popup_text, or in_game_issue_report for a narrower call
```

If the user says "popup", "notification", "warning", "alert", "prompt", "dialog", "MCM message", or similar, run popup triage from the plain description first. Do not block on exact popup text. Ask for exact text or screenshot/OCR only if the first candidates are weak.

For "file was not configured properly", SKSE popups, crash popups, or any log-like error:

```text
skyrim_runtime_log_report with description=<plain user problem>
```

Read `findings`, `severityCounts`, and `configCandidates`. If a config candidate
exists, call `read_text_file` on that path. Only propose
`apply_config_text_patch` with exact `old_text` and `new_text`, and start with
`dry_run=true`. Do not patch plugin files, DLLs, scripts, or arbitrary folders.

For placed objects, ask for exact location, object name, and if possible the console-clicked FormID.

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
safe_session_report
skyrim_diagnostics_report
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

`nexus_metadata_unavailable`

Explain that local diagnostics still work. If the user wants Nexus metadata,
they can set `NEXUS_MODS_API_KEY` or provide `nexus_api_key_file`, then rerun
`nexus_validate_key` and `skyrim_diagnostics_report`.

`nexus_updates_available`

Do not tell the user to update automatically. Large collections may require
specific pinned versions. Tell the user to review collection notes and Vortex
changelogs first.

`scan_cache_status shows old entries`

This is normally fine. The cache is a speed hint. If the user just changed lots
of files or the diagnosis looks stale, rerun the same tool with
`use_scan_cache=false`.

`xedit_diagnostics_report has low confidence`

Explain that FormID prefix mapping can be incomplete with ESL/light plugins and
runtime references. Ask for an in-game console reference, base object, or xEdit
inspection confirmation before changing mods.

`vortex_collection_report found no collection state`

Explain that Vortex may store collection details somewhere the CLI does not
expose. Use `nexus_update_report`, profile tools, and local staging metadata as
fallback context.

`in_game_issue_report returns weak candidates`

For popups, first rerun from the user's natural-language description if OpenClaw forgot to include it. If candidates are still weak, ask for screenshot/OCR text or exact popup text. For placed objects, ask for current cell/location and console-clicked FormID/base object. Then rerun `in_game_issue_report`.

Read `diagnosticQuality` and `nextBestInputs` before asking the user for more information. If the first pass is still too weak, rerun with `scan_mode=deep` or `deep_scan_files=true`. Warn the user that it is slower on large collections.

If `scan.timedOut=true`, explain that the result is partial. Increase `timeout_seconds`, lower `max_mods`, or ask for stronger evidence before blaming a mod.

`skyrim_runtime_log_report has configCandidates`

Read the candidate config file first. If the needed fix is a tiny exact text
replacement, propose `apply_config_text_patch` as a dry run. Applying requires
explicit user approval and writes a backup by default. If the candidate is an
ESP/ESM/ESL, DLL, PEX, BSA, or SWF, do not patch it with this tool.

`skyrim_runtime_log_report shows Address Library, DLL, fatal, or crash findings`

Treat those as higher priority than Papyrus warnings. Check SKSE version,
Address Library/runtime compatibility, plugin install path, and deployment
before changing gameplay mods.

`safe_session_report` has `dryRunOnly=true`. It may write report files and a profile backup, but it should never deploy, disable, delete, sort, or edit mods.

## Slower Model Tips

Prefer these calls:

```text
safe_session_report with performance_mode=slow_model
skyrim_diagnostics_report with performance_mode=slow_model
in_game_issue_report with response_mode=compact
bug_report_bundle with performance_mode=slow_model
```

Avoid starting with collection-wide hash scans. Avoid asking for every nested
section in one answer. Summarize the top finding, then inspect one section or
candidate at a time.

Keep the scan cache enabled for slower models. It reduces repeated filesystem
walks when several reports inspect the same staged mods.

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
- explain that it is heuristic; popup exact text is optional second-pass evidence, while FormID plus `xedit_diagnostics_report` is strongest for placed objects
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

For misplaced objects, ask the user to open the console, click the object, and provide the shown reference/base FormID and name. For popups, run from the plain description first. Then run:

```text
in_game_issue_report with description, location, object, popup_text if available
```

Default `scan_mode=balanced` is the preferred first pass. Use `scan_mode=quick`
only when the collection is huge and the user needs a very fast rough check.
Use `scan_mode=deep` only as a second pass.

Include `form_id`, `cell`, and `base_object` when the user provides console evidence. If the top candidate has a Vortex mod id, preview disabling it only in a cloned profile. Tell the user to deploy and test the cloned profile before changing their main profile.

## Undo Flow

If a profile change makes things worse:

```text
vortex_profile_restore_plan with backup_path=<backup file> and apply=false
```

Read the preview. If it looks correct and the user approves, tell the user to close Vortex and rerun with `apply=true`. Reopen Vortex afterward and deploy mods.
