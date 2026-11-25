"""Install the per-user Windows stdio bridge; no elevation or game access required."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys


SOURCE = Path(__file__).resolve().parent
MODULES = ("server.py","window.py","panel.py","controller.py","capture_window.py","card_drag.py")


def registry_entry(cli):
    # Capture locally; never print the user's full registry.
    res = subprocess.run([cli,"mcp","list","--json"],capture_output=True,encoding="utf-8",check=True)
    return next((e for e in json.loads(res.stdout) if e["name"] == "qqspeed-editor"),None)


def install(args):
    if os.name != "nt" or sys.version_info[:2] != (3,12) or struct.calcsize("P") != 8:
        raise ValueError("The live bridge is tested on Windows with 64-bit Python 3.12")
    target = (args.install_dir or Path(os.environ["LOCALAPPDATA"])/"qqspeed-editor-mcp").resolve()
    if target == SOURCE or target in SOURCE.parents or target == Path(target.anchor):
        raise ValueError("Choose a private target directory separate from the skill")
    for name in (*MODULES,"requirements.txt"):
        if not (SOURCE/name).is_file():
            raise ValueError(f"Missing bridge source {name}")
    cli = None if args.no_register else shutil.which("codex")
    if not args.no_register and not cli:
        raise ValueError("Codex CLI is required for registration. Use --no-register for the runtime alone.")
    if args.check_only:
        print(f"Prerequisites found. Target {target}")
        return
    py = target/"venv/Scripts/python.exe"
    server = target/"server.py"
    existing = registry_entry(cli) if cli else None
    if existing is not None:
        data = subprocess.run([cli,"mcp","get","qqspeed-editor","--json"],capture_output=True,encoding="utf-8",check=True)
        cfg = json.loads(data.stdout)["transport"]
        params = cfg.get("args",[])
        if (not cfg.get("command") or Path(cfg["command"]).resolve() != py or len(params)!=3 or
                params[:2] != ["-X","utf8"] or Path(params[2]).resolve() != server):
            raise ValueError("Existing qqspeed-editor registration points elsewhere. Inspect it or use --no-register.")
    if not py.is_file():
        subprocess.run([sys.executable,"-m","venv",target/"venv"],check=True)
    subprocess.run([py,"-c","import struct,sys;sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"],check=True)
    subprocess.run([py,"-m","pip","--disable-pip-version-check","install","-r",SOURCE/"requirements.txt"],check=True)
    # RapidOCR uses OpenCV headless. Keep just the WGC binding in an isolated import directory.
    subprocess.run([py,"-m","pip","--disable-pip-version-check","install","--no-deps","--upgrade",
                    "--target",target/"capture-binding","windows-capture==2.0.1"],check=True)
    for name in MODULES:
        shutil.copyfile(SOURCE/name,target/name)
    if cli and existing is None:
        subprocess.run([cli,"mcp","add","qqspeed-editor","--",py,"-X","utf8",server],check=True)
    print(f"Installed at {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir",type=Path)
    parser.add_argument("--check-only",action="store_true")
    parser.add_argument("--no-register",action="store_true")
    try:
        install(parser.parse_args())
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
