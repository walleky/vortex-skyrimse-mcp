# Deployment Doctor

`deployment_doctor_report` is the quickest answer to:

```text
Are my enabled Vortex mods actually reaching Skyrim SE?
```

It is read-only. It does not deploy, sort, enable, disable, install, uninstall,
delete, edit plugins, or edit INI/config files.

## What It Checks

- Skyrim `Data` folder detection.
- Vortex Skyrim SE staging folder detection.
- Vortex CLI/profile detection.
- Enabled mods in the selected Vortex profile.
- ESP/ESM/ESL files from enabled profile mods present in Skyrim `Data`.
- Those plugins enabled in `%LOCALAPPDATA%\Skyrim Special Edition\plugins.txt`.
- Stale `plugins.txt` entries that do not match the selected profile.
- Sampled deployable files for pluginless mods, including BSA archives, SKSE DLLs,
  scripts, meshes, textures, interface files, and config files.
- Critical deployed files for enabled mods, with a separate pass for SKSE DLLs,
  Papyrus scripts, and behavior/animation HKX output so random sampling does not
  miss FNIS/Nemesis/Pandora-style output problems.
- Missing plugin masters.
- SKSE loader/runtime/script evidence.
- Base game voice/sound archive evidence.

## Direct CLI

```powershell
py -3 .\server.py --deployment-doctor
```

Write a readable Markdown report:

```powershell
py -3 .\server.py --deployment-doctor --output-path "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor.md" --output-json "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor.json"
```

If detection picks the wrong paths:

```powershell
py -3 .\server.py --deployment-doctor --skyrim-dir "C:\SteamLibrary\steamapps\common\Skyrim Special Edition" --staging-dir "D:\Vortex Mods\skyrimse\mods"
```

If Vortex has multiple Skyrim SE profiles:

```powershell
py -3 .\server.py --deployment-doctor --profile-id "exact-vortex-profile-id"
```

For a deeper critical-file pass:

```powershell
py -3 .\server.py --deployment-doctor --critical-deployment-probe-files-per-mod 50
```

## Before And After Deploy

Use this loop when Vortex looks confusing:

1. Run Deployment Doctor and keep the JSON result.
2. Open Vortex, select the intended Skyrim SE profile, and click Deploy Mods.
3. Rerun Deployment Doctor with the first JSON as `baseline_path`.

```powershell
py -3 .\server.py --deployment-doctor --baseline-path "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor-before.json" --output-path "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor-after.md" --output-json "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor-after.json"
```

The `baselineComparison` section reports changed checks, improved checks,
regressed checks, and count changes such as missing deployed plugins or missing
sampled files.

## Local Menu

```powershell
.\vortex_skyrimse_menu.ps1 -Action deployment-doctor
```

After deploying in Vortex, compare against the previous JSON:

```powershell
.\vortex_skyrimse_menu.ps1 -Action deployment-doctor -DeploymentBaselinePath "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\deployment-doctor-before.json"
```

## OpenClaw Prompt

```text
Use deployment_doctor_report. Tell me whether my selected Vortex profile is linked to Skyrim Data and plugins.txt. Do not apply changes.
```

## How To Read It

Read in this order:

1. `summary.deploymentState`
2. `summary.profileToSkyrimLinked`
3. `checks`
4. `findings`
5. `nextActions`

Common `deploymentState` values:

- `linked`: the selected profile looks deployed and enabled.
- `needs_deploy`: enabled profile content is missing from Skyrim `Data`.
- `plugins_disabled`: plugin files exist, but `plugins.txt` has them disabled.
- `profile_mismatch_or_stale_plugins`: `plugins.txt` appears to reflect another
  profile or an old deployment.
- `blocked_missing_masters`: plugin headers reference masters that are missing.
- `blocked`: path/profile evidence was too broken to prove deployment.
- `review`: no hard blocker, but one or more warnings need human review.

## Safe Next Step

If Deployment Doctor is not green, the safest human action is usually:

```text
Open Vortex -> select the intended Skyrim SE profile -> Deploy Mods -> confirm Plugins tab is enabled -> launch through SKSE.
```

Then rerun Deployment Doctor. It should become the clean baseline before you
start disabling mods or chasing deeper xEdit conflicts.

After Deployment Doctor is linked, run Launch Doctor if you are unsure whether
to start through SKSE or Steam/vanilla:

```powershell
py -3 .\server.py --launch-doctor
```
