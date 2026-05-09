# Local Helper Menu

The local helper menu is for users who do not want to remember command-line flags or set up OpenClaw first.

Run:

```powershell
.\vortex_skyrimse_menu.ps1
```

Or double-click:

```text
Vortex-SkyrimSE-Menu.cmd
```

## Menu Actions

1. Validate setup
2. Create Vortex profile backup
3. Preview restore from backup
4. Environment diagnosis
5. Mod knowledge Markdown report
6. Modded play diagnosis
7. Bug report zip
8. Log status
9. List available tools
10. In-game issue triage
11. Safe session report
12. Skyrim diagnostics report
13. Scan cache status
14. xEdit/SSEEdit target helper
15. Vortex collection state
16. Collection manifest match
17. Workflow guide
18. Skyrim runtime logs
19. Config file validator
20. xEdit inspection script
21. xEdit inspection result
22. Skyrim issue case packet
23. Skyrim issue case status
24. Append issue case note
25. Safe experiment plan
26. What should I do now?
27. Live Skyrim bridge status
28. Import case evidence
29. Bundle issue case
30. Import case inbox
31. Clone profile and apply fixes
32. Deployment Doctor
33. Launch Doctor
34. Reversible Automation Plan
35. SKSE Runtime Doctor
36. Report Viewer
37. Live Evidence Summary
38. Known Mod Rules
39. MO2 Diagnostics
40. Runtime Log Watch

Reports are written to:

```text
Documents\vortex-skyrimse-mcp-reports
```

Use `-ReportDir` if you want another folder.

Unless you already set `VORTEX_SKYRIMSE_MCP_LOG_DIR`, menu-run logs are written under the same reports folder in `logs`.

## Noninteractive Use

Run one action directly:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge
.\vortex_skyrimse_menu.ps1 -Action bug
.\vortex_skyrimse_menu.ps1 -Action play
.\vortex_skyrimse_menu.ps1 -Action validate
.\vortex_skyrimse_menu.ps1 -Action backup
.\vortex_skyrimse_menu.ps1 -Action restore -BackupPath "C:\path\profile-backup.json"
.\vortex_skyrimse_menu.ps1 -Action ingame -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed" -FormId "1200ABCD"
.\vortex_skyrimse_menu.ps1 -Action safe
.\vortex_skyrimse_menu.ps1 -Action safe -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed"
.\vortex_skyrimse_menu.ps1 -Action diagnostics
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeNexusMetadata
.\vortex_skyrimse_menu.ps1 -Action cache
.\vortex_skyrimse_menu.ps1 -Action xedit -FormId "0100ABCD"
.\vortex_skyrimse_menu.ps1 -Action collection
.\vortex_skyrimse_menu.ps1 -Action collection-match -CollectionManifestPath "C:\path\collection.json"
.\vortex_skyrimse_menu.ps1 -Action workflow -Problem "mods downloaded but not working"
.\vortex_skyrimse_menu.ps1 -Action runtime -IssueDescription "popup says file was not configured properly"
.\vortex_skyrimse_menu.ps1 -Action runtime-watch -RuntimeWatchId playtest -ResetRuntimeWatch
.\vortex_skyrimse_menu.ps1 -Action runtime-watch -RuntimeWatchId playtest -IssueDescription "popup says file was not configured properly"
.\vortex_skyrimse_menu.ps1 -Action config -ConfigPath "C:\path\to\config\popup.json"
.\vortex_skyrimse_menu.ps1 -Action xedit-script -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed" -FormId "0100ABCD"
.\vortex_skyrimse_menu.ps1 -Action xedit-result -XeditReportPath "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\xedit-inspection-YYYYMMDD-HHMMSS.csv"
.\vortex_skyrimse_menu.ps1 -Action issue-case -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed" -FormId "0100ABCD"
.\vortex_skyrimse_menu.ps1 -Action issue-case-status -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action case-note -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS" -CaseNote "Tested in cloned profile; issue still appears."
.\vortex_skyrimse_menu.ps1 -Action safe-experiment -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action what-now -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action live-bridge -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action case-evidence -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS" -EvidenceKind popup_ocr -OcrText "file was not configured properly"
.\vortex_skyrimse_menu.ps1 -Action case-bundle -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action case-inbox -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action safe-profile-fix -SafeProfileName "OpenClaw Fixed Test" -DisableModIds "exact-vortex-mod-id"
.\vortex_skyrimse_menu.ps1 -Action deployment-doctor
.\vortex_skyrimse_menu.ps1 -Action deployment-doctor -DeploymentBaselinePath "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor-before.json"
.\vortex_skyrimse_menu.ps1 -Action launch-doctor
.\vortex_skyrimse_menu.ps1 -Action automation-plan -Problem "disable unwanted mods and sort safely"
.\vortex_skyrimse_menu.ps1 -Action skse-doctor
.\vortex_skyrimse_menu.ps1 -Action report-viewer
.\vortex_skyrimse_menu.ps1 -Action evidence-report -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
.\vortex_skyrimse_menu.ps1 -Action known-rules
.\vortex_skyrimse_menu.ps1 -Action mo2-diagnostics
```

Action 30 imports helper output from `<case folder>\incoming` by default. Use
`-InboxDir` only when the helper writes somewhere else.

Action 31 previews cloning the selected/active profile and applying exact mod-id
enable/disable fixes to the clone only. Add `-ApplyProfileFix` after reviewing
the preview and closing Vortex.

Action 32 is the fastest "are my Vortex mods reaching Skyrim?" verdict. It is
read-only and checks the selected profile against Skyrim `Data`, `plugins.txt`,
sampled deployed files, SKSE, audio archives, and missing masters.
Pass `-DeploymentBaselinePath` after deploying in Vortex to compare the new run
against an older Deployment Doctor JSON report.

Action 33 is the fastest "how should I launch Skyrim?" verdict. It is read-only
and checks SkyrimSE.exe, SKSE files, active profile state, and Deployment Doctor
state before recommending SKSE, Steam/vanilla, or a fix-first route.

Action 34 is the safety gate for risky automation requests. It writes a plan
only: backup first, clone profile first, apply exact mod-id changes to the clone
only, keep Vortex-owned actions in Vortex, then verify with Deployment Doctor.

Action 35 checks whether the detected Skyrim runtime matches the installed SKSE
runtime DLL target, SKSE scripts, and Address Library evidence.

Action 36 writes `report-viewer.html` in the reports folder. It is a static
read-only page that indexes generated JSON, Markdown, CSV, log, script, and zip
reports so you and OpenClaw can find the newest evidence faster.

Action 37 writes `live-evidence-summary.md` in an issue case folder. It reads
imported popup OCR, console FormIDs, cells, objects, and screenshot notes, then
lists the suggested next diagnostic calls without changing mods or profiles.

Action 38 runs common Skyrim SE known-rule checks such as FNIS + Pandora and
FSMPM without JContainers.

Action 39 runs read-only Mod Organizer 2 diagnostics. For MO2, launch SKSE,
Skyrim, and xEdit from MO2's Run dropdown so the selected profile's virtual
files are visible.

Action 40 watches runtime logs by cursor. Run it once with
`-ResetRuntimeWatch`, reproduce the issue in Skyrim, then run it again with the
same `-RuntimeWatchId` to read only newly appended Papyrus/SKSE/crash evidence.

If Windows cannot find Python, pass the executable once:

```powershell
.\vortex_skyrimse_menu.ps1 -Action validate -PythonCommand "C:\Path\To\python.exe"
```

You can also set `VORTEX_SKYRIMSE_MCP_PYTHON` to the same executable path.

Custom paths:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge -StagingDir "D:\Vortex Mods\skyrimse\mods" -SkyrimDir "C:\SteamLibrary\steamapps\common\Skyrim Special Edition"
```

Stronger duplicate evidence:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge -HashFiles
```

If Vortex profile state is slow or locked:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge -NoProfileState
```

Optional Nexus metadata:

```powershell
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeNexusMetadata -NexusApiKeyFile "$env:USERPROFILE\.vortex-skyrimse-mcp\nexus-api-key.txt"
```

The menu passes the key file path to the MCP. It does not copy Vortex's key.

Optional xEdit and collection context:

```powershell
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeXeditReport -FormId "0100ABCD"
.\vortex_skyrimse_menu.ps1 -Action diagnostics -IncludeCollectionReport
.\vortex_skyrimse_menu.ps1 -Action xedit -XeditExe "C:\Tools\SSEEdit\SSEEdit.exe" -FormId "0100ABCD"
.\vortex_skyrimse_menu.ps1 -Action xedit-script -XeditExe "C:\Tools\SSEEdit\SSEEdit.exe" -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed"
```

The `xedit-script` action writes a `.pas` script and tells you the CSV path it
will produce after you run it inside SSEEdit/xEdit with Apply Script. The
`xedit-result` action reads that CSV and summarizes likely plugin/record
candidates for OpenClaw.

The `issue-case` action creates one folder with `issue-case.md`,
`issue-case.json`, and an xEdit inspection script when enough clues are
available. Open the Markdown file first.

The `issue-case-status` action reads that folder later. If the generated xEdit
CSV exists, it writes `issue-case-status.md` and summarizes the strongest
plugin/record evidence.

Actions 24-27 keep the case tidy: notes append to `case-notes.md`, the safe
experiment plan writes a dry-run cloned-profile test plan, `what-now` writes one
short recommendation, and live bridge status explains what screenshot/OCR or
SKSE telemetry would need.

Actions 28-30 are for handoff. Evidence import appends popup OCR, console
FormIDs, cell names, and future helper output to `live-evidence.md/jsonl`.
Action 37 summarizes that evidence so OpenClaw can use the latest captured
popup/FormID instead of asking you to type it again.
Case inbox imports helper files from `incoming`, and bundle zips the case folder
for review; inspect the zip before posting it.

Action 31 is for safe profile experiments. It previews by default; with
`-ApplyProfileFix`, it creates a cloned Vortex profile and applies exact mod-id
enable/disable fixes to the clone only.

## Safety

The menu runs read-only report actions plus profile backup, restore preview, and cloned-profile fix previews. It does not delete mods, sort load order, write INI fixes, edit plugins, install collections, or apply restore plans. Action 31 writes only when `-ApplyProfileFix` is passed, and it changes the cloned profile only. Action 32 is read-only.

The safe session and diagnostics actions write Markdown and JSON reports and try to include a profile backup unless `-NoProfileBackup` is passed. They include Skyrim runtime log scanning by default unless `-NoRuntimeLogs` is passed. The backup action writes a JSON backup file. The restore action previews what would be restored; it does not change Vortex. The in-game issue action searches for likely mod candidates; it does not fix records automatically. The runtime log action is read-only and points OpenClaw at config candidates when logs reference them. The config validator is read-only and checks parse/health clues before any patch. The xEdit inspection and issue-case actions generate/read evidence only; do not save plugin edits from xEdit unless you intentionally made separate manual changes.
