# Changelog

## v0.2.36

- Adds WSL2 path bridging so OpenClaw running in WSL can resolve Windows Steam, Vortex, Skyrim SE, AppData, Documents/My Games, and Steam library paths through `/mnt/<drive>`.
- Adds `wsl_bridge_report` and `--wsl-bridge` to explain Windows profile mapping, interop availability, detected paths, and OpenClaw config hints.
- Adds `install_wsl.sh`, `openclaw.mcp.wsl.example.json`, and `docs/WSL-OPENCLAW.md` for no-guesswork OpenClaw-in-WSL setup.
- Updates detection, redaction, cache/log defaults, Vortex process checks, docs, and smoke coverage for WSL-aware behavior.

## v0.2.35

- Adds `skyrim_case_evidence_report`, a read-only summary for append-only case evidence such as popup OCR, console FormIDs, cells, objects, and screenshot notes.
- Wires live/case evidence summaries into `skyrim_issue_case_status` and `skyrim_case_what_now`, so OpenClaw can use captured popup/FormID evidence without asking the user to retype it.
- Adds `--case-evidence-report` direct CLI shortcut and local menu action 37.
- Adds regression coverage for evidence summary generation, latest popup/FormID extraction, and case-status integration.

## v0.2.34

- Adds `report_viewer_index`, a read-only static HTML index for generated JSON, Markdown, CSV, log, script, and zip report files.
- Adds `--report-viewer` direct CLI shortcut and local menu action 36.
- Documents the report viewer workflow for users and OpenClaw agents.
- Adds smoke, fixture, and PowerShell menu coverage for viewer generation and discovery.

## v0.2.33

- Adds `skse_runtime_doctor_report`, a read-only compatibility check for Skyrim runtime version, SKSE runtime DLL target, SKSE scripts, and Address Library evidence.
- Adds `--skse-doctor` direct CLI shortcut and local menu action 35.
- Relaxes Launch Doctor's SKSE check so `skse64_steam_loader.dll` is treated as evidence, not a hard requirement for newer SKSE builds.
- Adds regression coverage for SKSE runtime mismatch and matching 1.5.97 / SKSE 2.0.20 evidence.

## v0.2.32

- Adds `vortex_reversible_automation_plan`, a read-only safety gate for risky automation requests such as delete/uninstall, sort, conflict rules, deploy/purge, updates, plugin edits, and cloned-profile mod toggles.
- Adds `--automation-plan` direct CLI shortcut and local menu action 34.
- Documents which actions can be tested through cloned profiles and which must remain Vortex/xEdit-owned, with revert steps.
- Updates workflow routing so OpenClaw can answer "automate this but make it reversible" without applying changes.

## v0.2.31

- Adds `skyrim_launch_doctor_report`, a read-only launch-route verdict for SKSE vs Steam/vanilla vs fix deployment/SKSE first.
- Adds `--launch-doctor` direct CLI shortcut and local menu action 33.
- Writes optional Launch Doctor Markdown reports through `output_path`.
- Updates workflow routing and docs so OpenClaw can answer "how should I launch Skyrim?" without changing anything.

## v0.2.30

- Adds optional Deployment Doctor Markdown output through `output_path` / `--output-path`.
- Adds `baseline_path` / `--baseline-path` comparison for before/after deploy checks, including changed, improved, and regressed checks.
- Updates the local menu Deployment Doctor action to write both Markdown and JSON reports, with optional baseline comparison.
- Adds regression coverage for Deployment Doctor Markdown and baseline comparison.

## v0.2.29

- Adds `deployment_doctor_report`, a read-only plain-English deployment verdict for Vortex profile, Skyrim `Data`, `plugins.txt`, SKSE files, audio archives, and missing plugin masters.
- Adds `--deployment-doctor` direct CLI shortcut and local helper menu action 32.
- Extends profile deployment checks with sampled deployable-file probes so pluginless, SKSE, archive, script, mesh, texture, interface, and config-only mods have better evidence.
- Updates the mods-not-working workflow to start with Deployment Doctor, with fixture/smoke/Menu coverage.

## v0.2.28

- Bounds the local scan cache with `scan_cache_max_entries` / `--scan-cache-max-entries`, pruning oldest entries during dirty writes.
- Writes the internal scan cache as compact JSON to reduce disk size and parse time on large repeated diagnostics.
- Expands `scan_cache_status` with cache size, schema/update/prune fields, and max-entry/prunable-entry counts.
- Adds regression coverage for cache pruning, compact writes, and client-visible cache options.

## v0.2.27

- Avoids rewriting the local scan cache on pure cache-hit runs, reducing disk churn on repeated large-collection diagnostics.
- Optimizes `vortex_safe_profile_fix` and `vortex_set_profile_mods` to avoid loading Vortex's full installed-mod metadata by default.
- Adds regression coverage for scan-cache dirty writes and clone-only profile fix metadata behavior.

## v0.2.26

- Adds `vortex_safe_profile_fix`, a high-level dry-run-first tool that clones the selected Vortex profile and applies exact mod enable/disable fixes to the clone only.
- Adds CLI shortcut `--safe-profile-fix` with repeated `--disable-mod-id` / `--enable-mod-id` arguments.
- Adds local menu action 31 for cloned-profile fix previews and optional apply after Vortex is closed.
- Updates safe experiment planning to point at the one-step cloned-profile fix tool.

## v0.2.25

- Adds `skyrim_case_inbox_import` for importing helper-generated JSON/TXT/LOG evidence from a case `incoming` folder.
- De-dupes inbox files by SHA-256 in `live-evidence-index.json`, so OpenClaw or helper scripts can rerun imports safely.
- Adds direct CLI shortcut `--case-inbox`, local menu action 30, tests, and docs for the case inbox workflow.

## v0.2.24

- Adds `skyrim_case_evidence_import` for append-only popup OCR, console FormID, current-cell, screenshot-note, and future live-bridge evidence intake.
- Adds `skyrim_case_bundle` to zip a case folder for OpenClaw review or bug reports with a privacy warning.
- Adds direct CLI shortcuts and local menu actions 28-29 for evidence import and case bundling.
- Extends tests and docs for the live-evidence handoff workflow.

## v0.2.23

- Adds `skyrim_issue_case_note` for append-only case notes and decision/test logs.
- Adds `skyrim_safe_experiment_plan` for dry-run cloned-profile experiment planning before disabling candidate mods.
- Adds `skyrim_case_what_now` for one concise next-action recommendation from a case folder.
- Adds `skyrim_live_bridge_status`, a read-only capability/design surface for future screenshot/OCR, console FormID, and SKSE telemetry bridges.
- Improves `xedit_inspection_result_report` with record-type interpretation, issue-kind summaries, and per-row guidance.
- Adds local menu actions 24-27 plus CLI shortcuts for notes, experiment plans, what-now summaries, and live bridge status.

## v0.2.22

- Adds `skyrim_issue_case_status`, a no-change case-folder updater that detects the generated xEdit CSV, parses it, and writes `issue-case-status.md`/`.json`.
- Adds `--issue-case-status` direct CLI mode and local menu action 23.
- Adds tests and docs for the case-packet follow-up loop after running the generated SSEEdit/xEdit script.

## v0.2.21

- Adds `skyrim_issue_case_packet`, a no-change investigation folder generator that combines issue triage, xEdit/SSEEdit target hints, a generated read-only xEdit script, and OpenClaw next steps.
- Adds `--issue-case` direct CLI mode and local menu action 22 for one-command case packet creation.
- Adds fixture, smoke, and PowerShell menu coverage for the case-packet workflow.

## v0.2.20

- Adds `xedit_inspection_script`, a read-only xEdit/SSEEdit Pascal script generator that exports matching selected records to CSV for OpenClaw.
- Adds `xedit_inspection_result_report` to summarize generated xEdit CSV output by plugin, record signature, matched term, and preview rows.
- Expands xEdit diagnostics and workflow guidance from FormID/plugin hints into a safer read-only inspection loop before cloned-profile testing.
- Adds local menu actions for generating xEdit inspection scripts and summarizing the CSV result.
- Lets the local menu use `-PythonCommand` or `VORTEX_SKYRIMSE_MCP_PYTHON` when Windows does not expose `py`/`python` on PATH.
- Adds fixture and smoke coverage for xEdit script generation, static safety checks, and CSV parsing.

## v0.2.19

- Adds `tests/config_runtime_mcp.py`, a focused regression suite for config parsing, root restrictions, exact-text patch suggestions, repeated replacement safety, runtime log issue grouping, config candidate validation, and stale/fresh log handling.
- Adds `tests/run_all.py` as the no-hassle local test runner for compile, self-test, MCP smoke, fixture integration, config/runtime regression, and PowerShell helper checks when PowerShell is available.
- Updates CI to run the shared Python test runner so local and GitHub validation follow the same path.
- Lets `mcp_doctor.ps1` use `-PythonCommand` or `VORTEX_SKYRIMSE_MCP_PYTHON` for environments where `py`/`python` is not on `PATH`.
- Adds testing documentation for humans and OpenClaw agents.

## v0.2.18

- Adds `config_file_report`, a read-only config validator for JSON, XML, INI, loose key/value configs, TOML, YAML/plain text summaries, parse errors, and likely unconfigured placeholder values.
- Adds exact-text patch suggestions for obvious `configured=false` style settings, still requiring `apply_config_text_patch` dry-run/approval before anything writes.
- Adds runtime log issue grouping so repeated Papyrus/SKSE/crash spam is summarized into root-cause patterns before OpenClaw reads individual lines.
- Adds runtime log freshness warnings so stale logs are not mistaken for the current reproduced popup.
- Validates runtime log `configCandidates` automatically and surfaces config health findings in safe-session/diagnostics reports.
- Adds local menu action 19 for config file validation and expands tests/docs for the new workflow.

## v0.2.17

- Adds `skyrim_runtime_log_report` for recent Papyrus/SKSE/crash log scanning, high-signal error detection, and staged-file matching.
- Adds config/error candidate detection for popup messages such as "file was not configured properly".
- Adds `apply_config_text_patch`, an exact-text config patch tool that is dry-run by default, root-restricted, and backed up when writing.
- Wires Skyrim runtime logs into safe-session reports, Skyrim diagnostics, bug bundles, the workflow guide, direct CLI, and local menu action 18.
- Documents the runtime-log and safe config-patch workflow for OpenClaw and no-OpenClaw users.
- Extends smoke, fixture, and PowerShell menu tests for runtime logs and config patching.

## v0.2.16

- Adds `workflow_guide`, a read-only routing helper that turns a plain-language Skyrim/Vortex problem into a safe recommended MCP tool sequence.
- Adds `--workflow-guide`, `--problem`, `--workflow-key`, and local menu action 17 for workflow recommendations without memorizing tool names.
- Documents the workflow recommender in the README, Start Here, CLI, local menu, OpenClaw guide, and workflow examples.
- Extends smoke, fixture, and PowerShell menu tests for the new workflow guide.

## v0.2.15

- Adds a local mod-summary scan cache for faster repeated diagnostics on large collections, with `scan_cache_status`, CLI/menu flags, and safe fallback if the cache cannot be written.
- Adds read-only `xedit_diagnostics_report` for SSEEdit/xEdit target hints from FormIDs and plugin names.
- Adds read-only `vortex_collection_report` and `collection_local_match_report` for Vortex collection-state context and manifest-to-local Nexus metadata matching.
- Adds conflict risk explanations so OpenClaw can explain high-risk script/SKSE/plugin/archive conflicts differently from harmless duplicates.
- Wires xEdit, collection, and scan-cache options into safe-session, Skyrim diagnostics, bug bundles, direct CLI, and the local helper menu.
- Adds documentation for scan cache behavior, xEdit diagnostics, collection diagnostics, and conflict interpretation.
- Extends smoke and fixture tests for the new tools, cache behavior, collection matching, xEdit hints, and conflict explanations.

## v0.2.14

- Adds optional read-only Nexus Mods API metadata support with explicit MCP-owned key handling via `NEXUS_MODS_API_KEY`, `nexus_api_key_file`, or private tool arguments.
- Adds Nexus tools: `nexus_validate_key`, `nexus_mod_lookup`, `nexus_mod_files`, `nexus_file_info`, `nexus_file_by_md5`, `nexus_parse_nxm_link`, and `nexus_update_report`.
- Adds `skyrim_diagnostics_report`, a broad no-change report for setup, deployment, profile state, SKSE/audio/INI health, logs, in-game issue triage, and optional Nexus metadata.
- Enriches safe-session, play, bug-bundle, and mod-knowledge reports with optional Nexus source/update metadata while keeping Vortex responsible for downloads, installs, collections, and deployment.
- Redacts Nexus API keys and token-like fields from compact logs and documents why the MCP must not copy Vortex's key.
- Adds local menu and direct CLI support for Skyrim diagnostics, Nexus metadata options, and lookup limits.
- Adds industry-standard support, security, contributing, diagnostics, Nexus API, and ADR documentation.
- Extends fixture and smoke tests for Nexus metadata tools, redaction, and new MCP tool registration.

## v0.2.13

- Adds `performance_mode` for slower OpenClaw models: `slow_model`, `fast`, `normal`, and `thorough`.
- Adds `response_mode=compact` for smaller in-game issue candidates and trimmed safe-session/bug-bundle sections.
- Wires performance options into MCP tool schemas and direct CLI flags.
- Documents slow-model usage so agents start with summaries and only deepen scans when needed.
- Adds fixture coverage for compact issue output, slow-model safe sessions, and CLI performance flags.

## v0.2.12

- Makes the default in-game issue scan more comprehensive with a new balanced first pass.
- Balanced scans now inspect mod names, plugin names, readmes, plugin strings, important file paths, and a small number of relevant config/text files before asking for a slower deep scan.
- Adds scan-mode output, diagnostic-quality output, next-best-input hints, and timeout/partial-scan reporting so OpenClaw can explain what happened instead of guessing.
- Lets `safe_session_report` and bug bundles run in-game popup triage when `issue_kind=popup` is provided even without a typed popup message.

## v0.2.11

- Improves popup triage so natural language like "annoying popup after loading a save" automatically uses popup mode without requiring exact popup text.
- Adds popup synonym handling for pop-up, dialog, warning, alert, prompt, notification, MCM, overlay, widget, and similar wording.
- Ranks UI/interface, script, SKSE, config, FOMOD, and MCM-style evidence for popup candidates even when screenshots/OCR/exact text are not provided.
- Updates OpenClaw and CLI docs so exact popup text is optional second-pass evidence, not a first-pass requirement.

## v0.2.10

- Adds `safe_session_report`, a no-change Markdown/JSON first-response report that combines setup validation, optional Vortex profile backup, modded play health, optional in-game issue triage, and log status.
- Adds `--safe-session` CLI shortcut and a local helper menu action for users who want one safe report without choosing several tools manually.
- Documents the safe-session flow for OpenClaw agents and no-MCP users.
- Adds fixture and smoke coverage for the safe-session MCP tool and CLI shortcut.

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
