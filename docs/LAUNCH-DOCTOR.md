# Launch Doctor

`skyrim_launch_doctor_report` is the quickest answer to:

> Should I launch Skyrim SE through SKSE, Steam/vanilla, or stop and fix
> deployment/SKSE first?

It is read-only. It does not launch Steam, Skyrim, SKSE, Vortex, or xEdit.

## What It Checks

- `SkyrimSE.exe` exists in the detected game folder.
- Skyrim `Data` exists.
- SKSE launch pieces are present:
  - `skse64_loader.exe`
  - `skse64_steam_loader.dll`
  - one SKSE runtime DLL such as `skse64_1_5_97.dll`
  - SKSE scripts under `Data\Scripts`
- The selected Vortex profile is readable and active.
- Deployment Doctor says the selected profile is linked to Skyrim `Data` and
  `plugins.txt`.
- Enabled profile mods show SKSE plugin evidence.

## Direct CLI

```powershell
py -3 .\server.py --launch-doctor
```

Write a readable Markdown report:

```powershell
py -3 .\server.py --launch-doctor --output-path ".\launch-doctor.md" --output-json ".\launch-doctor.json"
```

If detection picked the wrong paths:

```powershell
py -3 .\server.py --launch-doctor --skyrim-dir "C:\SteamLibrary\steamapps\common\Skyrim Special Edition" --staging-dir "D:\Vortex Mods\skyrimse\mods"
```

## Local Menu

```powershell
.\vortex_skyrimse_menu.ps1 -Action launch-doctor
```

This writes both Markdown and JSON under the reports folder.

## OpenClaw Prompt

```text
Use skyrim_launch_doctor_report. Tell me whether I should launch through SKSE, Steam/vanilla, or fix deployment/SKSE first. Do not launch or change anything.
```

## How To Read It

- `summary.launchState=ready`: use the recommended route.
- `summary.recommendedLaunchRoute=skse`: launch through `skse64_loader.exe`,
  preferably from the Vortex Dashboard SKSE tool if that is your normal route.
- `summary.recommendedLaunchRoute=steam_or_vanilla`: only use Steam/vanilla if
  the profile truly does not require SKSE.
- `summary.recommendedLaunchRoute=fix_setup_first`: Skyrim/Vortex path detection
  is not good enough yet. Pass explicit paths or run setup validation first.
- `summary.recommendedLaunchRoute=fix_deployment_first`: Vortex has not linked
  the selected profile to Skyrim yet. Deploy in Vortex first.
- `summary.recommendedLaunchRoute=fix_skse_first`: SKSE is required or expected
  but the local SKSE files are incomplete.

## Important Limit

Launch Doctor checks installed SKSE file evidence. Exact SKSE-to-Skyrim runtime
compatibility still depends on the installed Skyrim runtime and SKSE package
version, so keep the SKSE archive/package name around when possible.
