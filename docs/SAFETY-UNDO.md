# Safety And Undo

This project should feel boring in the best way: check the setup, make a backup, preview changes, apply only when approved, and keep a clean path back.

## First Step

Ask OpenClaw to run:

```text
skyrim_diagnostics_report
```

This writes a no-change Markdown/JSON baseline, tries to include a profile
backup if Vortex CLI is available, and can include optional Nexus metadata. If
you only want setup blockers, ask for:

```text
validate_setup
```

`validate_setup` returns detected paths, blockers, tool groups, and the safety defaults. If it says `ready=false`, fix the blockers before asking OpenClaw to change profile state.

## Profile Backups

Before testing a big collection change, create a Vortex profile backup:

```text
vortex_profile_backup with include_all_profiles=true
```

Direct CLI:

```powershell
py -3 .\server.py --tool vortex_profile_backup --include-all-profiles --backup-path .\profile-backup.json
```

Local menu:

```powershell
.\vortex_skyrimse_menu.ps1
```

Then choose `Create Vortex profile backup`.

Backups are JSON files. They contain profile fields, mod enable/disable state, and optionally Vortex mod metadata. They do not contain mod archives.

## Automatic Backups

These tools write a backup automatically before `apply=true` unless `backup_before_apply=false`:

- `vortex_clone_profile`
- `vortex_set_profile_mods`
- `vortex_safe_profile_fix`

The result includes `backupPath`. Keep that path if you need to undo the change.

## Restore Preview

Restores are previews by default:

```text
vortex_profile_restore_plan with backup_path="C:\path\profile-backup.json" and apply=false
```

Direct CLI:

```powershell
py -3 .\server.py --tool vortex_profile_restore_plan --backup-path .\profile-backup.json
```

Local menu:

```powershell
.\vortex_skyrimse_menu.ps1
```

Then choose `Preview restore from backup`.

The restore preview shows exact Vortex state paths and values that would be written. It does not change Vortex.

## Applying A Restore

Only apply after reading the preview:

```text
vortex_profile_restore_plan with backup_path="C:\path\profile-backup.json" and apply=true
```

Rules:

- Close Vortex first.
- Keep `disable_extra_mods=false` unless you specifically want enabled mods that were not in the backup to be disabled.
- Reopen Vortex afterward.
- Select the intended profile.
- Click Deploy Mods.
- Launch Skyrim through the usual SKSE path for the profile.

## What Restore Does Not Do

The restore tool is intentionally conservative.

It restores backed-up profile fields and backed-up `modState` records. If a mod exists now but was not in the backup, it is left alone unless `disable_extra_mods=true`.

It does not:

- delete installed mods
- delete downloaded archives
- delete extra Vortex profiles that were created after the backup
- sort plugins
- write Vortex conflict rules
- edit Vortex database files directly

## OpenClaw Rule

For any profile-changing request, OpenClaw should use this order:

1. `validate_setup`
2. `vortex_profile_report`
3. `vortex_profile_backup`
4. `vortex_safe_profile_fix apply=false` for clone-only mod-id fixes, or another dry-run plan for the requested change
5. user approval
6. apply with Vortex closed
7. reopen Vortex, select the cloned/intended profile, deploy mods
8. `deployment_doctor_report`

If anything fails, run `bug_report_bundle` with `zip_output=true` and `redact_user_paths=true`.
