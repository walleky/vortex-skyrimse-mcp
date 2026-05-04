#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import struct
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path


def plugin_bytes(*masters: str) -> bytes:
    payload = b""
    for master in masters:
        raw = master.encode("utf-8") + b"\0"
        payload += b"MAST" + struct.pack("<H", len(raw)) + raw
    return b"TES4" + struct.pack("<I", len(payload)) + (b"\0" * 16) + payload


def write(path: Path, data: bytes | str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")


@contextmanager
def fixture_root(parent: Path):
    root = parent / "fixture-current"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    import server  # type: ignore

    tmp_parent = repo / ".local" / "test-tmp"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with fixture_root(tmp_parent) as root:
        os.environ["USERPROFILE"] = str(root)
        os.environ["LOCALAPPDATA"] = str(root / "AppData" / "Local")
        os.environ["APPDATA"] = str(root / "AppData" / "Roaming")
        skyrim = root / "SteamLibrary" / "steamapps" / "common" / "Skyrim Special Edition"
        data = skyrim / "Data"
        vortex_appdata = root / "AppData" / "Roaming" / "Vortex"
        staging = vortex_appdata / "skyrimse" / "mods"
        local_appdata = root / "AppData" / "Local"
        plugins_dir = local_appdata / "Skyrim Special Edition"
        my_games = root / "Documents" / "My Games" / "Skyrim Special Edition"
        vortex_exe = root / "AppData" / "Local" / "Programs" / "Vortex" / "Vortex.exe"
        log_dir = root / "Logs"

        write(skyrim / "SkyrimSE.exe")
        write(skyrim / "skse64_loader.exe")
        write(data / "Skyrim.esm", plugin_bytes())
        write(data / "Update.esm", plugin_bytes("Skyrim.esm"))
        write(data / "MyMod.esp", plugin_bytes("Skyrim.esm"))
        write(staging / "Weather Mod" / "BrokenWeather.esp", plugin_bytes("MissingMaster.esm"))
        write(staging / "Weather Mod" / "scripts" / "shared.pex", "weather")
        write(staging / "Lighting Mod" / "scripts" / "shared.pex", "lighting")
        write(staging / "Lighting Mod" / "readme.txt", "Lighting tweaks")
        write(staging / "Readme Pack" / "readme.txt", "Just a note file for cleanup testing")
        write(
            staging / "Whiterun Tavern Overhaul" / "WhiterunTavern.esp",
            plugin_bytes("Skyrim.esm") + b"Whiterun Bannered Mare tavern room bed furniture popup message",
        )
        write(staging / "Whiterun Tavern Overhaul" / "readme.txt", "Places a bed in the Whiterun Bannered Mare tavern room.")
        write(staging / "Popup UI Mod" / "interface" / "annoyingpopup.swf", "ui")
        write(staging / "Popup UI Mod" / "scripts" / "popupnotice.pex", "script")
        write(staging / "Popup UI Mod" / "config" / "popup.json", '{"warning":"notification after loading a save"}')
        write(staging / "Popup UI Mod" / "readme.txt", "Shows a warning notification after loading a save. Configure the popup in MCM.")
        write(plugins_dir / "plugins.txt", "# comment\r\n*Skyrim.esm\r\n*MYMOD.ESP\r\n*MissingOnDisk.esp\r\n")
        write(my_games / "Skyrim.ini", "[Archive]\nbInvalidateOlderFiles=1\n")
        write(my_games / "SkyrimPrefs.ini", "[Launcher]\nbEnableFileSelection=1\n")
        write(vortex_exe)
        write(log_dir / "tool-20260504.jsonl", '{"event":"tool_error","path":"%USERPROFILE%\\\\example"}\n')

        base_args = {
            "skyrim_dir": str(skyrim),
            "staging_dir": str(staging),
            "vortex_appdata": str(vortex_appdata),
            "vortex_exe": str(vortex_exe),
            "local_appdata": str(local_appdata),
            "my_games_dir": str(my_games),
        }

        env = server.detect_environment(base_args)
        assert env["skse_installed"] is True, env
        assert not [issue for issue in env["issues"] if "SkyrimSE.exe" in issue], env
        setup = server.validate_setup(base_args)
        assert setup["ready"] is True, setup

        inventory = server.inventory_mods({**base_args, "include_files": True})
        assert inventory["modCount"] == 5, inventory

        conflicts = server.analyze_conflicts(base_args)
        assert any(item["relativePath"] == "scripts/shared.pex" for item in conflicts["conflicts"]), conflicts

        plugins = server.plugin_report(base_args)
        assert "MissingOnDisk.esp" in plugins["missingEnabledPlugins"], plugins
        assert any(item["missingMaster"] == "MissingMaster.esm" for item in plugins["missingMasters"]), plugins

        issue = server.in_game_issue_report(
            {
                **base_args,
                "description": "There is a bed outside the tavern room and it is messing things up.",
                "location": "Whiterun Bannered Mare",
                "object": "bed",
                "form_id": "0100ABCD",
                "base_object": "CommonBed01",
                "cell": "WhiterunBanneredMare",
                "include_profile_state": False,
            }
        )
        assert issue["candidateCount"] >= 1, issue
        assert issue["candidates"][0]["mod"] == "Whiterun Tavern Overhaul", issue
        assert issue["candidates"][0]["confidence"] == "high", issue
        assert issue["profileState"]["mappedModCount"] == 0, issue
        assert "modsByPath" not in issue["profileState"], issue
        assert issue["formIdHint"]["pluginName"] == "MYMOD.ESP", issue

        popup_issue = server.in_game_issue_report(
            {
                **base_args,
                "description": "popup after loading a save",
                "popup_text": "Bannered Mare tavern room bed furniture popup message",
                "issue_kind": "popup",
                "include_profile_state": False,
            }
        )
        assert popup_issue["candidates"][0]["mod"] == "Whiterun Tavern Overhaul", popup_issue
        assert popup_issue["candidates"][0]["confidence"] == "high", popup_issue

        natural_popup = server.in_game_issue_report(
            {
                **base_args,
                "description": "annoying popup after loading a save",
                "include_profile_state": False,
            }
        )
        assert natural_popup["issue"]["kind"] == "popup", natural_popup
        assert natural_popup["issue"]["popupTextProvided"] is False, natural_popup
        assert natural_popup["issue"]["popupTextRequired"] is False, natural_popup
        assert natural_popup["issue"]["naturalLanguagePopup"] is True, natural_popup
        assert natural_popup["scan"]["mode"] == "balanced", natural_popup
        assert natural_popup["diagnosticQuality"]["level"] in {"medium", "strong"}, natural_popup
        assert natural_popup["candidates"][0]["mod"] == "Popup UI Mod", natural_popup
        assert natural_popup["candidates"][0]["popupEvidenceMode"] == "natural_language", natural_popup
        assert natural_popup["candidates"][0]["scannedPathCount"] > 0, natural_popup
        assert any(item["source"].startswith("file path:") for item in natural_popup["candidates"][0]["evidence"]), natural_popup

        compact_popup = server.in_game_issue_report(
            {
                **base_args,
                "description": "annoying popup after loading a save",
                "response_mode": "compact",
                "max_candidates": 2,
                "include_profile_state": False,
            }
        )
        assert compact_popup["responseMode"] == "compact", compact_popup
        assert compact_popup["candidateCount"] >= 1, compact_popup
        assert len(compact_popup["candidates"]) <= 2, compact_popup
        assert compact_popup["candidates"][0]["mod"] == "Popup UI Mod", compact_popup
        assert "path" not in compact_popup["candidates"][0], compact_popup
        assert len(compact_popup["candidates"][0]["evidence"]) <= 3, compact_popup
        assert compact_popup["performanceMode"] == "normal", compact_popup

        popup_kind_only = server.in_game_issue_report(
            {
                **base_args,
                "issue_kind": "popup",
                "include_profile_state": False,
            }
        )
        assert popup_kind_only["issue"]["kind"] == "popup", popup_kind_only
        assert popup_kind_only["issue"]["popupTextRequired"] is False, popup_kind_only
        assert popup_kind_only["scan"]["mode"] == "balanced", popup_kind_only
        assert popup_kind_only["candidateCount"] >= 1, popup_kind_only

        safe_md = root / "safe-session.md"
        safe_json = root / "safe-session.json"
        safe = server.safe_session_report(
            {
                **base_args,
                "output_path": str(safe_md),
                "session_json_path": str(safe_json),
                "include_profile_backup": False,
                "include_play_report": False,
                "include_logs": True,
                "log_dir": str(log_dir),
                "description": "There is a bed outside the tavern room and it is messing things up.",
                "location": "Whiterun Bannered Mare",
                "object": "bed",
                "include_profile_state": False,
                "redact_user_paths": True,
            }
        )
        assert safe_md.exists(), safe
        assert safe_json.exists(), safe
        safe_text = safe_md.read_text(encoding="utf-8")
        safe_payload_text = safe_json.read_text(encoding="utf-8")
        safe_payload = json.loads(safe_payload_text)
        assert "Vortex Skyrim SE Safe Session" in safe_text
        assert "Whiterun Tavern Overhaul" in safe_text
        assert str(root) not in safe_text
        assert str(root) not in safe_payload_text
        assert "inGameIssue" in safe["sections"], safe
        assert safe_payload["dryRunOnly"] is True, safe_payload

        slow_safe_md = root / "safe-session-slow.md"
        slow_safe_json = root / "safe-session-slow.json"
        slow_safe = server.safe_session_report(
            {
                **base_args,
                "output_path": str(slow_safe_md),
                "session_json_path": str(slow_safe_json),
                "performance_mode": "slow_model",
                "include_play_report": False,
                "include_logs": False,
                "description": "annoying popup after loading a save",
                "include_profile_state": False,
                "redact_user_paths": True,
            }
        )
        slow_payload = json.loads(slow_safe_json.read_text(encoding="utf-8"))
        assert slow_safe["summary"]["performanceMode"] == "slow_model", slow_safe
        assert slow_safe["summary"]["responseMode"] == "compact", slow_safe
        assert "profileBackup" not in slow_payload["sections"], slow_payload
        assert "inGameIssue" in slow_payload["sections"], slow_payload
        assert slow_payload["sections"]["inGameIssue"]["responseMode"] == "compact", slow_payload
        assert "path" not in slow_payload["sections"]["inGameIssue"]["candidates"][0], slow_payload

        cli_safe_md = root / "safe-session-cli.md"
        cli_safe_json = root / "safe-session-cli.json"
        cli_safe_result = subprocess.run(
            [
                sys.executable,
                str(repo / "server.py"),
                "--safe-session",
                "--output-path",
                str(cli_safe_md),
                "--session-json-path",
                str(cli_safe_json),
                "--staging-dir",
                str(staging),
                "--skyrim-dir",
                str(skyrim),
                "--local-appdata",
                str(local_appdata),
                "--my-games-dir",
                str(my_games),
                "--log-dir",
                str(log_dir),
                "--description",
                "bed outside tavern room",
                "--location",
                "Whiterun Bannered Mare",
                "--object",
                "bed",
                "--performance-mode",
                "slow_model",
                "--no-profile-backup",
                "--no-play-report",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        cli_safe_payload = json.loads(cli_safe_result.stdout)
        assert cli_safe_md.exists(), cli_safe_payload
        assert cli_safe_json.exists(), cli_safe_payload
        assert "inGameIssue" in cli_safe_payload["sections"], cli_safe_payload
        assert cli_safe_payload["summary"]["responseMode"] == "compact", cli_safe_payload

        knowledge_path = root / "knowledge.md"
        knowledge = server.mod_knowledge_report(
            {
                **base_args,
                "output_path": str(knowledge_path),
                "include_profile_state": False,
                "include_conflicts": True,
                "include_redundancy": True,
                "include_plugin_report": True,
                "include_readme_excerpts": True,
                "redact_user_paths": True,
                "max_detail_mods": 10,
            }
        )
        assert knowledge_path.exists(), knowledge
        knowledge_text = knowledge_path.read_text(encoding="utf-8")
        assert "Skyrim SE Mod Knowledge Report" in knowledge_text
        assert "Weather Mod" in knowledge_text
        assert "MissingMaster.esm" in knowledge_text
        assert "scripts/shared.pex" in knowledge_text
        assert "Readme Pack" in knowledge_text
        assert str(root) not in knowledge_text
        assert knowledge["removalCandidateCount"] >= 1, knowledge

        cli_knowledge_path = root / "knowledge-cli.md"
        cli_result = subprocess.run(
            [
                sys.executable,
                str(repo / "server.py"),
                "--mod-knowledge",
                "--output-path",
                str(cli_knowledge_path),
                "--staging-dir",
                str(staging),
                "--skyrim-dir",
                str(skyrim),
                "--local-appdata",
                str(local_appdata),
                "--no-profile-state",
                "--max-mods",
                "10",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        cli_payload = json.loads(cli_result.stdout)
        assert cli_payload["modCount"] == 5, cli_payload
        assert cli_knowledge_path.exists(), cli_payload

        bundle_path = root / "bundle.json"
        bundle = server.bug_report_bundle(
            {
                **base_args,
                "output_path": str(bundle_path),
                "log_dir": str(log_dir),
                "include_vortex_profiles": False,
                "include_vortex_deployment": False,
                "include_play_report": False,
                "include_logs": True,
                "redact_user_paths": True,
                "zip_output": True,
                "max_log_files": 5,
                "max_log_bytes": 2000,
            }
        )
        assert bundle_path.exists(), bundle
        assert Path(bundle["zip_path"]).exists(), bundle
        payload_text = bundle_path.read_text(encoding="utf-8")
        assert str(Path.home()) not in payload_text
        assert str(root) not in payload_text
        payload = json.loads(payload_text)
        assert payload["redactedUserPaths"] is True
        assert payload["setupValidation"]["ready"] is True
        assert "logs" in payload

        with zipfile.ZipFile(bundle["zip_path"]) as archive:
            names = set(archive.namelist())
            assert "README-BUG-REPORT.txt" in names, names
            assert "bundle.json" in names, names
            assert any(name.startswith("logs/") for name in names), names

    print("Fixture MCP tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
