"""独立核对 Q4 的 18 点下界常数及现有 21 点连续覆盖证书。

只使用 Python 标准库，不调用模拟器或模型求解程序。
从支撑材料根目录运行：python 问题四_基础点数界核验.py
"""
import argparse
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path


def check(condition, message):
    """检查失败时立即停止，避免把未通过的证书写成成功。"""
    if not condition:
        raise ValueError(message)


def trig_bounds(x, cosine=False):
    """在 0≤x≤1 上，以交错 Taylor 级数给出严格有理数包络。"""
    check(F(0) <= x <= F(1), "三角级数参数越界")
    term = F(1) if cosine else x
    total = F(0)
    for k in range(19):
        total += term if k % 2 == 0 else -term
        first = 2 * k + (1 if cosine else 2)
        term *= x * x / (first * (first + 1))
    return total - term, total


def atan_bounds(x):
    """反正切交错级数；第 60 项和第 61 项分别给出上、下界。"""
    check(F(0) < x < F(1), "反正切参数越界")
    total, power = F(0), x
    for k in range(61):
        total += (power if k % 2 == 0 else -power) / (2 * k + 1)
        power *= x * x
    return total - power / 123, total


def check_lower_bound():
    """用不同于原研究脚本的正弦、余弦判别独立验证关键角度上界。"""
    a, c, d, e = map(F, ["0.589030971", "0.451026812", "0.562960147", "0.508"])
    check(trig_bounds(a)[0] > F(5, 9), "一般测点半弧上界失败")
    check(trig_bounds(c, True)[1] < F(9, 10), "内点半弧上界失败")
    check(trig_bounds(d / 2)[0] > F(5, 18), "外点半弧上界失败")
    check(trig_bounds(e)[0] > F(5, 9) * trig_bounds(e, True)[1], "朝外天线半弧上界失败")
    # Machin 恒等式独立包络 π，所有比较均使用分数，未使用浮点三角函数。
    p, q = atan_bounds(F(1, 5)), atan_bounds(F(1, 239))
    pi_lower = 16 * p[0] - 4 * q[1]
    check(pi_lower > F("3.1415926535897932384626"), "π 的下界失败")
    capacity = 3 * c + 7 * d + 7 * a
    check(6 * e < pi_lower, "六个外点未被严格排除")
    check(capacity < 3 * pi_lower, "17 点未被严格排除")
    check(3 * pi_lower - capacity > F("0.0077596987"), "容量缺口不足")
    return {
        "passed": True,
        "method": "有理正弦/余弦 Taylor 包络及 Machin 恒等式；独立于原反正切-根号计算",
        "angle_upper_bounds_rad": dict(a=str(a), c=str(c), d=str(d), e=str(e)),
        "N17_capacity_upper_exact": str(capacity),
        "positive_gap_lower_rad": "0.0077596987",
        "universal_fixed_site_lower_bound": 18,
    }


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def check_upper_bound(path, config_path):
    """逐格重查整数证书，确认每个格由全格可接收的测点凸包覆盖。"""
    raw = path.read_bytes()
    cert = json.loads(raw)
    check(cert["passed"] and not cert["unresolved"], "输入证书未完成")
    check(cert["scale"] == 1000 and cert["source_radius"] == 1800000, "源域或单位不符")
    check(cert["reception_radius"] == 999990, "证书接收半径不符")
    points = [tuple(p) for p in cert["points_mm"]]
    check(len(points) == len(set(points)) == 21, "不是 21 个不同测点")
    config_raw = config_path.read_bytes()
    cfg = json.loads(config_raw)
    configured = {(0, 0)}
    for count, radius_m, phase in [(cfg['q4_inner_n'], cfg['q4_inner_radius'], 0),
                                   (cfg['q4_ring_n'], cfg['q4_ring_radius'], cfg['q4_outer_phase'])]:
        for k in range(count):
            theta = math.radians(phase) + 2 * math.pi * k / count
            configured.add((round(round(radius_m * math.cos(theta), 3) * 1000),
                            round(round(radius_m * math.sin(theta), 3) * 1000)))
    # 此处只核对配置到毫米坐标的身份；后续几何证明全部使用整数。
    check(set(points) == configured, "证书测点与采用配置不同")
    rows = {tuple(row["box"]): row for row in cert["leaves"]}
    check(len(rows) == len(cert["leaves"]), "证书存在重复格")
    root = tuple(cert["root"])
    radius, reception = cert["source_radius"], cert["reception_radius"]
    check(root[0] <= -radius and root[1] <= -radius and root[2] >= radius and root[3] >= radius,
          "根格未覆盖源盘")
    stack, visited, used, covered = [root], 0, set(), 0
    while stack:
        box = stack.pop()
        x0, y0, x1, y1 = box
        visited += 1
        check(visited <= 4 * len(rows) + 1, "分区未闭合")
        if box not in rows:
            check(x1 - x0 > 1 and y1 - y0 > 1, "分区存在缺口")
            xm, ym = (x0 + x1) // 2, (y0 + y1) // 2
            stack.extend([(x0,y0,xm,ym), (xm,y0,x1,ym), (xm,ym,x1,y1), (x0,ym,xm,y1)])
            continue
        used.add(box)
        row = rows[box]
        if row.get("outside"):
            dx, dy = max(x0, -x1, 0), max(y0, -y1, 0)
            check(dx * dx + dy * dy > radius * radius, "盘外标记错误")
            continue
        ids = row["hull"]
        check(len(ids) >= 3 and len(set(ids)) == len(ids), "凸包见证点不足或重复")
        check(all(0 <= i < len(points) for i in ids), "凸包索引越界")
        poly = [points[i] for i in ids]
        corners = [(x0,y0), (x1,y0), (x1,y1), (x0,y1)]
        for a, b in zip(poly, poly[1:] + poly[:1]):
            check(all(cross(a, b, p) >= 0 for p in poly), "见证多边形不满足凸性")
            edge2 = (b[0]-a[0])**2 + (b[1]-a[1])**2
            for corner in corners:
                h = cross(a, b, corner)
                check(h > 0 and h*h > 4 * edge2, "格角点未严格位于凸包内")
        for p in poly:
            check(all((p[0]-q[0])**2 + (p[1]-q[1])**2 <= reception**2 for q in corners),
                  "测点不能接收整个格")
        covered += 1
    check(used == set(rows), "证书含未使用叶格")
    check(visited == cert["visited_nodes"] == 6485 and len(rows) == 4864, "证书节点统计不符")
    return {
        "passed": True, "site_count": len(points), "visited_nodes": visited,
        "leaves": len(rows), "covered_leaves": covered, "reception_radius_m": "999.99",
        "certificate_sha256": hashlib.sha256(raw).hexdigest(),
        "config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "configured_sites_match": True,
        "method": "整数毫米、平方距离、叉积及完整四叉分区；不导入证书生成程序",
    }


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", type=Path, default=base / "数据/q4_coverage_certificate.json")
    parser.add_argument("--config", type=Path, default=base / "数据/参数/问题四_算法参数.json")
    parser.add_argument("--output", type=Path, default=base / "q4_site_bounds_check.json")
    args = parser.parse_args()
    result = {
        "schema": "q4-fixed-site-bounds-v1", "lower_bound": check_lower_bound(),
        "upper_bound": check_upper_bound(args.certificate, args.config),
        "conclusion": "18≤N*≤21，21/N*≤7/6；仅适用于固定通用无线发现布局的不同测点数",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("通过：18 点下界常数；21 点证书全部 6485 节点、4864 叶格。")


if __name__ == "__main__":
    main()
