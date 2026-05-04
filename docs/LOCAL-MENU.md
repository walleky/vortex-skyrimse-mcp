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

## Safety

The menu runs read-only report actions plus profile backup and restore preview. It does not delete mods, sort load order, write INI fixes, edit plugins, or apply restore plans.

The backup action writes a JSON backup file. The restore action previews what would be restored; it does not change Vortex. The in-game issue action searches for likely mod candidates; it does not fix records automatically.
