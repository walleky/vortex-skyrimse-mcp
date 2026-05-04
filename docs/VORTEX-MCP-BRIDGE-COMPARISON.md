# Vortex MCP Bridge Comparison

This is a practical comparison for OpenClaw and maintainers. It is based on the public Nexus Mods listing for "Claude.AI MCP Bridge" / "Vortex MCP Bridge" as of 2026-05-04:

- https://www.nexusmods.com/site/mods/1743
- https://www.nexusmods.com/site/mods/1743?tab=docs

No Vortex MCP Bridge code is copied here. This project only borrows product ideas from the public feature list.

## Short Answer

Vortex MCP Bridge is better for live Vortex control because it runs as a Vortex extension inside Vortex's Electron runtime.

This project is better for safe diagnosis, OpenClaw-readable reports, no-dependency Python setup, bug bundles, and conservative undoable profile experiments.

They are different tools:

- Bridge style: control Vortex directly from inside Vortex.
- This project: inspect and explain the local Skyrim SE setup from outside Vortex, then make narrow dry-run-first changes through Vortex's CLI.

## What Bridge Does Better

The public listing describes features that are naturally stronger inside Vortex:

- install Nexus mods through Vortex internals
- run Vortex deployment directly
- enable, disable, remove, and rename mods through Vortex APIs
- manage downloads
- set load order and mod rules
- query Nexus API for discovery, updates, changelogs, tracking, and endorsements
- switch active profiles through Vortex extension events

Those are powerful because the extension can use Vortex's internal services and live state.

## What This Project Does Better

This project is intentionally a safety-first sidecar:

- dependency-free Python server
- direct CLI mode when OpenClaw is not working
- setup validation through `validate_setup`
- large collection Markdown knowledge report
- bug-report zip with recent MCP/Vortex CLI logs
- profile deployment checks against Skyrim `Data` and `plugins.txt`
- SKSE/audio/INI/missing-master diagnosis in one `skyrim_modded_play_report`
- in-game issue triage for user-described misplaced objects and popups through `in_game_issue_report`
- dry-run profile changes
- automatic profile backups before profile writes
- restore previews through `vortex_profile_restore_plan`

For a frustrated user, this is less magical but easier to undo and easier to debug.

## Ideas Adopted Here

Useful Bridge ideas now mirrored in this project:

- `validate_setup`: one call that tells an agent what is ready and what is blocked.
- profile backup: export profile state before risky work.
- profile diff/compare: already present as `vortex_compare_profiles`.
- local no-hassle workflows: this project adds `Vortex-SkyrimSE-Menu.cmd` and direct CLI mode.

## Ideas Not Adopted Yet

These should not be implemented through guesses from outside Vortex:

- direct deployment
- automatic Nexus install/update
- automatic mod removal
- automatic load-order writes
- automatic Vortex conflict-rule writes

Those actions are best done by a Vortex extension or by the user in Vortex until there is a stable public CLI/API path. A wrong deploy, rule, or update can break a save or make the user think mods vanished.

## Best Combined Workflow

If the user has both tools:

1. Use this project for `validate_setup`, `skyrim_modded_play_report`, `mod_knowledge_report`, and bug bundles.
2. Use this project to make a profile backup.
3. Use Bridge for live Vortex actions like deploy/install/update if the user trusts it and Vortex is open.
4. Use this project again to verify deployment and plugin state after changes.

If the user wants the lowest-risk path, stay in this project and let Vortex itself handle deploy/install clicks.

For true "see what Skyrim is showing" behavior, this project would need a separate live bridge: screenshot/OCR capture, SKSE telemetry, console-clicked FormIDs, or read-only xEdit/SSEEdit lookup. The current `in_game_issue_report` is file/state triage, not live vision.
