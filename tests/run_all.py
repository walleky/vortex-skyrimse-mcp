#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run_step(name: str, command: list[str], cwd: Path) -> None:
    print(f"\n== {name} ==", flush=True)
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=str(cwd), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Vortex Skyrim SE MCP local test suite.")
    parser.add_argument("--skip-powershell", action="store_true", help="Skip PowerShell helper parsing/menu tests.")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    py = sys.executable
    py_files = [
        "server.py",
        "tests/smoke_mcp.py",
        "tests/fixture_mcp.py",
        "tests/config_runtime_mcp.py",
        "tests/run_all.py",
    ]
    run_step("Compile Python", [py, "-m", "py_compile", *py_files], repo)
    run_step("Server self-test", [py, "server.py", "--self-test"], repo)
    run_step("MCP stdio smoke test", [py, "tests/smoke_mcp.py"], repo)
    run_step("Fixture integration tests", [py, "tests/fixture_mcp.py"], repo)
    run_step("Config/runtime regression tests", [py, "tests/config_runtime_mcp.py"], repo)

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if args.skip_powershell:
        print("\n== PowerShell helper tests skipped by flag ==", flush=True)
    elif shell:
        if Path(shell).name.lower().startswith("powershell"):
            command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tests/check_powershell.ps1"]
        else:
            command = [shell, "-NoProfile", "-File", "tests/check_powershell.ps1"]
        run_step("PowerShell helper tests", command, repo)
    else:
        print("\n== PowerShell helper tests skipped: pwsh/powershell not found ==", flush=True)

    print("\nAll requested tests passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
