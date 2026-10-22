"""Start the delivered local GUI with new runs stored under results/gui."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    args = sys.argv[1:]
    if not any(a.split("=", 1)[0] in ("--results-dir", "--output-root") for a in args):
        args += ["--results-dir", str(ROOT / "results" / "gui")]
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return subprocess.call([sys.executable, "-s", "-B", "-X", "utf8",
                            str(ROOT / "支撑材料" / "问题三四_交互模拟终端.py")] + args,
                           cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
