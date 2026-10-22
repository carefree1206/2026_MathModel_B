"""Verify curated materials and the original frozen-program manifest; standard library only."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("all", "core"), default="all")
    parser.add_argument("--output", type=Path, help="Optional JSON verification report")
    args = parser.parse_args()
    manifest = read(ROOT / "docs" / "material_manifest.json")
    files = [r for r in manifest["files"] if args.scope == "all" or r["path"].startswith("支撑材料/")]
    failures = []
    seen = set()
    for row in files:
        name = row["path"]
        path = (ROOT / name).resolve()
        if ROOT not in path.parents or name in seen:
            failures.append({"path": name, "error": "Unsafe or duplicate manifest path"})
            continue
        seen.add(name)
        if not path.is_file():
            failures.append({"path": name, "error": "Missing file"})
        elif path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            with path.open("rb") as stream:
                is_pointer = stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1")
            error = "Git LFS pointer: run git lfs pull" if is_pointer else "Size or SHA-256 mismatch"
            failures.append({"path": name, "error": error})
    support = ROOT / "支撑材料"
    frozen = read(support / "数据" / "程序校验.json")["sha256"]
    for name, expected in frozen.items():
        path = support / name
        if not path.is_file() or digest(path) != expected:
            failures.append({"path": "支撑材料/" + name, "error": "Frozen-program mismatch"})
    result = dict(passed=not failures, scope=args.scope, materials_checked=len(files),
                  frozen_files_checked=len(frozen), failures=failures, network_requests=0)
    content = json.dumps(result, ensure_ascii=False, indent=2)
    print(content)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
