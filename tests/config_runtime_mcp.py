#!/usr/bin/env python3
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path


def write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@contextmanager
def temp_root(parent: Path):
    root = parent / "config-runtime-current"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def expect_tool_error(func, text: str) -> None:
    try:
        func()
    except Exception as exc:
        if text.lower() not in str(exc).lower():
            raise AssertionError(f"expected error containing {text!r}, got {exc!r}") from exc
        return
    raise AssertionError(f"expected error containing {text!r}")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    import server  # type: ignore

    tmp_parent = repo / ".local" / "test-tmp"
    tmp_parent.mkdir(parents=True, exist_ok=True)

    with temp_root(tmp_parent) as root:
        allowed = root / "allowed"
        outside = root / "outside"
        write(allowed / "config" / "popup.json", '{"warning":"popup","configured":false}')
        write(allowed / "config" / "spaced.json", '{ "is_configured": 0, "name": "Example" }')
        write(allowed / "config" / "mod.properties", "name=Example\nconfigured=no\n")
        write(allowed / "config" / "settings.ini", "[Popup]\nconfigured=false\n")
        write(allowed / "config" / "good.xml", "<root enabled=\"true\"><item /></root>")
        write(allowed / "config" / "bad.xml", "<root><item></root>")
        write(allowed / "config" / "settings.yaml", "configured: false\n")
        write(allowed / "config" / "script.py", '{"configured": False}\n')
        write(outside / "config.json", '{"configured":false}')

        base_args = {"allowed_roots": [str(allowed)]}

        json_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "popup.json")})
        assert json_report["valid"] is True, json_report
        assert json_report["summary"]["topLevelKeyCount"] == 2, json_report
        assert json_report["suggestedTextPatchCount"] == 1, json_report
        assert json_report["suggestedTextPatches"][0]["oldText"] == '"configured":false', json_report
        assert json_report["suggestedTextPatches"][0]["newText"] == '"configured":true', json_report

        spaced_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "spaced.json")})
        assert spaced_report["suggestedTextPatches"][0]["oldText"] == '"is_configured": 0', spaced_report
        assert spaced_report["suggestedTextPatches"][0]["newText"] == '"is_configured": 1', spaced_report

        properties_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "mod.properties")})
        assert properties_report["valid"] is True, properties_report
        assert properties_report["format"] == "loose-key-value", properties_report
        assert properties_report["summary"]["keyValueCount"] == 2, properties_report
        assert properties_report["suggestedTextPatches"][0]["oldText"] == "configured=no", properties_report
        assert properties_report["suggestedTextPatches"][0]["newText"] == "configured=yes", properties_report

        ini_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "settings.ini")})
        assert ini_report["valid"] is True, ini_report
        assert ini_report["format"] == "ini", ini_report
        assert ini_report["summary"]["sectionCount"] == 1, ini_report

        xml_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "good.xml")})
        assert xml_report["valid"] is True, xml_report
        assert xml_report["summary"]["rootTag"] == "root", xml_report

        bad_xml = server.config_file_report({**base_args, "path": str(allowed / "config" / "bad.xml")})
        assert bad_xml["valid"] is False, bad_xml
        assert any(item["code"] == "config_parse_failed" for item in bad_xml["healthFindings"]), bad_xml

        yaml_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "settings.yaml")})
        assert yaml_report["valid"] is None, yaml_report
        assert "YAML" in yaml_report["summary"]["note"], yaml_report

        py_report = server.config_file_report({**base_args, "path": str(allowed / "config" / "script.py")})
        assert py_report["valid"] is None, py_report
        assert py_report["healthFindings"] == [], py_report
        assert py_report["suggestedTextPatches"] == [], py_report

        expect_tool_error(
            lambda: server.config_file_report({**base_args, "path": str(outside / "config.json")}),
            "outside detected Vortex/Skyrim roots",
        )

        repeated = allowed / "config" / "repeat.ini"
        write(repeated, "configured=false\nconfigured=false\n")
        expect_tool_error(
            lambda: server.apply_config_text_patch(
                {**base_args, "path": str(repeated), "old_text": "configured=false", "new_text": "configured=true"}
            ),
            "more than once",
        )
        multiple_dry_run = server.apply_config_text_patch(
            {
                **base_args,
                "path": str(repeated),
                "old_text": "configured=false",
                "new_text": "configured=true",
                "allow_multiple": True,
            }
        )
        assert multiple_dry_run["dryRun"] is True, multiple_dry_run
        assert multiple_dry_run["occurrences"] == 2, multiple_dry_run
        assert repeated.read_text(encoding="utf-8").count("configured=false") == 2, multiple_dry_run

    with temp_root(tmp_parent) as root:
        os.environ["USERPROFILE"] = str(root)
        os.environ["LOCALAPPDATA"] = str(root / "AppData" / "Local")
        os.environ["APPDATA"] = str(root / "AppData" / "Roaming")
        skyrim = root / "SteamLibrary" / "steamapps" / "common" / "Skyrim Special Edition"
        staging = root / "AppData" / "Roaming" / "Vortex" / "skyrimse" / "mods"
        my_games = root / "Documents" / "My Games" / "Skyrim Special Edition"
        write(skyrim / "SkyrimSE.exe")
        write(staging / "Popup UI Mod" / "config" / "popup.json", '{"configured":false}')
        log_path = my_games / "Logs" / "Script" / "Papyrus.0.log"
        write(log_path, '[05/04/2026] Error: File "Popup UI Mod\\config\\popup.json" was not configured properly\n')
        old_time = time.time() - 72 * 3600
        os.utime(log_path, (old_time, old_time))

        runtime_args = {
            "skyrim_dir": str(skyrim),
            "staging_dir": str(staging),
            "my_games_dir": str(my_games),
            "fresh_log_hours": 24,
            "max_runtime_log_files": 5,
            "max_runtime_findings": 10,
        }
        stale_report = server.skyrim_runtime_log_report(runtime_args)
        assert stale_report["freshLogStatus"]["fresh"] is False, stale_report
        assert stale_report["freshLogStatus"]["newestAgeHours"] >= 24, stale_report
        assert stale_report["issueGroupCount"] >= 1, stale_report
        assert stale_report["issueGroups"][0]["code"] == "config_not_configured", stale_report
        candidate = stale_report["configCandidates"][0]
        assert candidate["relativePath"] == "config/popup.json", stale_report
        assert candidate["validation"]["valid"] is True, stale_report
        assert candidate["validation"]["suggestedTextPatchCount"] == 1, stale_report

        no_validation = server.skyrim_runtime_log_report({**runtime_args, "validate_config_candidates": False})
        assert "validation" not in no_validation["configCandidates"][0], no_validation

        os.utime(log_path, None)
        fresh_report = server.skyrim_runtime_log_report(runtime_args)
        assert fresh_report["freshLogStatus"]["fresh"] is True, fresh_report

    print("Config/runtime regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
