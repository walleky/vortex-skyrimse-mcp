# Mod Knowledge Reports

`mod_knowledge_report` writes a Markdown map of a Skyrim SE Vortex collection. It is meant for OpenClaw and humans who need to understand a large mod list before removing anything.

## What It Uses

The report uses local evidence only:

- staged Vortex mod folders
- ESP/ESM/ESL plugin headers and masters
- BSA archives
- SKSE DLLs
- Papyrus scripts
- meshes, textures, interface files, configs, and animation-tool files
- FOMOD metadata
- readme snippets
- Vortex profile enabled/disabled state, if Vortex CLI is available
- duplicate plugin/Nexus id/file coverage evidence
- file-level conflict examples

It does not download Nexus page descriptions. That keeps the tool dependency-free and avoids rate-limit/API surprises, but it also means the report is an evidence map, not a perfect encyclopedia.

## Basic OpenClaw Prompt

```text
Use the vortex-skyrimse MCP to run mod_knowledge_report. Write the Markdown report, summarize the top removal-review candidates, and do not apply changes.
```

## Direct Command

If OpenClaw is not set up yet:

```powershell
py -3 .\server.py --mod-knowledge
```

Or use the wrapper:

```powershell
.\make_mod_knowledge.ps1
```

You can also double-click `Make-Mod-Knowledge.cmd`.

For a broader local menu, double-click `Vortex-SkyrimSE-Menu.cmd`.

For slower but stronger duplicate evidence:

```text
Run mod_knowledge_report with hash_files=true. Summarize only high-confidence duplicate or no-game-file candidates. Do not apply changes.
```

## How To Read The Report

Start with:

1. `Removal Review Shortlist`: strongest local evidence for cleanup.
2. `Sensitive Conflict Examples`: scripts, plugins, UI, config, animation, and SKSE overlaps.
3. `Plugin Master Problems`: plugins that depend on missing masters.
4. `Mod Index`: one-line role map for the full collection.
5. `Mod Details`: evidence for each mod, including plugin masters and readme excerpts.

## Removal Safety

Do not delete mods directly from a big collection.

Safer flow:

1. Clone the current Vortex profile.
2. Disable candidate mods in the cloned profile.
3. Deploy mods in Vortex.
4. Launch Skyrim through SKSE.
5. Test the same save and a new game.
6. Only uninstall/delete after the cloned-profile test works.

The MCP can help preview exact profile changes with `vortex_set_profile_mods apply=false`. Use `apply=true` only after the user explicitly approves and Vortex is closed.

## Risk Meaning

- `high`: plugins, scripts, SKSE DLLs, or other files that can affect saves/runtime.
- `medium`: UI, animation tools, configs, or support files that can break menus or generated outputs.
- `low-medium`: visual assets such as textures and meshes. Usually easier to disable, but body/skeleton/physics mods still need care.
- `low`: no recognized game files, or documentation/leftover files only.

## Limits

The report cannot know the author's intent unless the intent is visible in local metadata, readmes, file names, plugin headers, or the Vortex state. For uncertain mods, OpenClaw should say "candidate" and ask the user whether that content is wanted.
