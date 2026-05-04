# Changelog

## v0.2.9

- Tightens `in_game_issue_report` for large collections by avoiding the extra full file-path/text scan unless `deep_scan_files=true`.
- Keeps in-game issue output smaller by summarizing profile lookup state instead of returning the full internal mod path map.
- Adds optional `form_id`, `cell`, and `base_object` evidence fields plus a rough FormID load-order hint.
- Improves exact popup-text matching so a full popup phrase can be detected even when it appears inside a longer plugin string.

## v0.2.8

- Adds `in_game_issue_report`, a read-only triage tool for misplaced objects, location-specific weirdness, and annoying popups.
- The new tool searches staged mods for issue terms across mod names, plugin filenames, plugin strings, readmes, config files, file paths, and profile state when available.
- Adds direct CLI/menu support for in-game issue triage.
- Adds in-game diagnosis documentation, including how OpenClaw should use console FormIDs, exact popup text, cloned profiles, and future SKSE/screenshot bridge ideas.

## v0.2.7

- Adds `validate_setup`, a one-shot setup check for OpenClaw with blockers and safe tool groups.
- Adds `vortex_profile_backup` and `vortex_profile_restore_plan` for profile backups and dry-run restore previews.
- `vortex_clone_profile` and `vortex_set_profile_mods` now write a profile backup before `apply=true` by default.
- Updates the local helper menu with setup validation, profile backup, and restore preview actions.
- Adds safety/undo documentation and a Vortex MCP Bridge comparison document.
- Bug-report bundles now include setup validation results.

## v0.2.6

- Adds `vortex_skyrimse_menu.ps1`, a local helper menu for no-OpenClaw workflows.
- Adds `Vortex-SkyrimSE-Menu.cmd` as a double-click wrapper for the helper menu.
- Adds local menu documentation and PowerShell syntax checks in CI.
- The menu writes environment, mod knowledge, play diagnosis, bug bundle, and log reports into a reports folder.

## v0.2.5

- Adds direct CLI mode so tools can run without an MCP client.
- Adds `--mod-knowledge` as a no-OpenClaw shortcut for writing the Markdown collection knowledge report.
- Adds `make_mod_knowledge.ps1` and `Make-Mod-Knowledge.cmd` for no-hassle report generation from PowerShell or double-click.
- Adds CLI documentation and smoke/fixture coverage for direct tool calls.

## v0.2.4

- Adds `mod_knowledge_report`, a read-only Markdown report for huge Skyrim SE collections.
- The report infers each mod's likely role from staged files, plugins, FOMOD metadata, readme snippets, conflicts, duplicate evidence, and Vortex profile state when available.
- Adds a removal-review shortlist that favors cloned-profile disable tests over dangerous deletes.
- Adds documentation for how OpenClaw should use the mod knowledge report.
- Adds installer and MCP Doctor prompts for generating the collection knowledge report.

## v0.2.3

- Adds optional `zip_output` support to `bug_report_bundle` for one-file GitHub attachments.
- Adds default user-path redaction for support bundles, with `redact_user_paths=false` available for private debugging.
- Adds fixture-based tests for fake Skyrim/Vortex staging, plugin checks, conflicts, logs, redacted bundles, and zip output.
- Adds a sanitized sample bug bundle document.
- Updates quick-start, installer, Doctor, and agent docs to prefer zipped redacted bug reports.
- Updates CI to Node 24-compatible GitHub Actions and read-only repository permissions.
- `detect_environment` now accepts `local_appdata` for portable tests and custom setups.

## v0.2.2

- Adds central MCP file logging for server lifecycle, tool calls, Vortex CLI calls, and support bundle creation.
- Adds `log_status` for OpenClaw-readable log discovery.
- Adds `bug_report_bundle` for JSON bug reports with environment/play/deployment/plugin/INI checks plus recent log tails.
- Adds architecture, OpenClaw agent, logging, and bug-reporting docs.
- Adds a GitHub bug-report issue template.
- MCP Doctor now writes a transcript log to the MCP log folder.

## v0.2.1

- Adds MCP Doctor PowerShell and double-click CMD launchers.
- MCP Doctor runs self-tests, writes a ready-to-copy config snippet, prints an OpenClaw registration command, optionally registers through `openclaw mcp set`, and can open the OpenClaw config folder.
- CI now runs MCP Doctor in addition to server compile, self-test, and stdio smoke tests.

## v0.2.0

- Initial standalone GitHub release.
- Adds a dependency-free stdio MCP server for Windows Vortex + Skyrim SE diagnostics.
- Includes environment detection, mod inventory, conflict reports, redundant mod checks, plugin reports, INI checks, profile inspection, profile cloning, profile mod toggles, deployment checks, and one-shot modded play reports.
- Includes a PowerShell installer that prints a ready-to-copy MCP config snippet.
- Includes smoke tests for JSON-RPC initialization, tool listing, and basic environment detection.
