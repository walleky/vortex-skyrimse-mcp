# Known Mod Rules

`known_mod_rule_report` is a read-only heuristic pass for common Skyrim SE
collection problems that plain file inventory can miss.

It runs automatically inside `inventory_mods` by default and is also included in
the broad modded play health report.

## What It Catches Now

- FNIS and Pandora Behavior Engine both staged.
- FNIS and Nemesis both staged.
- FSMPM present without JContainers evidence.
- SLAL/Leito animation content present without FNIS evidence.

These rules are intentionally conservative. They are not a replacement for mod
author instructions, collection notes, or xEdit evidence.

## Direct CLI

```powershell
py -3 .\server.py --known-rules
```

Or:

```powershell
py -3 .\server.py --tool known_mod_rule_report
```

For WSL/OpenClaw:

```bash
python3 server.py --known-rules
```

## OpenClaw Prompt

```text
Use known_mod_rule_report and deployment_doctor_report. Tell me whether my animation/dependency stack has known conflicts or missing dependencies, then tell me whether critical files are deployed. Do not apply changes.
```

## How OpenClaw Should Use It

Read `findings` first.

If the report flags an animation generator conflict, do not immediately disable
or delete mods. Use a cloned Vortex profile, follow the collection's behavior
generation instructions, deploy, and rerun Deployment Doctor.

If the report flags a missing dependency, install or enable the dependency in
Vortex, deploy, and rerun the report before testing a real save.

## Why This Exists

A raw scan can say "FNIS is installed" and "Pandora is installed" without
understanding that this is a risky combination for many profiles. This rule layer
turns common modding knowledge into structured findings that a slower OpenClaw
model can read without reverse-engineering every mod from scratch.

## Current Limits

- It cannot know every mod's hidden requirement.
- It only sees local staged files, names, metadata, and optional file lists.
- It does not use or scrape Vortex's private Nexus credentials.
- It does not generate FNIS/Nemesis/Pandora output.
- It does not edit Vortex rules, plugins, or profiles.
