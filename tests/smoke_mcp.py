#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    server = Path(__file__).resolve().parents[1] / "server.py"
    sys.path.insert(0, str(server.parent))
    import server as mcp_server  # type: ignore

    assert mcp_server.windows_drive_path_to_wsl_path(r"C:\Users\Alice\Documents") == "/mnt/c/Users/Alice/Documents"
    assert mcp_server.windows_drive_path_to_wsl_path("D:/SteamLibrary") == "/mnt/d/SteamLibrary"
    assert mcp_server.windows_path_to_wsl_path("/mnt/c/Users/Alice") == "/mnt/c/Users/Alice"
    assert mcp_server.windows_drive_path_to_wsl_path(r"\\?\C:\Games\Skyrim") == "/mnt/c/Games/Skyrim"
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
    temp_root = server.parent / ".local" / "smoke-cache-test"
    temp_root.mkdir(parents=True, exist_ok=True)
    cache_args = {"scan_cache_dir": str(temp_root)}
    cache_path = temp_root / "mod-summary-cache.json"
    if cache_path.exists():
        cache_path.unlink()
    mcp_server.write_scan_cache(cache_args, {"entries": {}})
    assert not cache_path.exists(), cache_path
    cache_payload = {"entries": {}, "_dirty": True}
    mcp_server.write_scan_cache(cache_args, cache_payload)
    assert cache_path.exists(), cache_path
    assert "_dirty" not in cache_path.read_text(encoding="utf-8"), cache_path.read_text(encoding="utf-8")
    pruned_payload = {
        "entries": {
            f"mod-{index}": {"fetchedAtEpoch": index, "summary": {"name": f"mod-{index}"}}
            for index in range(101)
        },
        "_dirty": True,
    }
    pruned_args = {"scan_cache_dir": str(temp_root), "scan_cache_max_entries": 100}
    mcp_server.write_scan_cache(pruned_args, pruned_payload)
    pruned_text = cache_path.read_text(encoding="utf-8")
    pruned_json = json.loads(pruned_text)
    assert "\n" not in pruned_text, pruned_text
    assert len(pruned_json["entries"]) == 100, pruned_json
    assert "mod-0" not in pruned_json["entries"], pruned_json
    assert "mod-100" in pruned_json["entries"], pruned_json
    assert pruned_json["lastPrunedCount"] == 1, pruned_json
    cache_status = mcp_server.scan_cache_status(pruned_args)
    assert cache_status["entryCount"] == 100, cache_status
    assert cache_status["maxEntries"] == 100, cache_status
    assert cache_status["prunableEntryCount"] == 0, cache_status
    assert cache_status["sizeBytes"] and cache_status["sizeBytes"] > 0, cache_status
    fixed_clone, fixed_changes, fix_preview = mcp_server.clone_profile_with_fix_changes(
        "clonefix",
        "Fixed Clone",
        {
            "id": "source",
            "gameId": "skyrimse",
            "name": "Source",
            "modState": {"bad": {"enabled": True}, "off": {"enabled": False}},
        },
        False,
        ["off"],
        ["bad"],
    )
    assert fixed_clone["id"] == "clonefix", fixed_clone
    bad_change = next(change for change in fixed_changes if change["path"] == "persistent.profiles.clonefix.modState.bad")
    off_change = next(change for change in fixed_changes if change["path"] == "persistent.profiles.clonefix.modState.off")
    assert bad_change["value"]["enabled"] is False, bad_change
    assert off_change["value"]["enabled"] is True, off_change
    assert {item["action"] for item in fix_preview} == {"enable", "disable"}, fix_preview
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
    assert "wsl_bridge_report" in listed_names, listed_names
    assert "validate_setup" in listed_names, listed_names
    assert "workflow_guide" in listed_names, listed_names
    assert "mod_knowledge_report" in listed_names, listed_names
    assert "in_game_issue_report" in listed_names, listed_names
    assert "skyrim_runtime_log_report" in listed_names, listed_names
    assert "config_file_report" in listed_names, listed_names
    assert "safe_session_report" in listed_names, listed_names
    assert "skyrim_diagnostics_report" in listed_names, listed_names
    assert "deployment_doctor_report" in listed_names, listed_names
    assert "skyrim_launch_doctor_report" in listed_names, listed_names
    assert "skse_runtime_doctor_report" in listed_names, listed_names
    assert "vortex_reversible_automation_plan" in listed_names, listed_names
    assert "scan_cache_status" in listed_names, listed_names
    assert "xedit_diagnostics_report" in listed_names, listed_names
    assert "xedit_inspection_script" in listed_names, listed_names
    assert "xedit_inspection_result_report" in listed_names, listed_names
    assert "skyrim_issue_case_packet" in listed_names, listed_names
    assert "skyrim_issue_case_status" in listed_names, listed_names
    assert "skyrim_issue_case_note" in listed_names, listed_names
    assert "skyrim_safe_experiment_plan" in listed_names, listed_names
    assert "skyrim_case_what_now" in listed_names, listed_names
    assert "skyrim_live_bridge_status" in listed_names, listed_names
    assert "skyrim_case_evidence_import" in listed_names, listed_names
    assert "skyrim_case_inbox_import" in listed_names, listed_names
    assert "skyrim_case_evidence_report" in listed_names, listed_names
    assert "skyrim_case_bundle" in listed_names, listed_names
    assert "vortex_collection_report" in listed_names, listed_names
    assert "collection_local_match_report" in listed_names, listed_names
    assert "nexus_validate_key" in listed_names, listed_names
    assert "nexus_update_report" in listed_names, listed_names
    assert "vortex_profile_backup" in listed_names, listed_names
    assert "vortex_profile_restore_plan" in listed_names, listed_names
    assert "vortex_safe_profile_fix" in listed_names, listed_names
    assert "apply_config_text_patch" in listed_names, listed_names
    assert "report_viewer_index" in listed_names, listed_names
    assert "performance_mode" in listed_by_name["in_game_issue_report"]["inputSchema"]["properties"], listed_by_name
    assert "response_mode" in listed_by_name["safe_session_report"]["inputSchema"]["properties"], listed_by_name
    assert "include_runtime_logs" in listed_by_name["safe_session_report"]["inputSchema"]["properties"], listed_by_name
    assert "max_log_bytes_per_file" in listed_by_name["skyrim_runtime_log_report"]["inputSchema"]["properties"], listed_by_name
    assert "fresh_log_hours" in listed_by_name["skyrim_runtime_log_report"]["inputSchema"]["properties"], listed_by_name
    assert "path" in listed_by_name["config_file_report"]["inputSchema"]["properties"], listed_by_name
    assert "include_nexus_metadata" in listed_by_name["skyrim_diagnostics_report"]["inputSchema"]["properties"], listed_by_name
    assert "scan_cache_dir" in listed_by_name["mod_knowledge_report"]["inputSchema"]["properties"], listed_by_name
    assert "scan_cache_max_entries" in listed_by_name["scan_cache_status"]["inputSchema"]["properties"], listed_by_name
    assert "scan_cache_max_entries" in listed_by_name["mod_knowledge_report"]["inputSchema"]["properties"], listed_by_name
    assert "deployment_probe_files_per_mod" in listed_by_name["deployment_doctor_report"]["inputSchema"]["properties"], listed_by_name
    assert "output_path" in listed_by_name["deployment_doctor_report"]["inputSchema"]["properties"], listed_by_name
    assert "baseline_path" in listed_by_name["deployment_doctor_report"]["inputSchema"]["properties"], listed_by_name
    assert "output_path" in listed_by_name["skyrim_launch_doctor_report"]["inputSchema"]["properties"], listed_by_name
    assert "output_path" in listed_by_name["skse_runtime_doctor_report"]["inputSchema"]["properties"], listed_by_name
    assert "request" in listed_by_name["vortex_reversible_automation_plan"]["inputSchema"]["properties"], listed_by_name
    assert "report_dir" in listed_by_name["report_viewer_index"]["inputSchema"]["properties"], listed_by_name
    assert "disable_mod_ids" in listed_by_name["vortex_reversible_automation_plan"]["inputSchema"]["properties"], listed_by_name
    assert "include_xedit_report" in listed_by_name["safe_session_report"]["inputSchema"]["properties"], listed_by_name
    assert "report_path" in listed_by_name["xedit_inspection_script"]["inputSchema"]["properties"], listed_by_name
    assert "max_preview_rows" in listed_by_name["xedit_inspection_result_report"]["inputSchema"]["properties"], listed_by_name
    assert "case_dir" in listed_by_name["skyrim_issue_case_packet"]["inputSchema"]["properties"], listed_by_name
    assert "case_dir" in listed_by_name["skyrim_issue_case_status"]["inputSchema"]["properties"], listed_by_name
    assert "note" in listed_by_name["skyrim_issue_case_note"]["inputSchema"]["properties"], listed_by_name
    assert "target_mod_id" in listed_by_name["skyrim_safe_experiment_plan"]["inputSchema"]["properties"], listed_by_name
    assert "disable_mod_ids" in listed_by_name["vortex_safe_profile_fix"]["inputSchema"]["properties"], listed_by_name
    assert "include_mod_metadata" in listed_by_name["vortex_safe_profile_fix"]["inputSchema"]["properties"], listed_by_name
    assert "evidence_type" in listed_by_name["skyrim_case_evidence_import"]["inputSchema"]["properties"], listed_by_name
    assert "inbox_dir" in listed_by_name["skyrim_case_inbox_import"]["inputSchema"]["properties"], listed_by_name
    assert "max_entries" in listed_by_name["skyrim_case_evidence_report"]["inputSchema"]["properties"], listed_by_name
    assert "max_file_bytes" in listed_by_name["skyrim_case_bundle"]["inputSchema"]["properties"], listed_by_name
    assert "include_collection_report" in listed_by_name["bug_report_bundle"]["inputSchema"]["properties"], listed_by_name
    assert "workflow_key" in listed_by_name["workflow_guide"]["inputSchema"]["properties"], listed_by_name

    direct = subprocess.run(
        [sys.executable, str(server), "--tool", "detect_environment"],
        text=True,
        capture_output=True,
        check=True,
    )
    direct_json = json.loads(direct.stdout)
    assert "issues" in direct_json, direct_json
    assert "wsl" in direct_json, direct_json

    wsl_direct = subprocess.run(
        [sys.executable, str(server), "--wsl-bridge"],
        text=True,
        capture_output=True,
        check=True,
    )
    wsl_json = json.loads(wsl_direct.stdout)
    assert "wsl" in wsl_json, wsl_json
    assert "openClawConfigHint" in wsl_json, wsl_json

    workflow_direct = subprocess.run(
        [sys.executable, str(server), "--workflow-guide", "--problem", "mods downloaded but not working"],
        text=True,
        capture_output=True,
        check=True,
    )
    workflow_json = json.loads(workflow_direct.stdout)
    assert workflow_json["workflows"][0]["key"] == "mods_not_working", workflow_json
    assert "deployment_doctor_report" in workflow_json["workflows"][0]["tools"], workflow_json

    doctor_md = temp_root / "deployment-doctor-smoke.md"
    doctor_direct = subprocess.run(
        [sys.executable, str(server), "--deployment-doctor", "--output-path", str(doctor_md)],
        text=True,
        capture_output=True,
        check=False,
    )
    doctor_json = json.loads(doctor_direct.stdout)
    assert "summary" in doctor_json or "error" in doctor_json, doctor_json
    assert doctor_md.exists(), doctor_json
    assert "Deployment Doctor" in doctor_md.read_text(encoding="utf-8"), doctor_md

    launch_md = temp_root / "launch-doctor-smoke.md"
    launch_direct = subprocess.run(
        [sys.executable, str(server), "--launch-doctor", "--output-path", str(launch_md)],
        text=True,
        capture_output=True,
        check=False,
    )
    launch_json = json.loads(launch_direct.stdout)
    assert "summary" in launch_json or "error" in launch_json, launch_json
    assert launch_md.exists(), launch_json
    assert "Launch Doctor" in launch_md.read_text(encoding="utf-8"), launch_md

    skse_md = temp_root / "skse-runtime-doctor-smoke.md"
    skse_direct = subprocess.run(
        [sys.executable, str(server), "--skse-doctor", "--output-path", str(skse_md)],
        text=True,
        capture_output=True,
        check=False,
    )
    skse_json = json.loads(skse_direct.stdout)
    assert "summary" in skse_json or "error" in skse_json, skse_json
    assert skse_md.exists(), skse_json
    assert "SKSE Runtime Doctor" in skse_md.read_text(encoding="utf-8"), skse_md

    automation_direct = subprocess.run(
        [sys.executable, str(server), "--automation-plan", "--request", "delete redundant mods and sort load order safely"],
        text=True,
        capture_output=True,
        check=False,
    )
    automation_json = json.loads(automation_direct.stdout)
    assert automation_json["dryRunOnly"] is True, automation_json
    assert any(plan["action"] == "delete_or_uninstall_mods" for plan in automation_json["actionPlans"]), automation_json
    assert any(plan["action"] == "sort_load_order" for plan in automation_json["actionPlans"]), automation_json

    viewer_dir = temp_root / "viewer-reports"
    viewer_dir.mkdir(exist_ok=True)
    (viewer_dir / "deployment-doctor-sample.json").write_text(
        json.dumps({"summary": {"deploymentState": "linked", "ready": True}, "findings": []}),
        encoding="utf-8",
    )
    (viewer_dir / "notes.md").write_text("# Sample Report\n\nEverything is linked.\n", encoding="utf-8")
    viewer_html = viewer_dir / "report-viewer.html"
    viewer_direct = subprocess.run(
        [
            sys.executable,
            str(server),
            "--report-viewer",
            "--report-dir",
            str(viewer_dir),
            "--output-path",
            str(viewer_html),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    viewer_json = json.loads(viewer_direct.stdout)
    assert viewer_json["fileCount"] >= 2, viewer_json
    assert viewer_html.exists(), viewer_json
    viewer_text = viewer_html.read_text(encoding="utf-8")
    assert "Vortex Skyrim SE Report Viewer" in viewer_text
    assert "deployment-doctor-sample.json" in viewer_text

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
            assert "wsl_bridge_report" in names, names
            assert "validate_setup" in names, names
            assert "workflow_guide" in names, names
            assert "analyze_conflicts" in names, names
            assert "in_game_issue_report" in names, names
            assert "skyrim_runtime_log_report" in names, names
            assert "config_file_report" in names, names
            assert "safe_session_report" in names, names
            assert "skyrim_diagnostics_report" in names, names
            assert "deployment_doctor_report" in names, names
            assert "skyrim_launch_doctor_report" in names, names
            assert "skse_runtime_doctor_report" in names, names
            assert "vortex_reversible_automation_plan" in names, names
            assert "scan_cache_status" in names, names
            assert "xedit_diagnostics_report" in names, names
            assert "xedit_inspection_script" in names, names
            assert "xedit_inspection_result_report" in names, names
            assert "skyrim_issue_case_packet" in names, names
            assert "skyrim_issue_case_status" in names, names
            assert "skyrim_issue_case_note" in names, names
            assert "skyrim_safe_experiment_plan" in names, names
            assert "skyrim_case_what_now" in names, names
            assert "skyrim_live_bridge_status" in names, names
            assert "skyrim_case_evidence_import" in names, names
            assert "skyrim_case_inbox_import" in names, names
            assert "skyrim_case_evidence_report" in names, names
            assert "skyrim_case_bundle" in names, names
            assert "vortex_collection_report" in names, names
            assert "collection_local_match_report" in names, names
            assert "nexus_validate_key" in names, names
            assert "nexus_mod_lookup" in names, names
            assert "nexus_update_report" in names, names
            assert "apply_ini_fixes" in names, names
            assert "apply_config_text_patch" in names, names
            assert "vortex_profile_report" in names, names
            assert "vortex_profile_mods" in names, names
            assert "vortex_profile_deployment_report" in names, names
            assert "vortex_profile_backup" in names, names
            assert "vortex_profile_restore_plan" in names, names
            assert "vortex_clone_profile" in names, names
            assert "vortex_set_profile_mods" in names, names
            assert "vortex_safe_profile_fix" in names, names
            assert "skyrim_modded_play_report" in names, names
            assert "log_status" in names, names
            assert "report_viewer_index" in names, names
            assert "bug_report_bundle" in names, names
        if msg["id"] == 3:
            assert data["result"]["isError"] is False, data
    proc.kill()
    print("MCP stdio smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
