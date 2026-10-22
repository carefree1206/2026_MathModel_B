"""Run the frozen reproduction entry point, writing new results outside the archive."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "支撑材料" / "问题一至四_统一复现.py"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task", default="verify")
    parser.add_argument("--output", type=Path)
    args, forwarded = parser.parse_known_args()
    if "--help" in forwarded or "-h" in forwarded:
        command_args = ["--help"]
    else:
        output = (args.output.resolve() if args.output else
                  ROOT / "results" / (args.task + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")))
        command_args = ["--task", args.task, "--output", str(output)] + forwarded
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return subprocess.call([sys.executable, "-s", "-B", "-X", "utf8", str(ENTRY)] + command_args,
                           cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
