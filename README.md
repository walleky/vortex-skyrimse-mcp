# Vortex Skyrim SE MCP

[![CI](https://github.com/walleky/vortex-skyrimse-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/walleky/vortex-skyrimse-mcp/actions/workflows/ci.yml)

Local diagnostics tool for Windows Vortex or Mod Organizer 2 + Skyrim Special Edition. It can run
as an MCP server or as a normal command-line tool. It also supports OpenClaw
running inside WSL2 by mapping Windows paths through `/mnt/c` and checking
Windows interop for Vortex profile tools and Windows-drive visibility for MO2
profile scans.

It is built for an MCP client such as OpenClaw, Claude Desktop, Cursor, or any
stdio MCP client. The server is dependency-free Python and talks newline-delimited
JSON-RPC over stdin/stdout. Direct CLI mode uses the same tools without needing
an MCP client.

## What It Can Do

- Find Steam, Skyrim SE, Vortex AppData, Vortex staging folders, `plugins.txt`,
  `loadorder.txt`, SKSE, and common missing-path problems.
- Let OpenClaw running in WSL2 see Windows Steam/Vortex/Skyrim paths through
  `/mnt/c`, with a dedicated `wsl_bridge_report` for setup failures.
- Validate the whole setup in one call for OpenClaw with `validate_setup`.
- Recommend a safe next workflow from a plain-language problem with `workflow_guide`.
- Inventory Vortex-staged Skyrim SE mods.
- Detect Mod Organizer 2 global/portable instances, selected profiles, `mods`,
  `profiles`, and `overwrite` folders.
- Read MO2 `modlist.txt`, `plugins.txt`, `loadorder.txt`, and `archives.txt`,
  then build a virtual-profile plugin report without pretending MO2 deploys
  files into Skyrim `Data`.
- Diagnose MO2 missing enabled mod folders, missing enabled plugins, missing
  masters, SKSE readiness, common known-rule problems, and approximate
  loose-file conflicts.
- Run known-rule checks during inventory for common stack problems such as
  FNIS + Pandora, FSMPM without JContainers, and SLAL/Leito without FNIS.
- Read mod evidence: files, readmes, FOMOD XML, plugins, masters, BSA archives,
  SKSE DLL plugins, scripts, meshes, textures, UI files.
- Triage in-game weirdness such as misplaced objects or annoying popups by
  searching staged mods for location, object, plugin, readme, popup wording,
  important file paths, limited config/text evidence, UI/script/MCM evidence,
  and optional exact popup text.
- Read recent Skyrim/Papyrus/SKSE/crash logs, detect config and popup-style
  errors such as "file was not configured properly", and map referenced files
  back to staged Vortex mods when possible.
- Poll Skyrim/Papyrus/SKSE/crash logs with saved cursors using
  `skyrim_runtime_log_watch`, so OpenClaw can catch newly appended errors while
  you reproduce a problem without rescanning old log text every time.
- Group repeated runtime log errors into issue patterns, warn when logs look
  stale, and validate candidate config files before proposing a patch.
- Detect likely redundant mods:
  - duplicate plugin names
  - duplicate Nexus IDs when metadata is present
  - file-set subsets, optionally using SHA-256 hashes
- Detect loose-file conflicts between staged mods.
  Each conflict includes a plain-language risk explanation and safer next
  action so OpenClaw can explain why scripts/SKSE/plugins matter more than
  harmless duplicates.
- Detect missing masters and enabled plugins that are missing on disk.
- Use a local scan cache to make repeated large-collection diagnostics faster.
- Avoid rewriting cache files when repeated scans are pure cache hits.
- Give read-only xEdit/SSEEdit target hints from FormIDs and plugin names, and
  generate read-only xEdit inspection scripts that export matching selected
  records to CSV for OpenClaw to summarize.
- Summarize imported case evidence such as popup OCR text, console FormIDs,
  cells, objects, and screenshot notes so OpenClaw can reuse captured evidence
  without asking the user to retype it.
- Inspect Vortex collection-like state when Vortex exposes it, and compare a
  manifest-like collection JSON file to locally staged Nexus mod/file metadata.
- Inspect Skyrim INI settings and apply a narrow safe set of INI fixes with
  backups. INI writes are dry-run by default.
- Patch exact text in staged config/text files with `apply_config_text_patch`.
  It is dry-run by default, restricted to detected Vortex/Skyrim roots, and
  creates backups when writing.
- Validate config files with `config_file_report` before patching: JSON/XML/INI,
  loose key/value configs, TOML parse status, top-level structure, common
  "not configured" clues, and exact-text patch suggestions for obvious
  `configured=false` style values.
- Read Vortex profiles through Vortex's own CLI, show the active-profile guess,
  list enabled/disabled mods per profile, compare profiles, and clone a profile
  for safer testing.
- Write Vortex profile backups and preview restore/undo plans before changing a
  profile.
- Turn risky automation requests into backup-first, cloned-profile-first,
  revert-aware plans with `vortex_reversible_automation_plan`.
- Write a no-change safe session report that combines setup validation, optional
  profile backup, play health, in-game issue triage, and log status.
- Write a one-button `skyrim_diagnostics_report` for OpenClaw or local CLI use:
  setup, deployment, SKSE/audio/INI health, profile state, logs, issue triage,
  and optional Nexus metadata in one no-change report.
- Use `performance_mode=slow_model` or `response_mode=compact` so slower
  OpenClaw models get smaller, easier-to-read diagnostics.
- Use optional read-only Nexus Mods API metadata with this MCP's own configured
  key, not Vortex's key: validate the key, parse NXM links, lookup mod/file
  metadata, MD5-match archives, and compare local staged mods to current Nexus
  versions/source metadata.
- Check whether plugins from the selected Vortex profile appear in Skyrim
  `Data` and are enabled in `plugins.txt`.
- Verify critical deployed files such as SKSE DLLs, Papyrus scripts, and
  behavior/animation output files instead of relying only on random samples.
- Check whether the next launch should use SKSE, Steam/vanilla, or stop for
  deployment/SKSE fixes first.
- Check whether Skyrim's runtime version matches the installed SKSE runtime DLL
  target and Address Library evidence.
- Produce a one-shot modded play report that combines environment, SKSE, audio
  archive, profile deployment, plugin, and INI checks into prioritized findings.
- Enable or disable exact Vortex mod ids in a selected profile only when
  `apply=true`. This is dry-run by default and never deletes mods.
- Write a JSON report that another agent can analyze.
- Write MCP logs by area (`server`, `tool`, `vortex-cli`, `support`) and create
  a bug-report bundle with recent log tails.
- Generate a static read-only HTML report viewer so users and OpenClaw can
  browse generated reports without digging through folders.
- Run the same tools directly from PowerShell for no-OpenClaw workflows.

## Documentation

- [START-HERE.md](START-HERE.md): short install, first prompts, and MCP Doctor.
- [docs/WSL-OPENCLAW.md](docs/WSL-OPENCLAW.md): OpenClaw-in-WSL2 setup for Windows Vortex/Steam/Skyrim.
- [docs/MO2-SUPPORT.md](docs/MO2-SUPPORT.md): Mod Organizer 2 profile diagnostics, virtual Data behavior, and launch rules.
- [docs/WORKFLOW-EXAMPLES.md](docs/WORKFLOW-EXAMPLES.md): copy-paste examples for common OpenClaw and PowerShell workflows.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): code map and runtime flow.
- [docs/CLI.md](docs/CLI.md): direct command-line mode without an MCP client.
- [docs/LOCAL-MENU.md](docs/LOCAL-MENU.md): local no-hassle menu for report generation.
- [docs/SAFE-SESSION.md](docs/SAFE-SESSION.md): one safe first report for OpenClaw or local troubleshooting.
- [docs/SKYRIM-DIAGNOSTICS.md](docs/SKYRIM-DIAGNOSTICS.md): broad one-button Skyrim SE diagnostics.
- [docs/DEPLOYMENT-DOCTOR.md](docs/DEPLOYMENT-DOCTOR.md): quickest profile-to-Skyrim deployment verdict.
- [docs/LAUNCH-DOCTOR.md](docs/LAUNCH-DOCTOR.md): quickest SKSE vs Steam/vanilla launch-route verdict.
- [docs/SKSE-RUNTIME-DOCTOR.md](docs/SKSE-RUNTIME-DOCTOR.md): SKSE runtime/build compatibility checks.
- [docs/REVERSIBLE-AUTOMATION.md](docs/REVERSIBLE-AUTOMATION.md): safety gate for risky automation and undo-aware plans.
- [docs/REPORT-VIEWER.md](docs/REPORT-VIEWER.md): static read-only HTML index for generated reports.
- [docs/SKYRIM-RUNTIME-LOGS.md](docs/SKYRIM-RUNTIME-LOGS.md): Papyrus/SKSE/crash log scanning and safe config patch workflow.
- [docs/RUNTIME-LOG-WATCH.md](docs/RUNTIME-LOG-WATCH.md): polling-style runtime log watching for OpenClaw and slower models.
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md): compact outputs and slow-model guidance.
- [docs/NEXUS-API.md](docs/NEXUS-API.md): optional read-only Nexus Mods API setup and tools.
- [docs/NEXUS-MODS-API-DESIGN.md](docs/NEXUS-MODS-API-DESIGN.md): Nexus API metadata design and roadmap.
- [docs/SCAN-CACHE.md](docs/SCAN-CACHE.md): local scan cache behavior, safety, and performance tips.
- [docs/XEDIT-DIAGNOSTICS.md](docs/XEDIT-DIAGNOSTICS.md): read-only xEdit/SSEEdit target hints, inspection scripts, and CSV result parsing.
- [docs/COLLECTION-DIAGNOSTICS.md](docs/COLLECTION-DIAGNOSTICS.md): Vortex collection-state and manifest matching.
- [docs/CONFLICT-EXPLAINER.md](docs/CONFLICT-EXPLAINER.md): conflict risk levels and safe interpretation.
- [docs/ADR-0001-NEXUS-API-KEYS.md](docs/ADR-0001-NEXUS-API-KEYS.md): why this MCP uses its own explicit Nexus key instead of Vortex's key.
- [docs/SAFETY-UNDO.md](docs/SAFETY-UNDO.md): backup, restore-preview, and dry-run rules.
- [docs/IN-GAME-DIAGNOSIS.md](docs/IN-GAME-DIAGNOSIS.md): how to ask OpenClaw about misplaced objects, popups, FormIDs, and future live Skyrim bridging.
- [docs/OPENCLAW-AGENT-GUIDE.md](docs/OPENCLAW-AGENT-GUIDE.md): how an OpenClaw agent should use the tools safely.
- [docs/VORTEX-MCP-BRIDGE-COMPARISON.md](docs/VORTEX-MCP-BRIDGE-COMPARISON.md): what this project borrows from Vortex MCP Bridge and what stays out of scope.
- [docs/LOGGING.md](docs/LOGGING.md): log folder, channels, and inspection commands.
- [docs/BUG-REPORTING.md](docs/BUG-REPORTING.md): support bundle and issue-reporting guide.
- [docs/VERCEL.md](docs/VERCEL.md): static public docs site deployment notes.
- [docs/MOD-KNOWLEDGE.md](docs/MOD-KNOWLEDGE.md): collection knowledge reports and safe removal review.
- [docs/KNOWN-MOD-RULES.md](docs/KNOWN-MOD-RULES.md): built-in common conflict/dependency rules.
- [docs/SAMPLE-BUG-BUNDLE.md](docs/SAMPLE-BUG-BUNDLE.md): sanitized example support bundle shape.
- [docs/ROADMAP.md](docs/ROADMAP.md): improvement notes and what not to automate yet.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [SUPPORT.md](SUPPORT.md): maintainer, security, and support process.

## What It Will Not Do Automatically

It does not blindly delete mods, disable plugins, rewrite conflict rules, or sort
load order. Vortex conflict rules and load-order changes are high-risk because
the wrong winner can break a save. Profile write tools require exact mod ids and
are dry-run unless `apply=true`.

For MO2, the MCP is read-only. It does not edit `modlist.txt`, `plugins.txt`,
or priorities. Skyrim, SKSE, and xEdit must be launched through MO2 for the
selected profile's virtual files to appear.

## Install

Short version: see [START-HERE.md](START-HERE.md).

1. Install Python 3 for Windows if you do not already have it.
2. Download or clone this repo somewhere stable, for example:

```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/walleky/vortex-skyrimse-mcp.git
cd vortex-skyrimse-mcp
```

Or keep the folder at:

```text
C:\Users\<you>\Documents\vortex-skyrimse-mcp
```

3. In PowerShell:

```powershell
cd C:\Users\<you>\Documents\vortex-skyrimse-mcp
.\install_windows.ps1
```

The installer prints an MCP config snippet.

If OpenClaw runs inside WSL2, use the WSL installer instead:

```bash
cd /mnt/c/Users/<you>/Documents/vortex-skyrimse-mcp
bash install_wsl.sh
```

See [docs/WSL-OPENCLAW.md](docs/WSL-OPENCLAW.md) for the exact WSL/OpenClaw config.

## MCP Doctor

For a no-hassle check, run:

```powershell
.\mcp_doctor.ps1
```

Or double-click:

```text
MCP-Doctor.cmd
```

MCP Doctor runs the self-test, runs the MCP stdio smoke test, writes
`openclaw.mcp.generated.json`, prints the OpenClaw registration command, and can
open the OpenClaw config folder. To register through the OpenClaw CLI:

```powershell
.\mcp_doctor.ps1 -RegisterOpenClaw
```

If Windows cannot find `py` or `python`, point Doctor at Python directly:

```powershell
.\mcp_doctor.ps1 -PythonCommand "C:\Path\To\python.exe"
```

## MCP Client Config

Generic stdio MCP config:

```json
{
  "mcpServers": {
    "vortex-skyrimse": {
      "command": "py",
      "args": [
        "-3",
        "C:\\Users\\<you>\\Documents\\vortex-skyrimse-mcp\\server.py"
      ]
    }
  }
}
```

Restart OpenClaw after adding the server.

For OpenClaw running inside WSL2, use [openclaw.mcp.wsl.example.json](openclaw.mcp.wsl.example.json) or run:

```bash
bash install_wsl.sh
```

## Direct CLI Mode

You can run tools without OpenClaw:

```powershell
py -3 .\server.py --tool detect_environment
py -3 .\server.py --tool validate_setup
py -3 .\server.py --tool wsl_bridge_report
py -3 .\server.py --workflow-guide --problem "mods downloaded but not working"
py -3 .\server.py --tool scan_cache_status
py -3 .\server.py --tool xedit_diagnostics_report --form-id 0100ABCD
py -3 .\server.py --issue-case --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed" --form-id 0100ABCD
py -3 .\server.py --issue-case-status --case-dir "C:\path\to\issue-case-folder"
py -3 .\server.py --what-now --case-dir "C:\path\to\issue-case-folder"
py -3 .\server.py --safe-experiment-plan --case-dir "C:\path\to\issue-case-folder"
py -3 .\server.py --case-note --case-dir "C:\path\to\issue-case-folder" --note "Tested candidate in cloned profile; issue still appears."
py -3 .\server.py --case-evidence --case-dir "C:\path\to\issue-case-folder" --evidence-kind popup_ocr --ocr-text "captured popup text"
py -3 .\server.py --case-inbox --case-dir "C:\path\to\issue-case-folder"
py -3 .\server.py --case-bundle --case-dir "C:\path\to\issue-case-folder"
py -3 .\server.py --safe-profile-fix --new-profile-name "OpenClaw Fixed Test" --disable-mod-id "exact-vortex-mod-id"
py -3 .\server.py --tool vortex_collection_report
py -3 .\server.py --deployment-doctor
py -3 .\server.py --deployment-doctor --baseline-path ".\deployment-doctor-before.json" --output-path ".\deployment-doctor-after.md"
py -3 .\server.py --launch-doctor
py -3 .\server.py --skse-doctor
py -3 .\server.py --automation-plan --request "disable unwanted mods and sort safely"
py -3 .\server.py --runtime-logs --description "popup says file was not configured properly"
py -3 .\server.py --skyrim-diagnostics
py -3 .\server.py --mo2-diagnostics
py -3 .\server.py --safe-session
py -3 .\server.py --mod-knowledge
py -3 .\server.py --known-rules
```

For huge collections, keep the scan cache on. It is compact and self-pruning by
default; use `--scan-cache-max-entries 5000` only if `scan_cache_status` shows
the cache growing too large for the machine.

Or double-click:

```text
Vortex-SkyrimSE-Menu.cmd
Make-Mod-Knowledge.cmd
```

See [docs/LOCAL-MENU.md](docs/LOCAL-MENU.md) for the menu and
[docs/CLI.md](docs/CLI.md) for options such as `--staging-dir`, `--hash-files`,
and `--no-profile-state`.

## First OpenClaw Prompts

Try:

```text
Use skyrim_diagnostics_report to write a no-change first report with setup validation, profile backup if possible, modded play health, logs, and Nexus metadata if available. Summarize the top findings and do not apply changes.
```

Or start narrower:

```text
Use the vortex-skyrimse MCP to run validate_setup, then detect my Skyrim SE/Vortex environment and list the highest-risk problems. Do not apply changes.
```

Then:

```text
Use the vortex-skyrimse MCP to find missing masters, likely redundant mods, and sensitive file conflicts. Do not apply changes yet.
```

For profiles:

```text
Use the vortex-skyrimse MCP to list my Skyrim SE Vortex profiles, identify the active one, and show enabled mods on that profile.
```

Before any profile experiment:

```text
Use vortex_profile_backup with include_all_profiles=true and tell me where the backup was written. Do not apply other changes.
```

For a visible in-game issue:

```text
Use skyrim_issue_case_packet for this issue: there is a bed outside the tavern room in Whiterun. Include location Whiterun Bannered Mare and object bed. Do not apply changes.
```

After running the generated xEdit script:

```text
Use skyrim_issue_case_status on the case folder and tell me the top xEdit evidence. Do not apply changes.
```

Then ask for a safe next step or a test plan:

```text
Use skyrim_case_what_now on the case folder. Then write a skyrim_safe_experiment_plan. Do not apply changes.
```

During testing:

```text
Append this to the case notes: disabled the candidate in a cloned profile and the bed disappeared.
```

For captured popup/FormID evidence:

```text
Import this live evidence into the case: OCR text says "file was not configured properly" and clicked FormID is 0100ABCD.
```

To make a safer test profile:

```text
Use vortex_clone_profile to clone my active Skyrim SE profile as "OpenClaw Safe Test". Keep it as a dry run first.
```

For deployment/profile mismatch:

```text
Use deployment_doctor_report to check whether my active Skyrim SE Vortex profile is actually linked to Skyrim Data and plugins.txt. Do not apply changes.
```

For a single no-hassle diagnosis:

```text
Use skyrim_diagnostics_report to tell me why my modded Skyrim SE setup is not launching with the expected Vortex profile. Do not apply changes.
```

For slower OpenClaw models or very large collections:

```text
Use skyrim_diagnostics_report with performance_mode=slow_model. Start from the summary, findings, and nextActions. Do not apply changes.
```

For a large collection map:

```text
Use mod_knowledge_report to write a Markdown report explaining what each Skyrim SE mod appears to do, how it fits into the collection, and which mods are safe candidates to review for disabling. Do not apply changes.
```

For an in-game object or popup:

```text
Use in_game_issue_report to find likely mods causing this: there is an annoying popup after loading a save. Do not apply changes.
```

If you can open Skyrim's console for placed objects, click the bad object and include the shown FormID/base object. For popups, exact text or a screenshot/OCR can help later, but OpenClaw should run the first popup scan from your plain description.

For a FormID or xEdit target:

```text
Use xedit_diagnostics_report with form_id 0100ABCD and tell me the likely plugin to inspect. Do not edit plugins.
```

For collection drift:

```text
Use vortex_collection_report and nexus_update_report to check whether my local collection state and Nexus metadata look consistent. Do not install, update, or remove mods.
```

For INI fixes:

```text
Use the vortex-skyrimse MCP to show Skyrim INI fixes as a dry run.
```

To apply only the narrow INI fixes:

```text
Use apply_ini_fixes with dry_run=false and make_backup=true.
```

## Tools

- `detect_environment`
- `validate_setup`
- `inventory_mods`
- `analyze_conflicts`
- `redundant_mod_report`
- `plugin_report`
- `mod_evidence`
- `mod_knowledge_report`
- `nexus_validate_key`
- `nexus_mod_lookup`
- `nexus_mod_files`
- `nexus_file_info`
- `nexus_file_by_md5`
- `nexus_parse_nxm_link`
- `nexus_update_report`
- `in_game_issue_report`
- `safe_session_report`
- `skyrim_diagnostics_report`
- `ini_report`
- `apply_ini_fixes`
- `read_text_file`
- `vortex_cli_get`
- `vortex_profile_report`
- `vortex_profile_mods`
- `vortex_compare_profiles`
- `vortex_profile_deployment_report`
- `deployment_doctor_report`
- `skyrim_launch_doctor_report`
- `skse_runtime_doctor_report`
- `skyrim_issue_case_packet`
- `skyrim_issue_case_status`
- `skyrim_issue_case_note`
- `skyrim_safe_experiment_plan`
- `skyrim_case_what_now`
- `skyrim_live_bridge_status`
- `skyrim_case_evidence_import`
- `skyrim_case_inbox_import`
- `skyrim_case_evidence_report`
- `skyrim_case_bundle`
- `vortex_profile_backup`
- `vortex_profile_restore_plan`
- `vortex_clone_profile`
- `vortex_set_profile_mods`
- `vortex_reversible_automation_plan`
- `skyrim_modded_play_report`
- `suggest_conflict_fixes`
- `log_status`
- `report_viewer_index`
- `bug_report_bundle`
- `write_report`

Every path-taking tool accepts explicit override paths, which helps if Vortex is
using a custom staging folder.

## Path Overrides

Useful Windows paths:

```text
Vortex AppData:
%APPDATA%\Vortex

Typical Vortex Skyrim SE staging:
%APPDATA%\Vortex\skyrimse\mods

Skyrim SE Steam folder:
C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition

Plugins file:
%LOCALAPPDATA%\Skyrim Special Edition\plugins.txt

Skyrim INIs:
%USERPROFILE%\Documents\My Games\Skyrim Special Edition
```

If detection misses your setup, pass `skyrim_dir`, `staging_dir`,
`vortex_appdata`, `local_appdata`, or `my_games_dir` to the relevant tool.

## Safety Model

- `detect_environment`, `validate_setup`, `inventory_mods`, `analyze_conflicts`,
  `redundant_mod_report`, `plugin_report`, `mod_evidence`,
  `mod_knowledge_report`, Nexus metadata tools, `in_game_issue_report`,
  `ini_report`, `safe_session_report`, `skyrim_diagnostics_report`,
  `read_text_file`, `vortex_cli_get`, `vortex_profile_report`,
  `vortex_profile_mods`, `vortex_compare_profiles`,
  `vortex_profile_deployment_report`, `deployment_doctor_report`,
  `skyrim_modded_play_report`,
  issue-case tools, `suggest_conflict_fixes`, `log_status`, `report_viewer_index`,
  `bug_report_bundle`, and
  `write_report` do not modify Vortex or Skyrim.
- `apply_ini_fixes` can write INI files only when `dry_run=false`.
- `apply_ini_fixes` creates backups by default.
- `vortex_clone_profile` and `vortex_set_profile_mods` can write Vortex profile
  state only when `apply=true`.
- `vortex_clone_profile` and `vortex_set_profile_mods` write a profile backup
  before `apply=true` unless `backup_before_apply=false`.
- `vortex_profile_restore_plan` previews restore actions by default and writes
  only when `apply=true`.
- Close Vortex before profile writes. Reopen Vortex afterward, select the wanted
  profile, then deploy mods before launching Skyrim.
- The write tools refuse `apply=true` while `Vortex.exe` is running unless
  `allow_running_vortex=true` is passed for advanced recovery work.
- Profile writes use Vortex.exe `--set` instead of editing Vortex's database
  files directly.
- Large profile clones are written in smaller CLI batches to avoid Windows
  command-line length failures on big Nexus Collections.
- `read_text_file` refuses to read outside detected Vortex/Skyrim roots unless
  `allow_any_path=true`.
- `in_game_issue_report` is read-only and heuristic. It identifies candidates;
  it does not edit plugins, delete mods, or remove placed objects.
- `in_game_issue_report` defaults to `scan_mode=balanced`: a broader first pass
  that still avoids reading every text/config file. Use `scan_mode=deep` or
  `deep_scan_files=true` only for slower second-pass searches.

## Vortex Profile Notes

Vortex profiles let different playthroughs have different enabled mod lists, and
Vortex can clone profiles in its own UI. This MCP mirrors that safety idea for
OpenClaw: first inspect, then clone, then apply exact profile changes only after
you approve them.

If OpenClaw wants to experiment, the safer flow is:

1. Run `validate_setup`.
2. Run `vortex_profile_report`.
3. Run `vortex_profile_backup` with `include_all_profiles=true`.
4. Run `vortex_clone_profile` with `apply=false`.
5. Close Vortex.
6. Run `vortex_clone_profile` with `apply=true`.
7. Reopen Vortex, enable the new profile, deploy mods, and test Skyrim.

If the test goes wrong, run `vortex_profile_restore_plan` with the backup path
and `apply=false` first. Only use `apply=true` after reading the plan.

For exact mod toggles, run `vortex_profile_mods` first and copy the exact `id`
values into `vortex_set_profile_mods`. Do not guess mod ids.

If Skyrim launches but the mods do not show up, run
`deployment_doctor_report`. It checks the common mismatch: Vortex says a mod is
enabled on a profile, but plugin/sample files are not deployed into Skyrim
`Data` or the plugin is not enabled in `%LOCALAPPDATA%\Skyrim Special Edition\plugins.txt`.

If you are not sure whether to launch through SKSE or Steam/vanilla, run
`skyrim_launch_doctor_report`. It checks the selected profile, deployment state,
SKSE files, and launch target before you touch a real save.

If SKSE itself looks suspicious, run `skse_runtime_doctor_report`. It checks the
Skyrim runtime, SKSE target DLL, SKSE scripts, and Address Library evidence.

If you want OpenClaw to automate something risky, start with
`vortex_reversible_automation_plan`. It explains what can be tested safely in a
cloned Vortex profile, what must stay in Vortex/xEdit, and how to undo.

For the broadest first pass, run `skyrim_modded_play_report`. It adds SKSE,
missing audio archive, missing master, stale `plugins.txt`, and INI checks, then
sorts the findings by severity.

## Testing

Run the full local test suite:

```powershell
py -3 .\tests\run_all.py
```

On Linux/macOS:

```bash
python3 tests/run_all.py
```

The runner compiles the server, runs self-test, MCP stdio smoke tests, fixture
integration tests, config/runtime regression tests, and PowerShell helper checks
when PowerShell is available. See [Testing](docs/TESTING.md) for details.

## Manual Smoke Test

```powershell
py -3 .\server.py --self-test
```

MCP handshake test:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"1"}}}' | py -3 .\server.py
```

You should get a JSON-RPC response with `serverInfo.name` equal to
`vortex-skyrimse-mcp`.

## Notes For Maintainers

This server intentionally avoids a dependency on Vortex internals. Current Vortex
state persistence has changed over time, and broad state writes are risky. The
profile tools use Vortex's public CLI path for `--get`/`--set` and keep writes
small, explicit, and dry-run by default.

Sources used for protocol behavior:

- MCP stdio transport requires UTF-8 JSON-RPC messages delimited by newlines:
  https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- MCP tools are listed with `tools/list` and invoked with `tools/call`:
  https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- Vortex profiles are documented as separate mod lists/settings/saves:
  https://github.com/Nexus-Mods/Vortex/wiki/MODDINGWIKI-Users-General-Setting-up-Profiles
- Public Vortex MCP Bridge listing used for feature comparison:
  https://www.nexusmods.com/site/mods/1743
