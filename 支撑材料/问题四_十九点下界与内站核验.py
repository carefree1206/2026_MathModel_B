"""独立核验固定无线发现布局的 19 点下界及 660 米内站必要条件。

仅需 Python 3.9 及以上版本的标准库。程序重新计算全部连续区间上界，
不导入原证明程序，不依赖优化器；浮点数只用于结果的小数显示。
"""
from fractions import Fraction as Q
from functools import lru_cache
from math import factorial, isqrt
from pathlib import Path
import argparse
import hashlib
import json
import time


HERE = Path(__file__).resolve().parent / '数据/问题四覆盖证明/latest'
ANGLE_SCALE = 10 ** 10
CERTIFICATES = {
    "n19_exact.json": "be29c0957913ea667b6c89d98a1a70f147a996ae707cc2c61e94c9a4074d9eae",
    "inner660_exact.json": "b6d8b7d359c3786cb9be0b34e4a760b6895b5d6328308f4483da599ad08da2a5",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arctan_bracket(z):
    # 正项结束的部分和为上界，再减去下一项即可得到下界。
    value = sum((-1) ** k * z ** (2 * k + 1) / Q(2 * k + 1)
                for k in range(21))
    return value - z ** 43 / Q(43), value


def floor_q(value):
    return value.numerator // value.denominator


def ceil_q(value):
    return -((-value.numerator) // value.denominator)


def pi_bracket():
    # Machin 公式配合有理数级数，为圆周率给出双侧界。
    a, b = arctan_bracket(Q(1, 5)), arctan_bracket(Q(1, 239))
    lower, upper = 16 * a[0] - 4 * b[1], 16 * a[1] - 4 * b[0]
    scale = 10 ** 24
    return Q(floor_q(lower * scale), scale), Q(ceil_q(upper * scale), scale)


PI = pi_bracket()


@lru_cache(None)
def cos_grid(k):
    x = Q(k, ANGLE_SCALE)
    assert 0 <= x <= 2
    squared, term, value = x * x, Q(1), Q(1)
    # 28 次余弦多项式也是 29 次 Taylor 多项式，余项由 x^30/30! 控制。
    for j in range(1, 15):
        term *= -squared / Q((2 * j - 1) * (2 * j))
        value += term
    error = x ** 30 / Q(factorial(30))
    return value - error, value + error


@lru_cache(None)
def acos_bracket(z):
    """用有理余弦界二分反余弦，返回向外包住真值的闭区间。"""
    z = Q(z)
    assert -1 <= z <= 1
    if z == 1:
        return Q(0), Q(0)
    if z == -1:
        return PI
    if z == 0:
        return PI[0] / 2, PI[1] / 2
    if z < 0:
        lower, upper = acos_bracket(-z)
        return PI[0] - upper, PI[1] - lower
    lower, upper = 0, ceil_q(PI[1] * ANGLE_SCALE / 2)
    assert cos_grid(lower)[0] > z and cos_grid(upper)[1] < z
    while upper - lower > 1:
        middle = (lower + upper) // 2
        interval = cos_grid(middle)
        if interval[0] > z:
            lower = middle
        elif interval[1] < z:
            upper = middle
        else:
            raise ArithmeticError("当前余弦外包无法判定大小关系")
    return Q(lower, ANGLE_SCALE), Q(upper, ANGLE_SCALE)


def sqrt_lower(value):
    value = Q(value)
    scale = 10 ** 15
    k = isqrt(value.numerator * scale * scale // value.denominator)
    answer = Q(k, scale)
    assert answer * answer <= value < Q(k + 1, scale) ** 2
    return answer


@lru_cache(None)
def beta_upper(rho, radius):
    """距离接收弧半角 B_radius(rho) 的有理上界。"""
    rho, radius = Q(rho), Q(radius)
    if rho + radius <= 1000:
        return PI[1]
    if abs(rho - radius) >= 1000 or rho == 0:
        return Q(0)
    z = (rho * rho + radius * radius - 1000 ** 2) / (2 * rho * radius)
    return acos_bracket(z)[1]


def beta_sup(lower, upper, radius):
    # 除端点外，还检查区间内唯一可能的极大值，覆盖全部连续半径。
    bound = max(beta_upper(lower, radius), beta_upper(upper, radius))
    critical_squared = radius * radius - 1000 ** 2
    if radius > 1000 and lower * lower <= critical_squared <= upper * upper:
        z_lower = sqrt_lower(Q(critical_squared, radius * radius))
        bound = max(bound, acos_bracket(z_lower)[1])
    return bound


@lru_cache(None)
def inward_upper(rho):
    """400 米源圆径向向内接收弧的半长度上界。"""
    rho = Q(rho)
    if rho <= 400:
        return PI[1]
    if rho * rho >= 1160000:
        return Q(0)
    direction_lower = acos_bracket(Q(400) / rho)[0]
    return max(Q(0), beta_upper(rho, 400) - direction_lower)


@lru_cache(None)
def outward_upper(rho):
    rho = Q(rho)
    if rho <= 1800 or rho >= 2800:
        return Q(0)
    return min(acos_bracket(Q(1800) / rho)[1], beta_upper(rho, 1800))


def outward_sup(lower, upper):
    bound = max(outward_upper(lower), outward_upper(upper))
    critical_squared = 1800 ** 2 + 1000 ** 2
    if lower * lower <= critical_squared <= upper * upper:
        z_lower = sqrt_lower(Q(1800 ** 2, critical_squared))
        bound = max(bound, acos_bracket(z_lower)[1])
    return bound


def read_certificate(name):
    path = HERE / "evidence" / name
    if sha256(path) != CERTIFICATES[name]:
        raise ValueError("原始证书的 SHA-256 不一致：" + name)
    return json.loads(path.read_text(encoding="utf-8"))


def interval_summary(rows):
    row = max(rows, key=lambda item: Q(item["upper"]))
    return {"interval_m": [row["lo_m"], row["hi_m"]],
            "upper_rational": row["upper"], "upper_display": float(Q(row["upper"]))}


def verify(output):
    if not __debug__:
        raise RuntimeError("核验依赖精确断言，请不要使用 Python 的 -O 选项")
    started = time.monotonic()
    previous = read_certificate("n19_exact.json")
    current = read_certificate("inner660_exact.json")
    old_weights = (Q(85, 1000), Q(393, 1000), Q(5333, 1000), Q(708, 1000))
    new_weights = (Q(2522, 1000), Q(5333, 1000), Q(708, 1000))
    old_demand = 3 * sum(old_weights[:3]) + old_weights[3]
    new_demand = new_weights[0] + 3 * new_weights[1] + new_weights[2]
    assert old_demand == Q(previous["weighted_required_total"]) == Q(18141, 1000)
    assert new_demand == Q(current["weighted_required_total"]) == Q(19229, 1000)
    assert len(previous["radius_intervals"]) == 560
    assert len(current["closed_radius_intervals"]) == 400

    # 四项资源：每站容量至多 1，而总需求为 18.141，整数站数至少为 19。
    old_rows = []
    for index, lower in enumerate(range(0, 2800, 5)):
        upper = lower + 5
        stored = previous["radius_intervals"][index]
        assert stored["lo_m"] == lower and stored["hi_m"] == upper
        assert Q(stored["capacity_upper_rational"]) <= 1
        arcs = (beta_sup(lower, upper, 50), beta_sup(lower, upper, 200),
                beta_sup(lower, upper, 1800), outward_sup(lower, upper))
        capacity = sum(w * arc for w, arc in zip(old_weights, arcs)) / PI[0]
        assert capacity < 1, (lower, upper, capacity)
        old_rows.append({"lo_m": lower, "hi_m": upper, "upper": str(capacity)})
    assert old_demand > 18

    # 三项资源：对所有 rho>=800 的站，容量至多 1，总需求却为 19.229。
    new_rows = []
    for index, lower in enumerate(range(800, 2800, 5)):
        upper = lower + 5
        stored = current["closed_radius_intervals"][index]
        assert stored["lo_m"] == lower and stored["hi_m"] == upper
        assert Q(stored["weighted_capacity_upper"]) <= 1
        # 向内弧随半径不增，故左端点外包适用于整个闭区间。
        arcs = (inward_upper(lower), beta_sup(lower, upper, 1800),
                outward_sup(lower, upper))
        capacity = sum(w * arc for w, arc in zip(new_weights, arcs)) / PI[0]
        assert capacity < 1, (lower, upper, capacity)
        new_rows.append({"lo_m": lower, "hi_m": upper, "upper": str(capacity)})
    assert new_demand > 19

    # 若闭 D800 中有两站，旧资源容量不足；因此 19 站布局只有一个内站。
    old_core_capacity = old_weights[0] + old_weights[1]
    assert old_core_capacity == Q(239, 500)
    assert 17 + 2 * old_core_capacity < old_demand
    # 若唯一内站仍位于 [660,800]，新资源容量也不足，严格排除两个端点。
    core660 = new_weights[0] * inward_upper(660) / PI[0]
    assert 18 + core660 < new_demand
    assert beta_upper(800, 1800) == outward_upper(800) == 0
    assert inward_upper(1400) == beta_upper(2800, 1800) == outward_upper(2800) == 0

    scope = {"source_disk_radius_m": 1800, "reception_radius_m": 1000,
             "arbitrary_closed_half_plane_direction": True,
             "arbitrary_finite_station_coordinates": True,
             "fixed_layout_only": True}
    checks = {
        "passed": True,
        "lower_bound": {"passed": True, "minimum_station_count": 19,
                        "weighted_demand": str(old_demand), "closed_intervals": 560,
                        "maximum_capacity": interval_summary(old_rows)},
        "inner_station": {"passed": True, "conditional_station_count": 19,
                          "exactly_one_station_radius_lt_m": 660,
                          "all_other_station_radii_gt_m": 800,
                          "weighted_demand": str(new_demand), "closed_intervals": 400,
                          "maximum_capacity": interval_summary(new_rows),
                          "core660_upper_rational": str(core660),
                          "core660_upper_display": float(core660),
                          "strict_deficit_rational": str(new_demand - 18 - core660)},
        "scope": scope,
        "general_19_and_20_feasibility": "未决",
        "upper_bound_21": "沿用支撑材料中既有 21 点连续覆盖证书，本入口只重算下界与内站条件",
        "no_float_proof_decisions": True,
        "all_radii_covered": True,
        "outside_2800_all_resources_zero": True,
        "input_sha256": CERTIFICATES,
        "script_sha256": sha256(Path(__file__)),
        "elapsed_seconds": time.monotonic() - started,
    }
    details = {"pi_bracket": [str(x) for x in PI],
               "n19_radius_intervals": old_rows, "inner660_radius_intervals": new_rows}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("checks.json", checks), ("interval_bounds.json", details)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/latest_bounds"),
                        help="保存 checks.json 及逐区间有理上界的目录")
    verify(parser.parse_args().output)
