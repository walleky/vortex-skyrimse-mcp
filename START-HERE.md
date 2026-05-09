# Start Here

This is the short path for using the Vortex Skyrim SE MCP with OpenClaw or another stdio MCP client.

## Install

Open PowerShell:

```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/walleky/vortex-skyrimse-mcp.git
cd vortex-skyrimse-mcp
.\install_windows.ps1
```

Copy the printed MCP config into OpenClaw, then restart OpenClaw.

If OpenClaw runs inside WSL2 but Vortex/Steam/Skyrim are Windows apps:

```bash
cd /mnt/c/Users/<you>/Documents/vortex-skyrimse-mcp
bash install_wsl.sh
python3 server.py --wsl-bridge
```

Use the config printed by `install_wsl.sh`. More detail is in
[docs/WSL-OPENCLAW.md](docs/WSL-OPENCLAW.md).

## No-Hassle Doctor

For the easiest check, double-click:

```text
MCP-Doctor.cmd
```

Or run:

```powershell
.\mcp_doctor.ps1
```

## No-OpenClaw Mod Map

To open the local helper menu, double-click:

```text
Vortex-SkyrimSE-Menu.cmd
```

To make the Markdown collection report directly, double-click:

```text
Make-Mod-Knowledge.cmd
```

Or run:

```powershell
.\make_mod_knowledge.ps1
```

This calls the same `mod_knowledge_report` tool without needing OpenClaw.

To make one browser page for the reports folder, run:

```powershell
.\vortex_skyrimse_menu.ps1 -Action report-viewer
```

Then open `Documents\vortex-skyrimse-mcp-reports\report-viewer.html`.

MCP Doctor runs the server self-test, runs the MCP handshake smoke test, writes
`openclaw.mcp.generated.json`, prints the OpenClaw registration command, and can
open the OpenClaw config folder. It also writes a transcript log under the MCP
log folder.

To let it register the server through the OpenClaw CLI:

```powershell
.\mcp_doctor.ps1 -RegisterOpenClaw
```

## First Prompts

For complete examples, see [docs/WORKFLOW-EXAMPLES.md](docs/WORKFLOW-EXAMPLES.md).

Start read-only:

```text
Use workflow_guide for this problem: mods downloaded but not working. Tell me the recommended safe tool sequence and do not apply changes.
```

Then run the recommended first report, or start directly with:

```text
Use skyrim_diagnostics_report to write a no-change first report with setup validation, profile backup if possible, modded play health, logs, and Nexus metadata if available. Summarize the top findings and do not apply changes.
```

If OpenClaw is using a slower model or the collection is huge:

```text
Use skyrim_diagnostics_report with performance_mode=slow_model. Read the summary, findings, and nextActions first. Do not apply changes.
```

Or start with only setup:

```text
Use the vortex-skyrimse MCP to run validate_setup, then detect my Skyrim SE/Vortex environment and list the highest-risk problems. Do not apply changes.
```

If OpenClaw is inside WSL2:

```text
Use wsl_bridge_report, then validate_setup. Tell me whether OpenClaw can see Windows Vortex, Steam, Skyrim SE, staging, plugins.txt, and whether profile tools can call Vortex.exe. Do not apply changes.
```

If you use Mod Organizer 2 instead of Vortex:

```text
Use workflow_guide for this problem: MO2 Skyrim mods are not working. Then run mo2_modded_play_report. Tell me whether the selected MO2 profile, enabled mods, plugins, missing masters, and SKSE route look ready. Do not apply changes.
```

Direct MO2 check:

```powershell
py -3 .\server.py --mo2-diagnostics
```

MO2 rule of thumb: launch SKSE, Skyrim, and xEdit from MO2's Run dropdown so
the selected profile's virtual files are visible.

For Vortex setups, then check whether Vortex's active profile is really deployed:

```text
Use deployment_doctor_report to tell me whether my selected Vortex profile is linked to Skyrim Data and plugins.txt. Do not apply changes.
```

After you deploy in Vortex, rerun Deployment Doctor with the previous JSON as a
baseline so OpenClaw can explain what improved or regressed.

Then check the safest launch route:

```text
Use skyrim_launch_doctor_report. Tell me whether I should launch through SKSE, Steam/vanilla, or fix deployment/SKSE first. Do not launch or change anything.
```

Optional Nexus metadata:

```powershell
setx NEXUS_MODS_API_KEY "paste-your-key-here"
```

Close and reopen OpenClaw after setting the variable. The MCP uses your
explicit key only; it does not copy Vortex's key.

To validate the key:

```powershell
py -3 .\server.py --tool nexus_validate_key
```

For redundant mods and conflicts:

```text
Use the vortex-skyrimse MCP to find missing masters, likely redundant mods, and sensitive file conflicts. Do not apply changes yet.
```

For performance on huge collections:

```text
Use scan_cache_status to show whether the local scan cache is enabled. Keep it enabled unless the result looks stale.
```

The scan cache is optimized for repeated runs: if everything is a cache hit, the cache file is not rewritten.
It also prunes oldest entries on writes when the cache grows past its configured limit.

For catching errors while testing in-game:

```text
Use skyrim_runtime_log_watch with reset=true. I will reproduce the problem in Skyrim, then call skyrim_runtime_log_watch again and summarize only new critical/high/config findings.
```

This is polling, not a live SKSE event stream, but it is much lighter than
rereading every runtime log on every OpenClaw turn.

For common stack mistakes like FNIS + Pandora or missing JContainers:

```text
Use known_mod_rule_report, then deployment_doctor_report. Summarize known conflict/dependency findings and critical missing deployed files. Do not apply changes.
```

For a big collection knowledge map:

```text
Use the vortex-skyrimse MCP to run mod_knowledge_report. Write the Markdown report, summarize the top removal-review candidates, and do not apply changes.
```

For mods downloaded but not working:

```text
Use deployment_doctor_report first. Tell me whether my selected Vortex profile is linked to Skyrim Data and plugins.txt. Do not apply changes.
```

For SKSE/launch confusion:

```text
Use skyrim_launch_doctor_report. Tell me the recommended launch route and the first blocker if it is not safe to launch yet. Do not launch or change anything.
```

For SKSE version mismatch confusion:

```text
Use skse_runtime_doctor_report. Tell me whether my Skyrim runtime matches SKSE and Address Library evidence. Do not install or change anything.
```

For "automate this but make it reversible":

```text
Use vortex_reversible_automation_plan with this request: disable unwanted mods, sort load order, and keep an undo path. Explain which parts can be tested in a cloned profile and which parts must stay in Vortex/xEdit. Do not apply changes.
```

For something weird inside the game:

```text
Use skyrim_diagnostics_report with this issue: there is a bed outside the tavern room in the Whiterun Bannered Mare. Include in-game issue candidates and do not apply changes.
```

If you have a console FormID, add it and ask for the xEdit target:

```text
Use xedit_diagnostics_report with form_id 0100ABCD and tell me the likely plugin to inspect. Do not edit plugins.
```

If OpenClaw still needs stronger record evidence:

```text
Use xedit_inspection_script for this issue, then after I run the generated script in SSEEdit, use xedit_inspection_result_report on the CSV. Do not save plugin edits.
```

Or make one folder for the whole investigation:

```text
Use skyrim_issue_case_packet for this issue: bed outside the tavern room in Whiterun. Location is Whiterun Bannered Mare and object is bed. Do not apply changes.
```

After you run the generated script in SSEEdit:

```text
Use skyrim_issue_case_status on the case folder and summarize the xEdit CSV evidence. Do not apply changes.
```

For the next safest action:

```text
Use skyrim_case_what_now on the case folder, then create skyrim_safe_experiment_plan. Do not apply changes.
```

To keep the investigation undoable:

```text
Use skyrim_issue_case_note to append this note to the case: tested in cloned profile, result was unchanged.
```

If a screenshot/OCR helper or console capture gives evidence:

```text
Use skyrim_case_evidence_import to add popup OCR text "file was not configured properly", reference FormID 0100ABCD, and cell WhiterunBanneredMare to the case.
```

If a helper writes evidence files instead, put JSON/TXT/LOG files in the case folder's `incoming` directory and ask:

```text
Use skyrim_case_inbox_import on the same case folder, then run skyrim_case_what_now.
```

To summarize captured popup/FormID/cell evidence without retyping it:

```text
Use skyrim_case_evidence_report on the same case folder, then use skyrim_case_what_now.
```

For annoying popups, just say "popup", "notification", "warning", or similar in the description. The first scan is balanced and checks local file/path/config clues automatically. Exact popup text or a screenshot/OCR can help later, but it is not required for the first scan.

If the popup says a file was not configured properly, reproduce it once and ask:

```text
Use skyrim_runtime_log_report for this popup: file was not configured properly. Start with issueGroups and freshLogStatus. Validate any configCandidates with config_file_report, check suggestedTextPatches if present, and propose only a dry-run apply_config_text_patch if the fix is exact. Do not edit plugins or disable mods.
```

No-OpenClaw command:

```powershell
py -3 .\server.py --runtime-logs --description "popup says file was not configured properly"
```

For collection drift:

```text
Use vortex_collection_report to inspect collection state and do not install, update, or remove mods.
```

Before changing a Vortex profile:

```text
Use vortex_profile_backup with include_all_profiles=true and tell me where the backup was written. Then show any requested profile change as a dry run first.
```

To test a fix without touching the original profile:

```text
Use vortex_safe_profile_fix to clone my active profile as "OpenClaw Fixed Test" and disable the exact candidate mod id in the clone only. Preview first.
```

## Bug Reports

If OpenClaw gets stuck or a tool fails:

```text
Use the vortex-skyrimse MCP to run log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Then summarize the highest-risk findings and tell me where the zip was written. Do not apply changes.
```

The bundle redacts normal user profile paths by default, but it may still include mod/plugin names and unusual custom paths. Review it before posting publicly.

## Safety Rules

- Most tools are read-only.
- `apply_ini_fixes` writes only when `dry_run=false`.
- `apply_config_text_patch` writes only when `apply=true` or `dry_run=false`; it replaces exact text and backs up by default.
- `vortex_clone_profile` and `vortex_set_profile_mods` write only when `apply=true`.
- `vortex_safe_profile_fix` clones a profile and applies exact mod-id fixes to the clone only; dry-run is the default.
- Profile write tools create a profile backup before `apply=true` by default.
- `vortex_profile_restore_plan` previews undo actions by default.
- `xedit_diagnostics_report` is read-only and does not launch xEdit or save plugins.
- `skyrim_issue_case_packet` writes a Markdown/JSON case folder plus a read-only xEdit script, but does not change Vortex, Skyrim, or plugins.
- `skyrim_issue_case_status` reads that case folder and generated CSV, then writes a status report without changing Vortex, Skyrim, or plugins.
- `skyrim_safe_experiment_plan` writes a dry-run plan only. It does not clone profiles or disable mods.
- `skyrim_issue_case_note` appends notes in the case folder only.
- `skyrim_case_evidence_import` appends captured evidence in the case folder only.
- `skyrim_case_evidence_report` summarizes captured evidence and suggested
  next diagnostic calls only.
- `skyrim_case_inbox_import` imports new files from the case `incoming` folder and de-dupes them by hash.
- `skyrim_case_bundle` zips a case folder for review; inspect it before posting publicly.
- Collection diagnostics are read-only and do not install, update, remove, or deploy mods.
- Close Vortex before profile writes.
- Reopen Vortex afterward, pick the intended profile, then deploy mods before launching Skyrim.

## Quick Test

```powershell
py -3 .\tests\run_all.py
```

On Linux/macOS:

```bash
python3 tests/run_all.py
```
