"""在相同 M020 和相同场景上比较 Q3 的 1+6、1+7、1+8 巡检布局。"""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import argparse
import gzip
import hashlib
import json
import math
import platform
import sys
import time


HERE = Path(__file__).resolve().parent / '数据/问题三巡检比较'


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_runtime(support):
    # 使用支撑材料中的正式入口；入口会逐文件核对冻结源码和参数。
    sys.path.insert(0, str(Path(support).resolve()))
    import 问题三四_正式算法与参数入口 as runtime
    if Path(runtime.__file__).resolve().parent != Path(support).resolve():
        raise RuntimeError("加载了其他目录的 runtime，请在新进程运行")
    selected = runtime.load("q3")
    if selected["algorithm"] != "m020":
        raise ValueError("本实验要求采用配置仍为 M020")
    return runtime, selected


def worker(job):
    support, case, variant, out = job
    load_runtime(support)
    from 问题三四_场景求解与核验 import safe_run_one
    # evaluator 原样执行完整任务，并检查计时、真值全清、定位与终止证据。
    return safe_run_one((case, variant, out, False))


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(rows, layouts):
    baseline = {r["case_id"]: r for r in rows if r["variant"] == "ring6"}
    summary, pairs, strata = [], [], []
    cost_keys = ("move_m", "move_s", "measure_s", "switch_s", "optical_s", "laser_s", "measures")
    for layout in layouts:
        group = [r for r in rows if r["variant"] == layout["name"]]
        valid = bool(group) and all(r["passed"] and r["per_source_s"] is not None for r in group)
        if not valid:
            raise RuntimeError("存在未通过的场景，请先检查逐场证据，不可删除失败后计算均值")
        values = [r["per_source_s"] for r in group]
        changes = []
        for row in group:
            base = baseline[row["case_id"]]
            change = 100 * (row["per_source_s"] / base["per_source_s"] - 1)
            changes.append(change)
            pairs.append(dict(case_id=row["case_id"], variant=layout["name"], source_count=row["source_count"],
                base_per_source_s=base["per_source_s"], actual_per_source_s=row["per_source_s"], relative_change_percent=change,
                delta_per_source_s=row["per_source_s"] - base["per_source_s"]))
        summary.append(dict(**layout, cases=len(group), passed=True,
            source_count=sum(r["source_count"] for r in group), cleared_count=sum(r["cleared_count"] for r in group),
            mean_per_source_s=sum(values) / len(values), median_per_source_s=percentile(values, .5),
            p90_per_source_s=percentile(values, .9), max_per_source_s=max(values),
            tail10_per_source_s=sum(sorted(values)[-math.ceil(.1 * len(values)):]) / math.ceil(.1 * len(values)),
            faster_vs_ring6=sum(c < -1e-8 for c in changes), equal_vs_ring6=sum(abs(c) <= 1e-8 for c in changes),
            slower_vs_ring6=sum(c > 1e-8 for c in changes), worst_relative_change_percent=max(changes),
            mean_costs_per_case={key: sum(r["costs"][key] for r in group) / len(group) for key in cost_keys},
            mean_costs_per_source={key: sum(r["costs"][key] / r["source_count"] for r in group) / len(group) for key in cost_keys}))
        for source_n in range(10, 17):
            part = [r for r in group if r["source_count"] == source_n]
            strata.append(dict(variant=layout["name"], source_count=source_n, cases=len(part),
                mean_per_source_s=sum(r["per_source_s"] for r in part) / len(part)))
    return summary, pairs, strata


def run(args):
    if platform.python_version() != "3.9.13":
        raise RuntimeError("逐动作一致性核验使用 Python 3.9.13")
    if not 1 <= args.workers <= 3:
        raise ValueError("workers 应为 1、2 或 3")
    support = args.support.resolve()
    runtime, selected = load_runtime(support)
    frozen = read(HERE / "frozen_inputs.json")
    cases = frozen["cases"]
    if len(cases) != 84 or len({c["case_id"] for c in cases}) != 84:
        raise ValueError("比较必须保留完整的 84 场固定输入")
    if any(c["problem"] != "q3" for c in cases):
        raise ValueError("本任务只比较 Q3")
    if any(sum(len(c["sources"]) == n for c in cases) != 12 for n in range(10, 17)):
        raise ValueError("每个源数分层应恰有 12 场")
    if selected["settings"] != frozen["m020_settings"]:
        raise ValueError("当前正式 M020 参数与登记时不同，不能直接拼接结果")
    if digest(support / "数据/参数/问题三四_原交付程序清单.json") != frozen["runtime_manifest_sha256"]:
        raise ValueError("冻结求解源码版本不同")
    # 随包的逐场存档是复现目标；墙钟耗时不参与一致性判定。
    expected_path = HERE / "results/rows.json"
    expected_rows = read(expected_path)
    expected_map = {(r["case_id"], r["variant"]): r for r in expected_rows}
    expected_keys = {(c["case_id"], v) for c in cases for v in ("ring6", "ring7", "ring8")}
    if len(expected_rows) != 252 or set(expected_map) != expected_keys:
        raise ValueError("随包逐场存档缺少预期的 252 项比较")
    layouts = []
    for n, radius in ((6, 1125.0), (7, 998.0), (8, 940.0)):
        alpha = math.pi / n
        farthest = math.sqrt(max(r*r + radius*radius - 2*r*radius*math.cos(alpha) for r in (1000., 1800.)))
        if farthest >= 1000:
            raise ValueError("该布局不能覆盖整个连续圆域")
        layouts.append(dict(name="ring" + str(n), ring_points=n, radius_m=radius,
            max_distance_m=farthest, fixed_open_route_m=radius + 2*(n-1)*radius*math.sin(alpha)))
    variants = [dict(name=l["name"], module="m020", settings=dict(q3_ring_n=l["ring_points"], q3_ring_radius=l["radius_m"])) for l in layouts]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # 在启动任何一次算法之前登记比较范围；此处没有根据成绩选场景或改半径。
    protocol = dict(experiment="V14_P3 Q3 固定环点布局比较", problem="q3", algorithm=selected["version"],
        input_sha256=digest(HERE / "frozen_inputs.json"), case_ids=[c["case_id"] for c in cases],
        cases_reused_from="V14 fresh_confirmation Q3; 这些是既有场景，不新增独立确认样本",
        official=False, network_requests=0, parameters_selected_before_execution=True,
        changed_fields=["q3_ring_n", "q3_ring_radius"], baseline_settings=selected["settings"], variants=variants,
        full_settings={v["name"]: dict(selected["settings"], **v["settings"]) for v in variants},
        geometry=layouts, source_check=runtime.verify_files(), runtime_manifest_sha256=frozen["runtime_manifest_sha256"],
        metric="每场总模拟费用/实际全清源数，再对84场等权平均；完整保留所有场景与失败",
        pairing="同一个场景的源位置、频道、接收半径和误差函数相同；策略动作不同，读取的误差值可不同",
        selection_scope="比较 3 个预先指定的一环布局；不宣称任意点集或整场清除全局最优",
        python=sys.version, workers=args.workers, command=sys.argv)
    protocol["expected_rows_sha256"] = digest(expected_path)
    save(out / "protocol.json", protocol)
    start = time.monotonic()
    jobs = [(str(support), case, variant, str(out / "runs")) for case in cases for variant in variants]
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool, (out / "rows.partial.jsonl").open("x", encoding="utf-8") as partial:
        for row in pool.map(worker, jobs):
            rows.append(row)
            partial.write(json.dumps(row, ensure_ascii=False) + "\n")
            partial.flush()
            if len(rows) % 21 == 0 or not row["passed"]:
                print("进度 {}/{}，通过 {}，耗时 {:.1f}s".format(len(rows), len(jobs), row["passed"], time.monotonic()-start), flush=True)
    save(out / "rows.json", rows)
    if not all(r["passed"] for r in rows):
        save(out / "integrity.json", dict(passed=False, runs=len(rows), network_requests=0))
        return 1
    summary, pairs, strata = summarize(rows, layouts)
    expected = frozen["reference_ring6_rows"]
    actual = {r["case_id"]: r for r in rows if r["variant"] == "ring6"}
    mismatches = []
    for old in expected:
        new = actual[old["case_id"]]
        for key in ("source_count", "cleared_count", "per_source_s", "virtual_s", "costs", "actions", "passed"):
            if new[key] != old[key]:
                mismatches.append(dict(case_id=old["case_id"], field=key, expected=old[key], actual=new[key]))
    save(out / "summary.json", summary)
    save(out / "paired.json", pairs)
    save(out / "strata.json", strata)
    save(out / "baseline_agreement.json", dict(passed=not mismatches, cases=len(expected), exact_fields=7, mismatches=mismatches))
    archive_mismatches = []
    for row in rows:
        archived = expected_map[(row["case_id"], row["variant"])]
        for key in ("source_count", "cleared_count", "per_source_s", "virtual_s", "costs", "actions", "passed"):
            if row[key] != archived[key]:
                archive_mismatches.append(dict(case_id=row["case_id"], variant=row["variant"], field=key,
                    expected=archived[key], actual=row[key]))
    save(out / "archive_agreement.json", dict(passed=not archive_mismatches, runs=len(rows), exact_fields=7, mismatches=archive_mismatches))
    integrity = dict(passed=not mismatches and not archive_mismatches, runs=len(rows), case_count=len(cases), all_clear=all(r["cleared_count"] == r["source_count"] for r in rows),
        source_check=runtime.verify_files(), input_sha256=digest(HERE / "frozen_inputs.json"), network_requests=0,
        wall_s=time.monotonic()-start, baseline_exact_agreement=not mismatches, archive_exact_agreement=not archive_mismatches)
    save(out / "integrity.json", integrity)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if integrity["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--support", type=Path, default=Path(__file__).resolve().parent, help="完整解压的支撑材料根目录")
    parser.add_argument("--output", type=Path, required=True, help="新的输出目录")
    parser.add_argument("--workers", type=int, default=3)
    raise SystemExit(run(parser.parse_args()))
