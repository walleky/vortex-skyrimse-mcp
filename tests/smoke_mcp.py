#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    server = Path(__file__).resolve().parents[1] / "server.py"
    sys.path.insert(0, str(server.parent))
    import server as mcp_server  # type: ignore

    assert mcp_server.state_path("persistent", "profiles", "profile.with.dot") == r"persistent.profiles.profile\.with\.dot"
    assert mcp_server.split_state_path(r"persistent.profiles.profile\.with\.dot") == [
        "persistent",
        "profiles",
        "profile.with.dot",
    ]
    parsed = mcp_server.parse_vortex_get_output('persistent.profiles.test = {"id":"test","modState":{}}\n')
    assert parsed["values"]["persistent.profiles.test"]["id"] == "test"
    clone, changes = mcp_server.clone_profile_changes(
        "clone",
        "Safe Clone",
        {
            "id": "source",
            "gameId": "skyrimse",
            "name": "Source",
            "lastActivated": 1,
            "modState": {"mod.with.dot": {"enabled": True, "enabledTime": 2}},
        },
        False,
    )
    assert clone["id"] == "clone"
    assert any(change["path"] == r"persistent.profiles.clone.modState.mod\.with\.dot" for change in changes)
    batches = mcp_server.batched_state_changes(changes, max_chars=200)
    assert batches and sum(len(batch) for batch in batches) == len(changes)
    snapshot = {
        "gameId": "skyrimse",
        "activeProfileId": "source",
        "profiles": {"source": clone},
        "mods": {"mod.with.dot": {"name": "Example Mod"}},
    }
    backup = mcp_server.build_profile_backup(snapshot, {"source": clone}, include_mod_metadata=True)
    assert backup["schema"] == "vortex-skyrimse-profile-backup-v1", backup
    assert backup["profiles"]["source"]["name"] == "Safe Clone", backup
    restore_changes = mcp_server.restore_profile_changes(
        "source",
        {"name": "Original", "modState": {"keep": {"enabled": True}}},
        {"name": "Changed", "modState": {"keep": {"enabled": False}, "extra": {"enabled": True}}},
        disable_extra_mods=True,
    )
    assert any(change["path"] == "persistent.profiles.source.name" for change in restore_changes), restore_changes
    assert any(change["path"] == "persistent.profiles.source.modState.keep" for change in restore_changes), restore_changes
    assert any(change["path"] == "persistent.profiles.source.modState.extra.enabled" for change in restore_changes), restore_changes
    findings = []
    mcp_server.add_finding(findings, "low", "later", "later", "later")
    mcp_server.add_finding(findings, "critical", "first", "first", "first")
    assert mcp_server.sort_findings(findings)[0]["code"] == "first"

    listed = subprocess.run(
        [sys.executable, str(server), "--list-tools"],
        text=True,
        capture_output=True,
        check=True,
    )
    listed_json = json.loads(listed.stdout)
    listed_names = [tool["name"] for tool in listed_json["tools"]]
    listed_by_name = {tool["name"]: tool for tool in listed_json["tools"]}
    assert "detect_environment" in listed_names, listed_names
    assert "validate_setup" in listed_names, listed_names
    assert "mod_knowledge_report" in listed_names, listed_names
    assert "in_game_issue_report" in listed_names, listed_names
    assert "safe_session_report" in listed_names, listed_names
    assert "vortex_profile_backup" in listed_names, listed_names
    assert "vortex_profile_restore_plan" in listed_names, listed_names
    assert "performance_mode" in listed_by_name["in_game_issue_report"]["inputSchema"]["properties"], listed_by_name
    assert "response_mode" in listed_by_name["safe_session_report"]["inputSchema"]["properties"], listed_by_name

    direct = subprocess.run(
        [sys.executable, str(server), "--tool", "detect_environment"],
        text=True,
        capture_output=True,
        check=True,
    )
    direct_json = json.loads(direct.stdout)
    assert "issues" in direct_json, direct_json

    proc = subprocess.Popen(
        [sys.executable, str(server)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "detect_environment", "arguments": {}},
        },
    ]
    assert proc.stdin is not None
    assert proc.stdout is not None
    for msg in messages:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise AssertionError(f"no response from MCP server; stderr={stderr}")
        data = json.loads(line)
        assert data.get("jsonrpc") == "2.0", data
        assert data.get("id") == msg["id"], data
        assert "result" in data, data
        if msg["id"] == 2:
            names = [tool["name"] for tool in data["result"]["tools"]]
            assert "detect_environment" in names, names
            assert "validate_setup" in names, names
            assert "analyze_conflicts" in names, names
            assert "in_game_issue_report" in names, names
            assert "safe_session_report" in names, names
            assert "apply_ini_fixes" in names, names
            assert "vortex_profile_report" in names, names
            assert "vortex_profile_mods" in names, names
            assert "vortex_profile_deployment_report" in names, names
            assert "vortex_profile_backup" in names, names
            assert "vortex_profile_restore_plan" in names, names
            assert "vortex_clone_profile" in names, names
            assert "vortex_set_profile_mods" in names, names
            assert "skyrim_modded_play_report" in names, names
            assert "log_status" in names, names
            assert "bug_report_bundle" in names, names
        if msg["id"] == 3:
            assert data["result"]["isError"] is False, data
    proc.kill()
    print("MCP stdio smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
