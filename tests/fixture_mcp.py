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
        write(skyrim / "skse64_1_5_97.dll")
        write(skyrim / "skse64_steam_loader.dll")
        write(skyrim / "SSEEdit.exe")
        write(data / "Skyrim.esm", plugin_bytes())
        write(data / "Update.esm", plugin_bytes("Skyrim.esm"))
        write(data / "MyMod.esp", plugin_bytes("Skyrim.esm"))
        write(data / "Scripts" / "skse.pex", "skse script")
        write(data / "SKSE" / "Plugins" / "versionlib-1-5-97-0.bin", "address library")
        write(data / "SKSE" / "Plugins" / "ExampleSksePlugin.dll", "dll")
        write(data / "Skyrim - Voices_en0.bsa", "voices")
        write(data / "Skyrim - Sounds.bsa", "sounds")
        write(staging / "Weather Mod" / "BrokenWeather.esp", plugin_bytes("MissingMaster.esm"))
        write(staging / "Weather Mod" / "scripts" / "shared.pex", "weather")
        write(staging / "Lighting Mod" / "scripts" / "shared.pex", "lighting")
        write(staging / "Lighting Mod" / "readme.txt", "Lighting tweaks")
        write(staging / "Lighting Mod" / "meta.ini", "modId=200\nfileId=777\nversion=1.0.0\n")
        write(staging / "Readme Pack" / "readme.txt", "Just a note file for cleanup testing")
        write(
            staging / "Whiterun Tavern Overhaul" / "WhiterunTavern.esp",
            plugin_bytes("Skyrim.esm") + b"Whiterun Bannered Mare tavern room bed furniture popup message",
        )
        write(staging / "Whiterun Tavern Overhaul" / "readme.txt", "Places a bed in the Whiterun Bannered Mare tavern room.")
        write(staging / "Popup UI Mod" / "interface" / "annoyingpopup.swf", "ui")
        write(staging / "Popup UI Mod" / "scripts" / "popupnotice.pex", "script")
        write(staging / "Popup UI Mod" / "config" / "popup.json", '{"warning":"notification after loading a save","configured":false}')
        write(staging / "Popup UI Mod" / "config" / "broken.ini", "[Popup]\nconfigured=false\n")
        write(staging / "Popup UI Mod" / "config" / "bad.json", '{"warning":')
        write(staging / "Popup UI Mod" / "SKSE" / "Plugins" / "PopupDll.dll", "dll")
        write(staging / "Popup UI Mod" / "readme.txt", "Shows a warning notification after loading a save. Configure the popup in MCM.")
        write(plugins_dir / "plugins.txt", "# comment\r\n*Skyrim.esm\r\n*MYMOD.ESP\r\n*MissingOnDisk.esp\r\n")
        write(my_games / "Skyrim.ini", "[Archive]\nbInvalidateOlderFiles=1\n")
        write(my_games / "SkyrimPrefs.ini", "[Launcher]\nbEnableFileSelection=1\n")
        write(
            my_games / "Logs" / "Script" / "Papyrus.0.log",
            '[05/04/2026 - 10:00:00PM] Error: File "Popup UI Mod\\config\\popup.json" was not configured properly\n',
        )
        write(my_games / "SKSE" / "CrashLogger.log", "ERROR: failed to load plugin PopupDll.dll\n")
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
        assert env["xedit"]["available"] is True, env
        assert not [issue for issue in env["issues"] if "SkyrimSE.exe" in issue], env
        setup = server.validate_setup(base_args)
        assert setup["ready"] is True, setup
        assert setup["environment"]["nexus_api"]["configured"] is False, setup
        assert "workflow_guide" in setup["toolGroups"]["alwaysAvailable"], setup
        assert "xedit_diagnostics_report" in setup["toolGroups"]["alwaysAvailable"], setup
        assert "vortex_reversible_automation_plan" in setup["toolGroups"]["alwaysAvailable"], setup
        assert "skse_runtime_doctor_report" in setup["toolGroups"]["alwaysAvailable"], setup

        original_windows_file_version = server.windows_file_version
        try:
            server.windows_file_version = lambda path: "1.6.1170.0" if path and Path(path).name == "SkyrimSE.exe" else None
            skse_doctor = server.skse_runtime_doctor_report(base_args)
            assert skse_doctor["summary"]["runtimeState"] == "blocked", skse_doctor
            assert skse_doctor["summary"]["skyrimRuntime"] == "1.6.1170", skse_doctor
            assert skse_doctor["summary"]["skseTargetRuntime"] == "1.5.97", skse_doctor
            assert any(finding["code"] == "skse_runtime_mismatch" for finding in skse_doctor["findings"]), skse_doctor
            server.windows_file_version = lambda path: "1.5.97.0" if path and Path(path).name == "SkyrimSE.exe" else None
            skse_doctor_match = server.skse_runtime_doctor_report(base_args)
            assert skse_doctor_match["summary"]["runtimeMatchesSkse"] is True, skse_doctor_match
            assert skse_doctor_match["summary"]["recommendedSkseBuild"] == "2.0.20", skse_doctor_match
            assert skse_doctor_match["summary"]["addressLibraryMatches"] is True, skse_doctor_match
        finally:
            server.windows_file_version = original_windows_file_version

        workflow = server.workflow_guide({"problem": "there is a bed outside the tavern room", "max_workflows": 1})
        assert workflow["workflows"][0]["key"] == "weird_object", workflow
        assert "in_game_issue_report" in workflow["workflows"][0]["tools"], workflow

        automation_workflow = server.workflow_guide({"problem": "delete unwanted mods and sort load order but make it reversible", "max_workflows": 1})
        assert automation_workflow["workflows"][0]["key"] == "risky_automation", automation_workflow

        xedit = server.xedit_diagnostics_report({**base_args, "form_id": "0100ABCD"})
        assert xedit["available"] is True, xedit
        assert xedit["pluginName"] == "MYMOD.ESP", xedit
        assert xedit["readOnly"] is True, xedit
        assert "xedit_inspection_script" in xedit["nextLeapTools"], xedit

        xedit_script = server.xedit_inspection_script(
            {
                **base_args,
                "description": "bed outside tavern room",
                "location": "Whiterun Bannered Mare",
                "object": "bed",
                "form_id": "0100ABCD",
                "output_path": str(root / "Reports" / "OpenClawSkyrimInspector.pas"),
                "report_path": str(root / "Reports" / "OpenClawSkyrimInspector.csv"),
                "max_records": 25,
            }
        )
        assert xedit_script["readOnly"] is True, xedit_script
        assert xedit_script["safety"]["readOnlyIntended"] is True, xedit_script
        assert Path(xedit_script["scriptPath"]).exists(), xedit_script
        script_text = Path(xedit_script["scriptPath"]).read_text(encoding="utf-8")
        assert "OpenClaw Skyrim inspector is read-only" in script_text, script_text
        assert "whiterun" in script_text, script_text
        assert "scriptValue" in script_text and "VMAD" in script_text, script_text
        assert "-script:" in xedit_script["xeditCommandPreview"], xedit_script

        write(
            Path(xedit_script["reportPath"]),
            'sourcePlugin,signature,formId,editorId,name,full,cell,base,model,script,matchedTerm,fullPath\n'
            '"WhiterunTavern.esp","REFR","0100ABCD","TavernBedRef","[REFR:0100ABCD]","Bed","WhiterunBanneredMare","CommonBed01","","","bed","Full\\Path"\n'
            '"WhiterunTavern.esp","CELL","01000AAA","WhiterunBanneredMare","Cell","","","","","","Whiterun","Full\\Cell"\n',
        )
        xedit_result = server.xedit_inspection_result_report(
            {
                **base_args,
                "report_path": xedit_script["reportPath"],
                "allowed_roots": [str(root)],
            }
        )
        assert xedit_result["rowCount"] == 2, xedit_result
        assert xedit_result["topPlugins"][0]["value"] == "WhiterunTavern.esp", xedit_result
        assert xedit_result["topSignatures"][0]["value"] in {"CELL", "REFR"}, xedit_result
        assert xedit_result["topIssueKinds"][0]["value"] == "placed_object", xedit_result
        assert xedit_result["rows"][0]["interpretation"]["meaning"] == "placed reference/object", xedit_result

        assert server.compact_for_log({"nexus_api_key": "secret"})["nexus_api_key"] == "<redacted>"
        previous_nexus_key = os.environ.pop("NEXUS_MODS_API_KEY", None)
        try:
            assert server.nexus_validate_key({})["available"] is False
            os.environ["NEXUS_MODS_API_KEY"] = "fixture-secret"
            assert "fixture-secret" not in server.redact_text("token=fixture-secret")
        finally:
            if previous_nexus_key is None:
                os.environ.pop("NEXUS_MODS_API_KEY", None)
            else:
                os.environ["NEXUS_MODS_API_KEY"] = previous_nexus_key

        original_nexus_http_get = server.nexus_http_get

        def fake_nexus_http_get(args, path, params=None, cache_namespace=None):
            if path == "/users/validate":
                return {
                    "ok": True,
                    "available": True,
                    "cacheHit": False,
                    "statusCode": 200,
                    "data": {"user_id": 42, "name": "tester", "is_premium": True, "is_supporter": False},
                    "rateLimit": {"dailyRemaining": 999, "hourlyRemaining": 99},
                }
            if path.endswith("/mods/200/files/777"):
                return {
                    "ok": True,
                    "available": True,
                    "cacheHit": False,
                    "statusCode": 200,
                    "data": {"file_id": 777, "name": "Main File", "file_name": "lighting.7z", "version": "1.1.0", "size": 1234},
                    "rateLimit": {},
                }
            if path.endswith("/mods/200/files"):
                return {
                    "ok": True,
                    "available": True,
                    "cacheHit": False,
                    "statusCode": 200,
                    "data": {"files": [{"file_id": 777, "name": "Main File", "file_name": "lighting.7z", "version": "1.1.0"}]},
                    "rateLimit": {},
                }
            if path.endswith("/mods/200"):
                return {
                    "ok": True,
                    "available": True,
                    "cacheHit": False,
                    "statusCode": 200,
                    "data": {
                        "mod_id": 200,
                        "name": "Official Lighting Mod",
                        "summary": "Improves interior lighting.",
                        "version": "1.1.0",
                        "author": "Fixture Author",
                        "category_name": "Visuals",
                        "status": "published",
                        "available": True,
                    },
                    "rateLimit": {},
                }
            if "md5_search" in path:
                return {
                    "ok": True,
                    "available": True,
                    "cacheHit": False,
                    "statusCode": 200,
                    "data": [{"mod_id": 200, "file_id": 777, "name": "Official Lighting Mod", "file_name": "lighting.7z"}],
                    "rateLimit": {},
                }
            return {"ok": False, "available": False, "error": f"unexpected path {path}", "statusCode": 404}

        server.nexus_http_get = fake_nexus_http_get
        try:
            validated_key = server.nexus_validate_key({"nexus_api_key": "secret"})
            assert validated_key["available"] is True, validated_key
            assert validated_key["user"]["name"] == "tester", validated_key
            mod_lookup = server.nexus_mod_lookup({"nexus_api_key": "secret", "mod_id": 200})
            assert mod_lookup["mod"]["name"] == "Official Lighting Mod", mod_lookup
            mod_files = server.nexus_mod_files({"nexus_api_key": "secret", "mod_id": 200})
            assert mod_files["fileCount"] == 1, mod_files
            file_info = server.nexus_file_info({"nexus_api_key": "secret", "mod_id": 200, "file_id": 777})
            assert file_info["file"]["fileName"] == "lighting.7z", file_info
            md5_lookup = server.nexus_file_by_md5({"nexus_api_key": "secret", "md5": "0" * 32})
            assert md5_lookup["matchCount"] == 1, md5_lookup
            nxm = server.nexus_parse_nxm_link(
                {"nxm_link": "nxm://skyrimspecialedition/mods/200/files/777?key=abc&expires=9999999999"}
            )
            assert nxm["gameDomain"] == "skyrimspecialedition", nxm
            assert nxm["modId"] == 200, nxm
            assert nxm["fileId"] == 777, nxm
            assert nxm["hasDownloadKey"] is True, nxm
            update_report = server.nexus_update_report(
                {**base_args, "nexus_api_key": "secret", "include_profile_state": False, "max_mods": 10}
            )
            assert update_report["available"] is True, update_report
            assert update_report["staleCount"] == 1, update_report
            assert update_report["staleMods"][0]["mod"] == "Lighting Mod", update_report
        finally:
            server.nexus_http_get = original_nexus_http_get

        inventory = server.inventory_mods({**base_args, "include_files": True})
        assert inventory["modCount"] == 5, inventory
        cached_inventory = server.inventory_mods({**base_args, "include_files": True, "include_scan_cache_status": True})
        assert any(mod.get("_cache", {}).get("hit") for mod in cached_inventory["mods"]), cached_inventory
        assert cached_inventory["scanCache"]["entryCount"] >= inventory["modCount"], cached_inventory

        conflicts = server.analyze_conflicts(base_args)
        assert any(item["relativePath"] == "scripts/shared.pex" for item in conflicts["conflicts"]), conflicts
        shared_conflict = next(item for item in conflicts["conflicts"] if item["relativePath"] == "scripts/shared.pex")
        assert shared_conflict["explanation"]["risk"] == "high", shared_conflict
        assert conflicts["riskSummary"]["high"] >= 1, conflicts

        plugins = server.plugin_report(base_args)
        assert "MissingOnDisk.esp" in plugins["missingEnabledPlugins"], plugins
        assert any(item["missingMaster"] == "MissingMaster.esm" for item in plugins["missingMasters"]), plugins

        original_load_profile_state_for_deployment = server.load_vortex_profile_state

        def fake_deployment_profile_state(args, include_mods=False):
            return {
                "gameId": "skyrimse",
                "vortex_exe": str(vortex_exe),
                "profiles": {
                    "deploy-source": {
                        "id": "deploy-source",
                        "name": "Deployment Source",
                        "gameId": "skyrimse",
                        "lastActivated": 10,
                        "modState": {
                            "lighting": {"enabled": True},
                            "weather": {"enabled": True},
                        },
                    }
                },
                "allProfiles": {},
                "mods": {
                    "lighting": {"attributes": {"name": "Lighting Mod", "installationPath": "Lighting Mod"}},
                    "weather": {"attributes": {"name": "Weather Mod", "installationPath": "Weather Mod"}},
                },
                "activeProfileId": "deploy-source",
                "activeFromSettings": "deploy-source",
                "activeFromLastActivated": "deploy-source",
                "rawPaths": [],
            }

        server.load_vortex_profile_state = fake_deployment_profile_state
        try:
            automation = server.vortex_reversible_automation_plan(
                {
                    **base_args,
                    "request": "delete weather mod and sort load order safely",
                    "disable_mod_ids": ["weather"],
                    "include_profile_state": False,
                }
            )
            assert automation["dryRunOnly"] is True, automation
            assert automation["summary"]["profileCloneRequired"] is True, automation
            assert any(plan["action"] == "delete_or_uninstall_mods" for plan in automation["actionPlans"]), automation
            assert any(step["tool"] == "vortex_safe_profile_fix" for step in automation["planSteps"]), automation
            doctor = server.deployment_doctor_report({**base_args, "deployment_probe_files_per_mod": 3})
            assert doctor["summary"]["profileToSkyrimLinked"] is False, doctor
            assert doctor["summary"]["deploymentState"] in {"blocked_missing_masters", "needs_deploy"}, doctor
            assert doctor["summary"]["sampleMissingModCount"] >= 1, doctor
            assert any(check["key"] == "profile_plugins_deployed" and check["status"] == "fail" for check in doctor["checks"]), doctor
            assert any(finding["code"] == "sampled_enabled_mod_files_not_deployed" for finding in doctor["findings"]), doctor
            assert any(finding["code"] == "missing_plugin_masters" for finding in doctor["findings"]), doctor
            assert doctor["sections"]["deployment"]["sampledEnabledModFilesMissingFromData"], doctor
            doctor_md = root / "Reports" / "deployment-doctor.md"
            baseline_path = root / "Reports" / "deployment-doctor-baseline.json"
            baseline = json.loads(json.dumps(doctor))
            baseline["summary"]["deploymentState"] = "linked"
            for check in baseline["checks"]:
                if check.get("key") == "profile_plugins_deployed":
                    check["status"] = "pass"
                    check["message"] = "Baseline thought plugins were deployed."
            write(baseline_path, json.dumps(baseline))
            doctor_with_baseline = server.deployment_doctor_report(
                {
                    **base_args,
                    "deployment_probe_files_per_mod": 3,
                    "baseline_path": str(baseline_path),
                    "output_path": str(doctor_md),
                }
            )
            assert doctor_with_baseline["output_path"] == str(doctor_md), doctor_with_baseline
            assert doctor_md.exists(), doctor_with_baseline
            doctor_md_text = doctor_md.read_text(encoding="utf-8")
            assert "Baseline Comparison" in doctor_md_text, doctor_md_text
            assert doctor_with_baseline["baselineComparison"]["available"] is True, doctor_with_baseline
            assert doctor_with_baseline["baselineComparison"]["stateChanged"] is True, doctor_with_baseline
            assert any(change["key"] == "profile_plugins_deployed" for change in doctor_with_baseline["baselineComparison"]["changedChecks"]), doctor_with_baseline
            launch_md = root / "Reports" / "launch-doctor.md"
            launch = server.skyrim_launch_doctor_report(
                {
                    **base_args,
                    "deployment_probe_files_per_mod": 3,
                    "output_path": str(launch_md),
                }
            )
            assert launch["readOnly"] is True, launch
            assert launch["summary"]["recommendedLaunchRoute"] == "fix_deployment_first", launch
            assert launch["summary"]["skseReady"] is True, launch
            assert launch["commandPreview"]["fallbackExecutable"].endswith("SkyrimSE.exe"), launch
            assert launch_md.exists(), launch
            assert "Launch Doctor" in launch_md.read_text(encoding="utf-8"), launch
        finally:
            server.load_vortex_profile_state = original_load_profile_state_for_deployment

        collection_match = server.collection_local_match_report(
            {
                **base_args,
                "include_profile_state": False,
                "collection_manifest_json": json.dumps(
                    {"mods": [{"modId": 200, "fileId": 777}, {"mod_id": 999, "file_id": 1}]}
                ),
            }
        )
        assert collection_match["manifestReferenceCount"] == 2, collection_match
        assert 999 in collection_match["missingModIds"], collection_match
        assert 200 not in collection_match["missingModIds"], collection_match
        assert collection_match["filePairMismatchCount"] == 1, collection_match

        original_vortex_state_get = server.vortex_state_get

        def fake_vortex_state_get(paths, vortex_exe_override=None, timeout_seconds=60):
            return {
                "vortex_exe": str(vortex_exe),
                "state": {
                    "persistent": {
                        "collections": {
                            "abc": {
                                "id": "abc",
                                "name": "Fixture Collection",
                                "revision": 1,
                                "mods": [{"modId": 200, "fileId": 777}],
                            }
                        },
                        "mods": {
                            "skyrimse": {
                                "lighting": {
                                    "attributes": {
                                        "name": "Lighting Mod",
                                        "collectionId": "abc",
                                        "collectionRevision": 1,
                                    }
                                }
                            }
                        },
                        "profiles": {},
                    },
                    "settings": {"collections": {}},
                },
                "parsed": {"values": {}},
            }

        server.vortex_state_get = fake_vortex_state_get
        try:
            collection_report = server.vortex_collection_report(base_args)
            assert collection_report["available"] is True, collection_report
            assert collection_report["collectionStateCount"] >= 1, collection_report
            assert collection_report["modCollectionMarkerCount"] == 1, collection_report
        finally:
            server.vortex_state_get = original_vortex_state_get

        original_load_profile_state = server.load_vortex_profile_state
        original_vortex_state_set = server.vortex_state_set
        applied_profile_changes = []
        include_mods_calls = []

        def fake_load_profile_state(args, include_mods=False):
            include_mods_calls.append(include_mods)
            return {
                "gameId": "skyrimse",
                "vortex_exe": "Vortex.exe",
                "profiles": {
                    "source": {
                        "id": "source",
                        "name": "Original Profile",
                        "gameId": "skyrimse",
                        "lastActivated": 1,
                        "modState": {
                            "bad-mod": {"enabled": True, "enabledTime": 1},
                            "off-mod": {"enabled": False},
                            "keep-mod": {"enabled": True},
                        },
                    }
                },
                "allProfiles": {},
                "mods": {
                    "bad-mod": {"attributes": {"name": "Bad Mod"}},
                    "off-mod": {"attributes": {"name": "Off Mod"}},
                    "keep-mod": {"attributes": {"name": "Keep Mod"}},
                },
                "activeProfileId": "source",
                "activeFromSettings": "source",
                "activeFromLastActivated": "source",
                "rawPaths": [],
            }

        def fake_vortex_state_set(changes, vortex_exe_override=None, timeout_seconds=60, allow_running_vortex=False):
            applied_profile_changes.extend(changes)
            return {"vortex_exe": "Vortex.exe", "changeCount": len(changes), "batchCount": 1, "calls": []}

        server.load_vortex_profile_state = fake_load_profile_state
        server.vortex_state_set = fake_vortex_state_set
        try:
            safe_fix_preview = server.vortex_safe_profile_fix(
                {
                    "source_profile_id": "source",
                    "new_profile_id": "clone",
                    "new_name": "Fixed Clone",
                    "disable_mod_ids": ["bad-mod"],
                    "enable_mod_ids": ["off-mod"],
                }
            )
            assert safe_fix_preview["dryRun"] is True, safe_fix_preview
            assert safe_fix_preview["cloneOnly"] is True, safe_fix_preview
            assert safe_fix_preview["sourceProfileModified"] is False, safe_fix_preview
            assert safe_fix_preview["includeModMetadata"] is False, safe_fix_preview
            assert safe_fix_preview["disableModIds"] == ["bad-mod"], safe_fix_preview
            assert safe_fix_preview["enableModIds"] == ["off-mod"], safe_fix_preview
            safe_fix_apply = server.vortex_safe_profile_fix(
                {
                    "source_profile_id": "source",
                    "new_profile_id": "clone-applied",
                    "new_name": "Fixed Clone Applied",
                    "disable_mod_ids": ["bad-mod"],
                    "apply": True,
                    "backup_before_apply": False,
                }
            )
            assert safe_fix_apply["applied"] is True, safe_fix_apply
            assert applied_profile_changes, safe_fix_apply
            assert all(str(change["path"]).startswith("persistent.profiles.clone-applied") for change in applied_profile_changes), applied_profile_changes
            assert include_mods_calls and all(call is False for call in include_mods_calls), include_mods_calls
        finally:
            server.load_vortex_profile_state = original_load_profile_state
            server.vortex_state_set = original_vortex_state_set

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

        case_packet = server.skyrim_issue_case_packet(
            {
                **base_args,
                "description": "There is a bed outside the tavern room and it is messing things up.",
                "location": "Whiterun Bannered Mare",
                "object": "bed",
                "form_id": "0100ABCD",
                "base_object": "CommonBed01",
                "cell": "WhiterunBanneredMare",
                "include_profile_state": False,
                "case_dir": str(root / "Reports" / "CaseBed"),
                "include_runtime_logs": False,
                "max_records": 25,
            }
        )
        assert case_packet["readOnly"] is True, case_packet
        assert case_packet["dryRunOnly"] is True, case_packet
        assert case_packet["candidateCount"] >= 1, case_packet
        assert case_packet["topCandidate"]["mod"] == "Whiterun Tavern Overhaul", case_packet
        assert case_packet["xeditPluginHint"] == "MYMOD.ESP", case_packet
        assert Path(case_packet["markdownPath"]).exists(), case_packet
        assert Path(case_packet["jsonPath"]).exists(), case_packet
        assert Path(case_packet["xeditScriptPath"]).exists(), case_packet
        case_markdown = Path(case_packet["markdownPath"]).read_text(encoding="utf-8")
        assert "Skyrim Issue Case Packet" in case_markdown, case_markdown
        assert "Whiterun Tavern Overhaul" in case_markdown, case_markdown
        assert not case_packet["errors"], case_packet

        write(
            Path(case_packet["xeditCsvPath"]),
            'sourcePlugin,signature,formId,editorId,name,full,cell,base,model,script,matchedTerm,fullPath\n'
            '"WhiterunTavern.esp","REFR","0100ABCD","TavernBedRef","[REFR:0100ABCD]","Bed","WhiterunBanneredMare","CommonBed01","","","bed","Full\\Path"\n',
        )
        case_status = server.skyrim_issue_case_status(
            {
                **base_args,
                "case_dir": case_packet["caseDir"],
                "max_preview_rows": 5,
            }
        )
        assert case_status["readOnly"] is True, case_status
        assert case_status["dryRunOnly"] is True, case_status
        assert case_status["state"] == "has_xedit_results", case_status
        assert case_status["rowCount"] == 1, case_status
        assert case_status["candidatePlugins"] == ["WhiterunTavern.esp"], case_status
        assert Path(case_status["statusPath"]).exists(), case_status
        status_markdown = Path(case_status["statusPath"]).read_text(encoding="utf-8")
        assert "Skyrim Issue Case Status" in status_markdown, status_markdown
        assert "WhiterunTavern.esp" in status_markdown, status_markdown

        case_note = server.skyrim_issue_case_note(
            {
                "case_dir": case_packet["caseDir"],
                "kind": "test",
                "note": "Disabled nothing yet; xEdit evidence points at WhiterunTavern.esp.",
                "result": "observed",
                "next_action": "plan cloned-profile test",
            }
        )
        assert Path(case_note["notesPath"]).exists(), case_note
        assert "xEdit evidence" in Path(case_note["notesPath"]).read_text(encoding="utf-8"), case_note

        experiment = server.skyrim_safe_experiment_plan(
            {
                "case_dir": case_packet["caseDir"],
                "target_mod": "Whiterun Tavern Overhaul",
                "target_mod_id": "whiterun-tavern-overhaul",
                "test_profile_name": "OpenClaw Safe Test",
            }
        )
        assert experiment["dryRunOnly"] is True, experiment
        assert experiment["target"]["vortexModId"] == "whiterun-tavern-overhaul", experiment
        assert any(call["tool"] == "vortex_safe_profile_fix" for call in experiment["dryRunToolCalls"]), experiment
        assert Path(experiment["planPath"]).exists(), experiment

        what_now = server.skyrim_case_what_now({"case_dir": case_packet["caseDir"]})
        assert what_now["recommendation"].startswith("Use the xEdit evidence"), what_now
        assert Path(what_now["outputPath"]).exists(), what_now

        live_bridge = server.skyrim_live_bridge_status({"case_dir": case_packet["caseDir"]})
        assert live_bridge["canSeeRunningGameNow"] is False, live_bridge
        assert live_bridge["capabilities"]["caseFolderIntegration"]["implemented"] is True, live_bridge

        evidence = server.skyrim_case_evidence_import(
            {
                "case_dir": case_packet["caseDir"],
                "evidence_type": "popup_ocr",
                "ocr_text": "Bannered Mare bed warning popup",
                "reference_form_id": "0100ABCD",
                "base_form_id": "00001234",
                "cell": "WhiterunBanneredMare",
                "object": "bed",
                "confidence": "captured",
            }
        )
        assert Path(evidence["evidencePath"]).exists(), evidence
        assert evidence["entry"]["suggestedToolArgs"]["xedit_diagnostics_report"]["form_id"] == "0100ABCD", evidence
        assert "popup" in Path(evidence["evidencePath"]).read_text(encoding="utf-8").lower(), evidence

        inbox_dir = Path(case_packet["caseDir"]) / "incoming"
        write(
            inbox_dir / "popup-capture.json",
            json.dumps(
                {
                    "evidence_type": "popup_ocr",
                    "ocr_text": "MCM warning file was not configured properly",
                    "reference_form_id": "0100ABCD",
                    "cell": "WhiterunBanneredMare",
                    "object": "bed",
                    "confidence": "fixture",
                }
            ),
        )
        inbox_import = server.skyrim_case_inbox_import({"case_dir": case_packet["caseDir"], "max_files": 10})
        assert inbox_import["importedCount"] == 1, inbox_import
        assert inbox_import["skippedDuplicateCount"] == 0, inbox_import
        assert Path(inbox_import["evidenceIndexPath"]).exists(), inbox_import
        evidence_index = json.loads(Path(inbox_import["evidenceIndexPath"]).read_text(encoding="utf-8"))
        assert len(evidence_index["files"]) == 1, evidence_index
        duplicate_inbox = server.skyrim_case_inbox_import({"case_dir": case_packet["caseDir"], "max_files": 10})
        assert duplicate_inbox["importedCount"] == 0, duplicate_inbox
        assert duplicate_inbox["skippedDuplicateCount"] == 1, duplicate_inbox

        bundle = server.skyrim_case_bundle(
            {
                "case_dir": case_packet["caseDir"],
                "output_path": str(root / "Reports" / "CaseBed.zip"),
            }
        )
        assert Path(bundle["zipPath"]).exists(), bundle
        with zipfile.ZipFile(bundle["zipPath"]) as archive:
            names = set(archive.namelist())
        assert "issue-case.md" in names, names
        assert "live-evidence.jsonl" in names, names
        assert "live-evidence-index.json" in names, names

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

        runtime_logs = server.skyrim_runtime_log_report(
            {
                **base_args,
                "description": "popup says file was not configured properly",
                "max_runtime_log_files": 5,
                "max_runtime_findings": 10,
            }
        )
        assert runtime_logs["available"] is True, runtime_logs
        assert runtime_logs["freshLogStatus"]["fresh"] is True, runtime_logs
        assert runtime_logs["findingCount"] >= 1, runtime_logs
        assert runtime_logs["issueGroupCount"] >= 1, runtime_logs
        assert any(group["code"] == "config_not_configured" for group in runtime_logs["issueGroups"]), runtime_logs
        assert any("configured properly" in item["line"] for item in runtime_logs["findings"]), runtime_logs
        assert any(
            match["mod"] == "Popup UI Mod"
            for item in runtime_logs["findings"]
            for match in item.get("stagedMatches", [])
        ), runtime_logs
        assert any(candidate["relativePath"] == "config/popup.json" for candidate in runtime_logs["configCandidates"]), runtime_logs
        popup_candidate = next(candidate for candidate in runtime_logs["configCandidates"] if candidate["relativePath"] == "config/popup.json")
        assert popup_candidate["validation"]["valid"] is True, runtime_logs
        assert any(item["code"] == "configured_flag_false" for item in popup_candidate["validation"]["healthFindings"]), runtime_logs
        assert popup_candidate["validation"]["suggestedTextPatchCount"] >= 1, runtime_logs

        config_report = server.config_file_report({**base_args, "path": str(staging / "Popup UI Mod" / "config" / "popup.json")})
        assert config_report["valid"] is True, config_report
        assert config_report["summary"]["topLevelKeyCount"] == 2, config_report
        assert any(item["code"] == "configured_flag_false" for item in config_report["healthFindings"]), config_report
        assert config_report["suggestedTextPatches"][0]["oldText"] == '"configured":false', config_report
        assert config_report["suggestedTextPatches"][0]["newText"] == '"configured":true', config_report

        loose_ini = server.config_file_report({**base_args, "path": str(staging / "Lighting Mod" / "meta.ini")})
        assert loose_ini["valid"] is True, loose_ini
        assert loose_ini["format"] == "loose-key-value", loose_ini
        assert loose_ini["summary"]["keyValueCount"] == 3, loose_ini

        bad_config = server.config_file_report({**base_args, "path": str(staging / "Popup UI Mod" / "config" / "bad.json")})
        assert bad_config["valid"] is False, bad_config
        assert any(item["code"] == "config_parse_failed" for item in bad_config["healthFindings"]), bad_config

        config_path = staging / "Popup UI Mod" / "config" / "broken.ini"
        patch_dry = server.apply_config_text_patch(
            {
                **base_args,
                "path": str(config_path),
                "old_text": "configured=false",
                "new_text": "configured=true",
            }
        )
        assert patch_dry["dryRun"] is True, patch_dry
        assert patch_dry["wouldChange"] is True, patch_dry
        assert "configured=false" in config_path.read_text(encoding="utf-8"), patch_dry
        patch_apply = server.apply_config_text_patch(
            {
                **base_args,
                "path": str(config_path),
                "old_text": "configured=false",
                "new_text": "configured=true",
                "apply": True,
            }
        )
        assert patch_apply["changed"] is True, patch_apply
        assert Path(patch_apply["backup"]).exists(), patch_apply
        assert "configured=true" in config_path.read_text(encoding="utf-8"), patch_apply

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
        assert "Skyrim Runtime Logs" in safe_text
        assert str(root) not in safe_text
        assert str(root) not in safe_payload_text
        assert "inGameIssue" in safe["sections"], safe
        assert "skyrimRuntimeLogs" in safe["sections"], safe
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
        assert "skyrimRuntimeLogs" in payload
        assert payload["skyrimRuntimeLogs"]["findingCount"] >= 1, payload

        with zipfile.ZipFile(bundle["zip_path"]) as archive:
            names = set(archive.namelist())
            assert "README-BUG-REPORT.txt" in names, names
            assert "bundle.json" in names, names
            assert any(name.startswith("logs/") for name in names), names

    print("Fixture MCP tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
