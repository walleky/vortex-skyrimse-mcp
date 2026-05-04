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
```

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
```

## Safety

The menu runs read-only report actions plus profile backup and restore preview. It does not delete mods, sort load order, write INI fixes, edit plugins, install collections, or apply restore plans.

The safe session and diagnostics actions write Markdown and JSON reports and try to include a profile backup unless `-NoProfileBackup` is passed. They include Skyrim runtime log scanning by default unless `-NoRuntimeLogs` is passed. The backup action writes a JSON backup file. The restore action previews what would be restored; it does not change Vortex. The in-game issue action searches for likely mod candidates; it does not fix records automatically. The runtime log action is read-only and points OpenClaw at config candidates when logs reference them.
