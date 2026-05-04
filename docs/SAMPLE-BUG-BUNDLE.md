# Sample Bug Bundle

This is a shortened, sanitized example of what `bug_report_bundle` writes. It helps OpenClaw agents understand the shape before reading a real user bundle.

```json
{
  "generatedAt": "2026-05-04T01:30:00.000",
  "server": "vortex-skyrimse-mcp",
  "version": "0.2.6",
  "output_path": "%USERPROFILE%\\Documents\\vortex-skyrimse-mcp-bug-report-20260504-013000.json",
  "log_dir": "%LOCALAPPDATA%\\vortex-skyrimse-mcp\\logs",
  "privacyNote": "This bundle may include local Windows paths, mod names, plugin names, and recent MCP logs. Review before posting publicly.",
  "redactedUserPaths": true,
  "bugReportTemplate": {
    "summary": "What did you expect OpenClaw/Vortex/Skyrim to do, and what happened instead?",
    "reproductionSteps": [
      "What command, MCP tool, or OpenClaw prompt did you run?",
      "Was Vortex open or closed?",
      "Which Vortex profile was active?"
    ]
  },
  "environment": {
    "vortex_exe": "%LOCALAPPDATA%\\Programs\\Vortex\\Vortex.exe",
    "staging_dir": "%APPDATA%\\Vortex\\skyrimse\\mods",
    "skyrim_dir": "C:\\SteamLibrary\\steamapps\\common\\Skyrim Special Edition",
    "issues": []
  },
  "skyrimModdedPlay": {
    "findings": [
      {
        "severity": "high",
        "code": "enabled_profile_plugins_not_deployed",
        "message": "3 plugin(s) from enabled profile mods are not in Skyrim Data.",
        "nextAction": "Click Deploy Mods in Vortex and confirm the game path/staging path are correct."
      }
    ]
  },
  "logs": {
    "status": {
      "channels": {
        "server": 1,
        "tool": 1,
        "vortex-cli": 1
      }
    },
    "recentFiles": [
      {
        "name": "tool-20260504.jsonl",
        "channel": "tool",
        "tail": "{\"event\":\"tool_error\",\"data\":{\"tool\":\"vortex_profile_report\"}}"
      }
    ]
  }
}
```

OpenClaw should start with `skyrimModdedPlay.findings`, then check `vortexProfileDeployment.issues`, then recent `tool_error` or `vortex-cli` timeout entries.
