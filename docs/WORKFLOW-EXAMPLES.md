# Workflow Examples

This project is not a replacement for Vortex. Think of it as a safe diagnostic
assistant for OpenClaw or PowerShell.

The usual interaction looks like this:

```text
You
  -> ask OpenClaw a Skyrim/Vortex question
  -> OpenClaw calls this MCP tool
  -> MCP reads local Vortex/Skyrim files and Vortex CLI state
  -> MCP returns structured evidence
  -> OpenClaw explains the safest next action
  -> you make final deploy/install/update choices in Vortex
```

The MCP can write reports and profile backups. It should not silently delete,
deploy, sort, update, or edit plugins.

## Three Ways To Use It

OpenClaw:

```text
Use the vortex-skyrimse MCP to run skyrim_diagnostics_report. Summarize the top findings and do not apply changes.
```

Built-in workflow recommender:

```text
Use workflow_guide for this problem: mods downloaded but not working. Tell me the recommended tool sequence and do not apply changes.
```

Local menu:

```powershell
.\vortex_skyrimse_menu.ps1
```

Noninteractive workflow guide:

```powershell
.\vortex_skyrimse_menu.ps1 -Action workflow -Problem "mods downloaded but not working"
```

Direct CLI:

```powershell
py -3 .\server.py --skyrim-diagnostics
```

Direct workflow guide:

```powershell
py -3 .\server.py --workflow-guide --problem "mods downloaded but not working"
```

## Workflow 1: First Setup Check

Use this when you just installed the MCP or OpenClaw seems unsure.

Ask OpenClaw:

```text
Use validate_setup, then detect_environment. Tell me whether Vortex, Skyrim SE, staging, plugins.txt, SKSE, and xEdit are detected. Do not apply changes.
```

What OpenClaw should call:

```text
validate_setup
detect_environment
```

What to look for:

- `ready=true`: the basic paths are good.
- `blockers`: things to fix first, such as missing `skyrim_dir`, missing staging folder, or missing SKSE.
- `toolGroups`: which tools are safe immediately and which need Vortex CLI.

Human next step:

Fix blockers first. Do not start disabling mods until setup detection is clean
enough to trust the diagnosis.

## Workflow 2: Mods Downloaded But Not Working In Game

Use this when Vortex shows mods installed but Skyrim launches vanilla or only
some mods work.

Ask OpenClaw:

```text
Use skyrim_diagnostics_report with performance_mode=slow_model. Check whether my selected Vortex profile is deployed into Skyrim Data and enabled in plugins.txt. Do not apply changes.
```

What OpenClaw should call:

```text
skyrim_diagnostics_report
vortex_profile_deployment_report
plugin_report
```

What to look for:

- enabled profile mods missing from Skyrim `Data`
- enabled plugins missing from `plugins.txt`
- stale plugins in `plugins.txt` from another profile
- missing masters
- wrong or inactive Vortex profile

Human next step:

In Vortex, select the intended Skyrim SE profile, click Deploy Mods, confirm the
Plugins tab is enabled, then launch through SKSE if the setup uses SKSE.

## Workflow 3: Weird Object In Game

Example: "There is a bed outside the tavern room in the Whiterun Bannered Mare."

Ask OpenClaw:

```text
Use skyrim_diagnostics_report with this issue: there is a bed outside the tavern room in the Whiterun Bannered Mare. Find likely mod candidates and do not apply changes.
```

Better if you have console evidence:

```text
Use in_game_issue_report with description "bed outside tavern room", location "Whiterun Bannered Mare", object "bed", form_id "0100ABCD", and base_object "CommonBed01". Then use xedit_diagnostics_report for the same FormID. Do not edit plugins.
```

What OpenClaw should call:

```text
in_game_issue_report
xedit_diagnostics_report
vortex_profile_backup
```

What to look for:

- top candidate mod and confidence
- matched terms from plugin strings, readmes, filenames, or config text
- FormID plugin hint
- whether the candidate is enabled in the active profile

Human next step:

Make or confirm a profile backup, clone the current profile, disable one
candidate in the clone, deploy in Vortex, and test the same save. Do not delete
the mod first.

## Workflow 4: Annoying Popup

Use this when you do not want to type the exact popup text.

Ask OpenClaw:

```text
Use in_game_issue_report with description "annoying popup after loading a save". Do not ask me for exact text unless the first scan is weak.
```

What OpenClaw should call:

```text
in_game_issue_report
```

What to look for:

- `issue.kind=popup`
- UI/interface, script, SKSE, config, FOMOD, and MCM evidence
- `diagnosticQuality`
- `nextBestInputs`

Human next step:

If the first result is weak, provide a screenshot/OCR or exact popup text and
rerun. If the result is strong, test in a cloned Vortex profile before changing
mods.

## Workflow 5: Large Collection Review

Use this when the mod list is huge and you want to know what is safe to review
for removal.

Ask OpenClaw:

```text
Use mod_knowledge_report to write a Markdown report explaining what each mod appears to do, how it fits into the collection, and which mods are safe candidates to review for disabling. Do not apply changes.
```

What OpenClaw should call:

```text
mod_knowledge_report
scan_cache_status
```

What to look for:

- removal review shortlist
- no-game-file or documentation-only mods
- duplicate plugins or duplicate Nexus ids
- high-risk conflict examples
- mods with missing masters

Human next step:

Review candidates in a cloned profile. Disable, deploy, test, then decide
whether to uninstall later. Keep the scan cache enabled unless results look
stale after many file changes.

## Workflow 6: Collection Drift Or Missing Collection Mods

Use this when a Nexus collection downloaded but something seems missing or out
of sync.

Ask OpenClaw:

```text
Use vortex_collection_report and nexus_update_report to inspect collection-like state and local Nexus metadata. Do not install, update, or remove mods.
```

If you have a manifest-like JSON file:

```text
Use collection_local_match_report with this manifest path: C:\path\collection.json. Compare it to local staged Nexus metadata. Do not change Vortex.
```

What OpenClaw should call:

```text
vortex_collection_report
collection_local_match_report
nexus_update_report
```

What to look for:

- missing expected Nexus mod ids
- pinned file-id mismatches
- expected mods disabled in the selected profile
- local Nexus mods that are not part of the supplied manifest

Human next step:

Use Vortex's collection UI for installs/updates. Do not auto-update a collection
from metadata alone because collections often pin older compatible versions.

## Workflow 7: Safe Profile Experiment And Undo

Use this before testing mod disables or profile changes.

Ask OpenClaw:

```text
Use vortex_profile_backup with include_all_profiles=true. Then create a dry-run plan to clone my active profile as "OpenClaw Safe Test". Do not apply until I approve.
```

What OpenClaw should call:

```text
vortex_profile_backup
vortex_clone_profile with apply=false
```

After approval:

```text
vortex_clone_profile with apply=true
```

Undo preview:

```text
vortex_profile_restore_plan with apply=false
```

Human next step:

Close Vortex before profile writes. Reopen Vortex afterward, choose the intended
profile, deploy, and test. Keep the backup path.

## Workflow 8: Bug Report For OpenClaw Or Maintainers

Use this when a tool fails, the output is confusing, or you need help.

Ask OpenClaw:

```text
Use log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Summarize the highest-risk findings and tell me where the zip was written. Do not apply changes.
```

What OpenClaw should call:

```text
log_status
bug_report_bundle
```

What to look for:

- setup blockers
- recent tool errors
- Vortex CLI timeouts or database locks
- deployment/profile mismatch
- missing masters

Human next step:

Attach the zip to a bug report or ask OpenClaw to read it. Review it first
because it may contain mod names, plugin names, and unusual custom paths.

## Quick Cheat Sheet

| User says | Best first tool |
| --- | --- |
| "Is this set up right?" | `validate_setup` |
| "Mods are not showing in Skyrim" | `skyrim_diagnostics_report` |
| "Wrong Vortex profile?" | `vortex_profile_report` |
| "Downloaded but not deployed?" | `vortex_profile_deployment_report` |
| "Missing masters or crash?" | `plugin_report` |
| "What mod added this thing?" | `in_game_issue_report` |
| "I have a FormID" | `xedit_diagnostics_report` |
| "Annoying popup" | `in_game_issue_report` |
| "What can I remove?" | `mod_knowledge_report` |
| "Collection seems off" | `vortex_collection_report` |
| "OpenClaw got confused" | `bug_report_bundle` |

## Golden Rule

Reports first, backups second, cloned-profile tests third, real changes last.
