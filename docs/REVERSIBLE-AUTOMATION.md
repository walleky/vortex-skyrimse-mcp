# Reversible Automation

`vortex_reversible_automation_plan` is the safety gate for scary requests like:

- disable unwanted mods
- delete or uninstall mods
- sort load order
- write Vortex conflict rules
- deploy or purge
- update/install collection mods
- edit plugin records in xEdit
- patch config files

It is read-only. It does not deploy, purge, sort, uninstall, delete, update,
install, write conflict rules, edit plugins, or change Vortex profiles.

## Why This Exists

Vortex profiles are still the right way to test mod configurations safely. The
safe loop is:

1. Make a profile backup.
2. Clone the current profile.
3. Apply exact enable/disable tests to the clone only.
4. Deploy manually in Vortex.
5. Verify with Deployment Doctor.
6. Launch only after Launch Doctor says the route is safe.
7. If the test is worse, switch back to the original profile or restore from
   the profile backup.

## Direct CLI

```powershell
py -3 .\server.py --automation-plan --request "disable redundant mods and sort load order safely"
```

With exact mod ids:

```powershell
py -3 .\server.py --automation-plan --request "disable these in a cloned test profile" --disable-mod-id "exact-vortex-mod-id"
```

## Local Menu

```powershell
.\vortex_skyrimse_menu.ps1 -Action automation-plan -Problem "disable redundant mods safely"
```

## OpenClaw Prompt

```text
Use vortex_reversible_automation_plan with this request: disable unwanted mods, sort load order, and make it revertable. Explain which parts can be tested in a cloned profile and which parts must stay in Vortex/xEdit. Do not apply changes.
```

## What The MCP Will Automate

The MCP can plan and point to existing apply-capable tools for narrow, reversible
operations:

- `vortex_safe_profile_fix` for exact mod-id enable/disable tests in a cloned
  profile.
- `apply_config_text_patch` for exact text replacements after validation and a
  dry run.
- `apply_ini_fixes` for narrow Skyrim INI fixes after a dry run.

## What Must Stay In Vortex Or xEdit

Some actions are still planned but not executed by the MCP because direct state
or file edits are more likely to corrupt the setup:

- Vortex Deploy Mods and Purge Mods
- Vortex conflict rule writes
- load-order sorting
- Nexus downloads, installs, updates, collection changes, and uninstalls
- plugin record edits and placed-object deletion in xEdit

The MCP can still help by creating before/after reports, exact candidate lists,
and cloned-profile test plans.

## Source Notes

Vortex documents deployment as the step that links installed mod files into the
game folder, and purge as the reverse operation. Vortex profile docs describe
profiles as separate mod/settings/save contexts that can be cloned or enabled.
Vortex also documents `--set` and `--del` as advanced state operations where
improper use can break Vortex state. This is why the MCP treats direct Vortex
state writes as narrow, dry-run-first, backup-first operations.
