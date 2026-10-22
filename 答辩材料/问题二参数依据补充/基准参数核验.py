"""2026-10-05 supplementary audit of Q2 baseline parameters.

This is a new analytical check, not historical evidence of how (750, 500)
was originally selected. Original manuscript and algorithms remain unedited.
"""
from pathlib import Path
import hashlib
import json
import math
import platform
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "支撑材料"
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))

from 问题二_定位直径上下界 import bound, sector_witness


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def facts(x, b, delta):
    d = math.radians(delta)
    h = 1500.0 * math.tan(d)
    triangle_bound = max(math.hypot(x, b),
                         math.hypot(1500.0-x, b+h),
                         math.hypot(1500.0-x, b-h))
    centers = [(r*math.cos(d), sign*r*math.sin(d))
               for r in (5.0, 1000.0) for sign in (-1, 1)]
    slack = 1000.0-max(math.dist((x, b), c) for c in centers)
    return {
        "point_m": [x, b],
        "move_distance_m": math.hypot(x, b),
        "move_time_s": math.hypot(x, b)/5.0,
        "triangle_uniform_distance_upper_m": triangle_bound,
        "triangle_uniform_reception_certified": triangle_bound <= 1000.0,
        "four_disk_constraint_slack_m": slack,
        "four_disk_reception_certified": slack > 1e-6,
    }


def main():
    delta = 1.005
    step = 0.0005
    h = 1500.0*math.tan(math.radians(delta))
    safe_b = math.sqrt(1000.0**2-750.0**2)-h
    sources = [SOURCE/"问题一_定位区域与包围圆.py",
               SOURCE/"问题二_安全第二测点.py",
               SOURCE/"问题二_定位直径上下界.py",
               SOURCE/"数据/q2_results.json",
               ROOT/"我的论文.docx"]
    hashes_before = {str(p.relative_to(ROOT)): sha256(p) for p in sources}
    recorded = json.loads((SOURCE/"数据/q2_results.json").read_text(encoding="utf-8"))
    ref = next(v for v in recorded["candidates"] if v["name"] == "legacy")
    ref = next(v for v in ref["bounds"] if v["delta_deg"] == delta)
    rows = []
    start = time.monotonic()
    for b in (100.0, 300.0, 400.0, 500.0, 550.0, 600.0, 625.0, 650.0):
        q = (750.0, b)
        row = facts(*q, delta)
        upper = bound(q, step=step, delta=delta, arc_segments=16)
        lower = sector_witness(q, delta=delta)
        row.update({"diameter_lower_m": lower["lower_m"],
                    "diameter_upper_m": upper["upper_m"],
                    "bound_gap_m": upper["upper_m"]-lower["lower_m"],
                    "second_reading_bin_count": upper["bins"],
                    "max_angle_bin_width_deg": upper["angle_step_deg"],
                    "lower_witness": lower,
                    "upper_witness": upper})
        if b == 500.0:
            row["recorded_lower_exact_match"] = lower["lower_m"] == ref["lower_m"]
            row["recorded_upper_exact_match"] = upper["upper_m"] == ref["upper_m"]
            assert row["recorded_lower_exact_match"]
            assert row["recorded_upper_exact_match"]
        assert row["four_disk_reception_certified"]
        assert lower["lower_m"] <= upper["upper_m"]
        rows.append(row)
        print(json.dumps({k: row[k] for k in (
            "point_m", "move_time_s", "diameter_lower_m",
            "diameter_upper_m", "triangle_uniform_reception_certified")},
            ensure_ascii=False), flush=True)
    hashes_after = {str(p.relative_to(ROOT)): sha256(p) for p in sources}
    assert hashes_before == hashes_after
    baseline = next(v for v in rows if v["point_m"][1] == 500.0)
    midpoint_finite_triangle = (
        1500.0**2+h*h+2.0*500.0*h)/(2.0*1500.0)
    report = {
        "audit_date_client": "2026-10-05",
        "provenance": "New supplementary analytical audit; not the original selection history",
        "scope": "normal first bearing, omnidirectional source, local sector, delta=1.005 deg",
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "analytic_certificate": {
            "outer_triangle": [[0.0, 0.0], [1500.0, h], [1500.0, -h]],
            "fixed_forward_m": 750.0,
            "safe_nonnegative_lateral_interval_m": [0.0, safe_b],
            "baseline_uniform_distance_upper_m": baseline["triangle_uniform_distance_upper_m"],
            "baseline_uniform_reception_margin_m": 1000.0-baseline["triangle_uniform_distance_upper_m"],
            "x_midpoint_in_zero_angle_outer_ray_model_m": 750.0,
            "x_balancing_triangle_vertices_at_lateral500_m": midpoint_finite_triangle,
            "midpoint_claim_scope": "750 is minimax in the zero-angle [0,1500] outer-ray distance model only",
            "lateral500_claim_scope": "500 is a preconfigured feasible baseline value; no unique or global optimum proof",
        },
        "rows": rows,
        "baseline_exact_reproduction": True,
        "original_files_unchanged": hashes_before == hashes_after,
        "source_sha256": hashes_before,
        "numerics": "Analytic reception proof plus existing float64 polygon outer bounds; not interval arithmetic",
        "evaluation_parameters": {"delta_deg": delta, "angle_bin_width_max_deg": step, "arc_segments": 16},
        "elapsed_s": time.monotonic()-start,
        "historical_selection_record": "Not present in current Q2 scripts",
        "global_optimality_proven": False,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT/"核验结果.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    table = "\n".join(
        f"| {r['point_m'][1]:.0f} | {r['move_time_s']:.2f} | "
        f"[{r['diameter_lower_m']:.4f}, {r['diameter_upper_m']:.4f}] | "
        f"{r['four_disk_constraint_slack_m']:.2f} | "
        f"{'通过' if r['triangle_uniform_reception_certified'] else '未通过；四圆盘约束仍通过'} |"
        for r in rows)
    md = rf"""# 第二问750、500的证据核验与答辩口径

## Material Passport

- 工作日期：2026-10-05，Asia/Shanghai。
- 工作类型：数学参数依据核验、确定性复算。
- 证据来源：现有选点源码、定位直径源码、原有结果文件和题面提取内容。
- 新增材料：本说明、基准参数核验.py、核验结果.json。
- 原材料保护：原论文及四个被读取的Q2相关来源文件哈希核对一致。
- 核验状态：原基准上下界精确复算成功；原始参数生成历史无法核验。
- 无随机场景、无训练、无官方测试；统计推断及显著性检验不适用。
- 本次计算是事后补充核验，不能作为竞赛期间原始选点记录。

## 1. 现有代码能证明什么

问题一_定位区域与包围圆.py的second_point直接给定前进750米、侧移500米。
问题二_安全第二测点.py的CHOICES保存基准、均衡、精度三个最终坐标。
当前Q2交付脚本提供安全检查与固定点连续上下界计算，没有提供这些坐标的完整生成搜索。

因此，必须区分：

1. 有数学理由构造这个基准。
2. 这个基准在真实有界误差下可行。
3. 当前源码为何在历史上恰好选了这两个数。
4. 这个基准是否最优。

本补充给出第1项的明确简化模型和第2项的连续解析保证，并复算定位表现。
第3项没有原始记录，第4项没有全局最优证明。

## 2. 750的可解释依据：简化中心线模型下的中点均衡

在忽略角误差的简化模型中，沿中心线的可能距离为(5,1500]；
将这个一维距离区间保守外包为[0,1500]。
给定侧移量b，测点q=(x,b)到候选源(r,0)的最坏距离满足

\[
F_b(x)^2=b^2+\max\{{x^2,(1500-x)^2\}}.
\]

在0≤x≤1500中，两个端点距离均衡时x=1500/2=750，且该处取得最小值。
这是一个清楚、可证明的基准构造准则。

重要边界：这不是完整问题二最坏定位直径D(q)的最优证明。
正常首测距离实际为5<r≤1500；使用[0,1500]是额外保守外包。
即使在有限角误差的三角外包中，固定b=500时均衡三个顶点距离所需的横坐标也是

\[
x_\mathrm{{bal}}=
\frac{{1500^2+h^2+2bh}}{{3000}}
\approx {midpoint_finite_triangle:.6f}\ \mathrm m,
\]

其中h=1500 tanδ。因此，不能把750说成实际有界角误差模型中的精确最优横坐标。

## 3. 500的接收可行性：完整扇形的保守解析证明

首测局部扇形满足x≥0、x≤1500、|y|≤x tanδ，故包含在三角形

\[
T=\operatorname{{conv}}\{{(0,0),(1500,h),(1500,-h)\}},\qquad
h=1500\tan\delta
\]

内。距固定测点的范数是凸函数，因此整个三角形的最坏距离由顶点控制。
对q=(750,b)、b≥0，得到

\[
\sup_{{G\in K}}\|q-G\|
\le\sqrt{{750^2+(b+h)^2}}.
\]

只要该上界不超过题设接收半径下界1000米，第二测点就保证接收。
这甚至没有使用首次成功接收给出的R≥r信息，是比四圆盘更保守的充分条件。

在δ=1.005°下：

- h={h:.9f}米；
- 合法保守横移范围0≤b≤sqrt(1000²−750²)−h={safe_b:.9f}米；
- b=500时，最远距离上界={baseline['triangle_uniform_distance_upper_m']:.9f}米；
- 相对1000米接收下界，解析距离余量={1000.0-baseline['triangle_uniform_distance_upper_m']:.9f}米。

因此(750,500)的接收可行性有连续域的数学证明。
但这个不等式允许一段横移范围，并没有唯一决定b=500。
500是现有代码中的保守基准参数，不能称作由题设必然推出或经过全域最优化得到的数值。

## 4. 新增横移对照：固定x=750，改变b

全部对照采用相同首测扇形、同一1.005°工作误差、同一角区间外包参数和移动速度。
上界覆盖连续第二示向，下界使用合法点对；这些数值来自现有float64几何程序。
横移对照只验证所列固定点的表现，不是完整二维安全域搜索或全局最优证明。

| 横移b / m | 移动时间 / s | 最坏定位直径区间 / m | 四圆盘约束余量 / m | 保守三角条件 |
|---:|---:|---:|---:|---|
{table}

原基准(750,500)上下界精确匹配历史结果：
下界{baseline['diameter_lower_m']:.12f}米，上界{baseline['diameter_upper_m']:.12f}米。
复算匹配证明现有结果可重复，不证明参数生成历史。
650米侧移未通过本节更保守的三角条件，但通过利用首次接收信息的四圆盘条件。

## 5. 可以直接用于答辩的诚实表述

“我们的(750,500)是一个有解析可行性保证的保守基准。
750采用中心线外包模型的中点均衡准则；500是安全横移区间内的预设基准值。
在完整1.005°误差下，我们用三角外包证明该点到全部候选源的距离不超过916.25米，
因此在接收半径至少1000米时保证接收。我们进一步用连续定位直径上下界评价其表现，
并与其他横移及候选测点比较。没有将500或该点宣称为全局最优。”

若被问“为什么不取400或600”，应展示对照并说明移动时间与最坏定位直径的权衡。
不能回答“试验证明500最好”，因为本次对照并没有这个结论。
若需要从规则唯一生成一个横移量，必须预先明确移动预算、精度阈值或费用目标，
再执行并保存搜索；这是新的策略修订，不能追认成原方案已经做过的过程。

## 6. 题面边界和复现方式

本项目题面提取文件raw-rules.json第1页记录，问题二要求第二检测点选择策略、
较好的定位效果和候选区域，没有明确要求证明全局最优。
这不代表任意参数都无需解释；构造准则、可行性证明和可复算比较仍应清楚。
需要正式引用时，以原B题.pdf为准。

运行本目录中的基准参数核验.py即可重新生成核验结果.json和本说明。
需要NumPy；几何计算代码读取项目支撑材料中的现有模块。
原材料SHA256、环境版本、下界点对、上界角区间和全部计算参数保存在核验结果.json。
"""
    (OUTPUT/"参数依据与答辩口径.md").write_text(md, encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "elapsed_s": time.monotonic()-start,
                      "original_files_unchanged": True, "baseline_exact_match": True},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
