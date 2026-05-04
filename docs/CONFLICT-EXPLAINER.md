# Conflict Explainer

`analyze_conflicts` now adds an `explanation` object to each loose-file conflict
so OpenClaw can explain why the conflict matters instead of dumping file paths.

## Risk Levels

`high`

Scripts, SKSE plugins, plugins, and archives. These can affect runtime behavior,
quest logic, records, and engine/plugin behavior.

`medium`

Interface, config, MCM-like, and generated-tool outputs. These can break menus,
settings, and generated patch outputs.

`low-medium`

Meshes and textures. Often visual, but body, skeleton, physics, and animation
assets still deserve care.

`low`

Less-classified files or same-hash duplicate files. Usually review only when the
path matches the problem being diagnosed.

## What The MCP Can And Cannot Know

The MCP can see which staged mods provide the same relative file path. It cannot
always know Vortex's final conflict-rule winner from the loose-file scan alone.

For final conflict decisions, use Vortex's Conflicts view and the mod authors'
compatibility instructions.

## Agent Guidance

When conflicts are relevant:

1. Sort by `riskSummary` and high-risk `explanation.risk` first.
2. Explain `impact` and `safeAction` in plain language.
3. Do not change rules automatically.
4. Prefer a cloned profile when testing conflict winner changes.
5. Same-hash conflicts are usually harmless duplication.
