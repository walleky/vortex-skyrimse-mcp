# Improvement Notes

These are useful next steps, ordered by value and risk.

## Best Next Improvements

1. Add richer Vortex collection detection if Vortex exposes collection state through stable CLI paths.
2. Add more plugin metadata parsing for ESP/ESM headers beyond masters, such as plugin version and record counts.
3. Add a tiny local HTML report viewer for generated JSON/Markdown outputs.
4. Add Nexus/Vortex collection manifest detection if stable local collection metadata is available.
5. Add a synthetic Vortex profile fixture so profile/deployment behavior can be tested without a real Vortex install.
6. Add a profile restore apply helper in the local menu only after the preview UX is clear enough for nontechnical users.

## What Not To Automate Yet

- Do not auto-delete redundant mods.
- Do not auto-sort load order.
- Do not auto-write Vortex conflict rules.
- Do not auto-disable mods from broad guesses.
- Do not trigger deployment, installs, updates, removals, load-order writes, or Nexus account actions from outside Vortex until there is a stable supported API path.

Those actions can break saves. Keep them as reports or dry-run plans until the evidence is strong and the user approves.

## Code Health Improvements

- Split `server.py` into modules once it becomes painful to navigate:
  - `paths.py`
  - `logging_support.py`
  - `vortex_cli.py`
  - `mods.py`
  - `plugins.py`
  - `profiles.py`
  - `mcp_server.py`
- Keep the current single-file shape while rapid iteration is more useful than packaging polish.
- Expand `tests/smoke_mcp.py` into fixture-based tests before making larger refactors.

## OpenClaw Experience Improvements

- Teach OpenClaw to call `bug_report_bundle` automatically after any tool exception.
- Teach OpenClaw to call `validate_setup` before diagnosis and `vortex_profile_backup` before profile experiments.
- Teach OpenClaw to call `mod_knowledge_report` before suggesting collection cleanup.
- Teach OpenClaw to read `docs/OPENCLAW-AGENT-GUIDE.md` before applying any profile or INI write.
- Prefer one-shot `skyrim_modded_play_report` for first diagnosis, then narrower tools.
- Keep direct CLI commands working for no-OpenClaw recovery and report generation.
- Keep final answers short and action-oriented for nontechnical users.
