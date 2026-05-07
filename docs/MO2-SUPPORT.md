# Mod Organizer 2 Support

This MCP now supports read-only diagnostics for Mod Organizer 2 profiles.

MO2 works differently from Vortex. Vortex deploys files into Skyrim `Data`.
MO2 keeps mods isolated and uses `usvfs` to create a virtual `Data` folder only
for programs launched through MO2. That means a healthy MO2 setup can look
"undeployed" if you only inspect the real Skyrim `Data` folder.

## What The MCP Can Do

- Detect a global or portable MO2 instance.
- Read `ModOrganizer.ini` path settings when they exist.
- Read the selected profile's `modlist.txt`, `plugins.txt`, `loadorder.txt`,
  and `archives.txt`.
- Inventory MO2 mod folders and mark each mod as enabled, disabled, or not in
  the selected profile.
- Evaluate known mod-stack rules against enabled MO2 profile mods only.
- Build a virtual plugin view from Skyrim `Data` plus enabled MO2 mod folders.
- Report enabled plugins that are missing from the virtual view.
- Parse plugin headers and report missing masters.
- Approximate loose-file conflicts for the selected profile.
- Run a one-shot `mo2_modded_play_report` combining profile, plugin, SKSE, and
  known-rule checks.
- Work from OpenClaw inside WSL2 when Windows drives are mounted under `/mnt/c`.

## What It Does Not Do

- It does not edit `modlist.txt`, `plugins.txt`, or `loadorder.txt`.
- It does not launch MO2, Skyrim, SKSE, or xEdit.
- It does not sort plugins or change MO2 priorities.
- It does not inspect MO2's live `usvfs` process state.
- It does not replace MO2's own Conflicts tab, Plugin list, or executable
  configuration.

## The Important Rule

For MO2, launch Skyrim and tools through MO2.

Use MO2's executable dropdown and Run button for:

- `skse64_loader.exe`
- `SkyrimSE.exe`
- `SSEEdit.exe` / `xEdit.exe`
- BodySlide, Nemesis, Pandora, FNIS, and other tools that must see virtual mods

If you launch `SkyrimSE.exe` directly from Steam or Explorer, MO2 profile mods
will usually not appear in game.

## First OpenClaw Prompt

```text
Use workflow_guide for this problem: MO2 Skyrim mods are not working. Then run mo2_modded_play_report. Tell me whether the selected MO2 profile, enabled mods, plugins, missing masters, and SKSE route look ready. Do not apply changes.
```

If OpenClaw needs exact paths:

```text
Use mo2_modded_play_report with mo2_instance_dir "C:\Users\<you>\AppData\Local\ModOrganizer\Skyrim Special Edition" and mo2_profile "Default". Do not apply changes.
```

For WSL2:

```text
Use mo2_modded_play_report with mo2_instance_dir "/mnt/c/Users/<you>/AppData/Local/ModOrganizer/Skyrim Special Edition" and mo2_profile "Default". Do not apply changes.
```

## Direct CLI

From PowerShell:

```powershell
py -3 .\server.py --mo2-diagnostics
```

With explicit paths:

```powershell
py -3 .\server.py --mo2-diagnostics `
  --mo2-instance-dir "C:\Users\<you>\AppData\Local\ModOrganizer\Skyrim Special Edition" `
  --mo2-profile "Default" `
  --skyrim-dir "C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition"
```

Inventory only:

```powershell
py -3 .\server.py --tool mo2_inventory_mods --mo2-instance-dir "C:\path\to\MO2 instance"
```

Plugin and missing-master check:

```powershell
py -3 .\server.py --tool mo2_plugin_report --mo2-instance-dir "C:\path\to\MO2 instance"
```

Loose-file conflict approximation:

```powershell
py -3 .\server.py --tool mo2_file_conflict_report --mo2-instance-dir "C:\path\to\MO2 instance"
```

Local menu:

```powershell
.\vortex_skyrimse_menu.ps1 -Action mo2-diagnostics
```

## Path Overrides

The MCP tries to auto-detect common locations first. Use overrides when a
portable setup or custom base folder is not found.

- `mo2_instance_dir`: folder containing `ModOrganizer.ini`, or portable MO2's
  base folder.
- `mo2_profile`: profile folder name under `profiles`.
- `mo2_mods_dir`: custom `mods` folder.
- `mo2_profiles_dir`: custom `profiles` folder.
- `mo2_overwrite_dir`: custom `overwrite` folder.
- `mo2_exe`: path to `ModOrganizer.exe`.
- `skyrim_dir`: folder containing `SkyrimSE.exe`.

Environment variables are also supported:

- `VORTEX_SKYRIMSE_MCP_MO2_INSTANCE_DIR`
- `VORTEX_SKYRIMSE_MCP_MO2_PROFILE`
- `VORTEX_SKYRIMSE_MCP_MO2_MODS_DIR`
- `VORTEX_SKYRIMSE_MCP_MO2_PROFILES_DIR`
- `VORTEX_SKYRIMSE_MCP_MO2_OVERWRITE_DIR`
- `VORTEX_SKYRIMSE_MCP_MO2_EXE`

## How The Reports Think

`mo2_profile_report` reads the selected profile files:

```text
profiles\<profile>\modlist.txt
profiles\<profile>\plugins.txt
profiles\<profile>\loadorder.txt
profiles\<profile>\archives.txt
```

`modlist.txt` decides which mod folders are enabled for that profile. Lines
starting with `+` are enabled, `-` are disabled, and `*` are unmanaged entries
such as official DLC.

`mo2_plugin_report` then builds an expected virtual plugin list:

```text
Skyrim Data
  + enabled MO2 mod folders from modlist.txt
  -> top-level .esm/.esp/.esl files
  -> plugin header master checks
```

`mo2_file_conflict_report` scans enabled mod folders and groups duplicate
relative paths. It includes an apparent winner based on the selected profile
order, but MO2's own Conflicts tab remains the authority.

## OpenClaw Safety Rules

- Do not use Vortex Deployment Doctor for MO2 deployment questions.
- Do not tell the user to copy MO2 files into Skyrim `Data`.
- Do not judge MO2 success by "is the mod file in Data?"
- Use `mo2_modded_play_report` for MO2 first-pass health.
- Use `skse_runtime_doctor_report` for SKSE/runtime mismatch.
- Launch xEdit through MO2 before using generated xEdit scripts on MO2 profiles.
- Make reversible tests by copying or cloning the MO2 profile in MO2, then
  changing only that copied profile.

## Sources

- MO2 instance model and global/portable instance layout: <https://github.com/ModOrganizer2/modorganizer/wiki/Instances>
- MO2 path settings and `%BASE_DIR%`: <https://github.com/ModOrganizer2/modorganizer/wiki/settings-window>
- MO2 executables and why tools must be launched through MO2: <https://github.com/ModOrganizer2/modorganizer/wiki/Executables-window>
- MO2 conflict priority behavior: <https://github.com/ModOrganizer2/modorganizer/wiki/Mod-information-window>
