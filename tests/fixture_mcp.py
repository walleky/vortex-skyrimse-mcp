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
        assert inventory["modCount"] == 3, inventory

        conflicts = server.analyze_conflicts(base_args)
        assert any(item["relativePath"] == "scripts/shared.pex" for item in conflicts["conflicts"]), conflicts

        plugins = server.plugin_report(base_args)
        assert "MissingOnDisk.esp" in plugins["missingEnabledPlugins"], plugins
        assert any(item["missingMaster"] == "MissingMaster.esm" for item in plugins["missingMasters"]), plugins

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
        assert cli_payload["modCount"] == 3, cli_payload
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
