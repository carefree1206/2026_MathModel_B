# -*- coding: utf-8 -*-
"""第一问的可复算几何示例：多次观测累积、测向反例和退化边界。

这些例子均为解析构造，只检验几何算法，不调用模拟器。
在支撑包根目录运行：python 问题一_多测点示例与退化检验.py --output results
在模板目录测试时显式指定：--code <已解压支撑包>/code
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import platform
import sys


ROOT = Path(__file__).resolve().parent
DELTA_DEG = 1.005
REFERENCE_SOURCE_M = (900.0, 90.0)
# 图 6 与正文数值共用此定义；示向度模拟接口的两位小数返回。
OBSERVATIONS = (
    {"station_m": (0.0, 0.0), "reading_deg": 5.31, "error_before_rounding_deg": -0.4},
    {"station_m": (710.0, 555.0), "reading_deg": 292.83, "error_before_rounding_deg": 0.6},
    {"station_m": (850.0, -200.0), "reading_deg": 79.72, "error_before_rounding_deg": -0.5},
    {"station_m": (1000.0, 100.0), "reading_deg": 186.11, "error_before_rounding_deg": 0.4},
)


def _require(condition, message):
    """即使 Python 使用 -O，也保留复现检查。"""
    if not condition:
        raise AssertionError(message)


def _geometry(code_dir=None):
    """明确加载支撑包冻结代码，避免误导入工作区内其他版本。"""
    code = Path(code_dir).resolve() if code_dir is not None else ROOT
    source = code / '问题一_定位区域与包围圆.py'
    if not source.is_file():
        raise FileNotFoundError('未找到问题一定位程序，请完整解压支撑材料。')
    import 问题一_定位区域与包围圆 as module
    if Path(module.__file__).resolve()!=source.resolve():
        raise RuntimeError('几何模块来源与指定目录不一致')
    return module, source


def _true_bearing(station, source):
    return math.degrees(math.atan2(source[1] - station[1], source[0] - station[0])) % 360.0


def _angle_difference(a, b):
    """返回 [-180,180) 内有符号角差，正确处理 0/360 度跨界。"""
    return (a - b + 180.0) % 360.0 - 180.0


def _halfplanes(planes):
    # 每一行均表示 a*x+b*y<=c；只为 JSON 明确字段，不修改几何数值。
    return [{"a": a, "b": b, "c": c} for a, b, c in planes]


def _violation(point, planes):
    """约束违反量按法向量长度归一化，单位为米。"""
    return max((a * point[0] + b * point[1] - c) / math.hypot(a, b)
               for a, b, c in planes if math.hypot(a, b) > 0.0)


def _region(geometry, planes):
    result = geometry.halfplane_region(planes)
    # 无界不冒充有限值，JSON 不写非标准 Infinity 或 NaN。
    result["mathematical_diameter"] = (
        "+infinity" if result["status"] == "unbounded"
        else "undefined_empty_set" if result["status"] == "empty"
        else "finite"
    )
    return result


def build_examples(code_dir=None):
    """返回全部验证后的结构化数据，供图件与正文共用；不产生文件。"""
    geometry, source_file = _geometry(code_dir)
    planes, observations = [], []
    previous_diameter = previous_radius = math.inf
    for step, definition in enumerate(OBSERVATIONS, 1):
        station = definition["station_m"]
        true_bearing = _true_bearing(station, REFERENCE_SOURCE_M)
        reading = round((true_bearing + definition["error_before_rounding_deg"]) % 360.0, 2) % 360.0
        _require(abs(reading - definition["reading_deg"]) < 1e-10,
                 "构造示向度与冻结的两位小数返回不一致。")
        actual_error = _angle_difference(reading, true_bearing)
        source_distance = math.dist(station, REFERENCE_SOURCE_M)
        _require(abs(actual_error) <= DELTA_DEG, "示例误差越过统一工作界。")
        _require(5.0 < source_distance <= 1000.0,
                 "示例应为 R=1000 米时也能正常接收的全向源。")
        new_planes = geometry.bearing_planes(station, reading, delta=DELTA_DEG)
        planes.extend(new_planes)
        region = _region(geometry, planes)
        _require(_violation(REFERENCE_SOURCE_M, planes) <= 1e-6, "新增观测错误排除了构造真值。")
        for vertex in region["vertices"]:
            _require(_violation(vertex, planes) <= 1e-6, "返回顶点违反已有半平面。")
        if step == 1:
            _require(region["status"] == "unbounded", "单次角楔应判为无界。")
        else:
            _require(region["status"] == "polygon", "多站示例应形成有界多边形。")
            diameter, radius = region["diameter_m"], region["enclosing_radius_m"]
            _require(diameter <= previous_diameter + 1e-6, "增加观测后直径不应增大。")
            _require(radius <= previous_radius + 1e-6, "增加观测后最小包围圆不应增大。")
            _require(math.dist(region["enclosing_center"], REFERENCE_SOURCE_M) <= radius + 1e-6,
                     "包围圆未包含构造真值。")
            previous_diameter, previous_radius = diameter, radius
        observations.append({
            "step": step,
            "station_m": station,
            "reading_deg": reading,
            "true_bearing_deg": true_bearing,
            "actual_return_error_deg": actual_error,
            "source_distance_m": source_distance,
            "new_halfplanes": _halfplanes(new_planes),
            "accumulated_halfplanes": _halfplanes(planes),
            "region": region,
            "guaranteed_clear_at_mec_19_99m": (
                region.get("enclosing_radius_m") is not None and region["enclosing_radius_m"] <= 19.99
            ),
        })

    # 固定数值是回归核对；正确性另由原始约束、包含性及解析例子检查。
    expected = ((43.13233943532047, 21.566169817660278),
                (30.71068739413969, 15.386968192068288),
                (11.83149449322307, 5.916959782207593))
    for row, (diameter, radius) in zip(observations[1:], expected):
        _require(abs(row["region"]["diameter_m"] - diameter) < 2e-6, "多测站直径与冻结值不符。")
        _require(abs(row["region"]["enclosing_radius_m"] - radius) < 2e-6, "多测站包围半径与冻结值不符。")

    # 三测站均为题设 ±1 度模型；它与上面的 1.005 度示例分别存储。
    root3 = math.sqrt(3.0)
    triangle = [(0.0, 0.0), (40.0, 0.0), (20.0, 20.0 * root3)]
    triangle_stations = [(-1000.0, 0.0), (540.0, -500.0 * root3), (520.0, 520.0 * root3)]
    triangle_readings = [1.0, 121.0, 241.0]
    triangle_planes = []
    for station, reading in zip(triangle_stations, triangle_readings):
        triangle_planes.extend(geometry.bearing_planes(station, reading, delta=1.0))
        for vertex in triangle:
            _require(5.0 < math.dist(station, vertex) <= 1500.0,
                     "三角形顶点应可由半径 1500 米全向源产生正常示向。")
            _require(abs(_angle_difference(reading, _true_bearing(station, vertex))) <= 1.0 + 1e-10,
                     "三角形顶点不能解释某个测站示向。")
    triangle_region = _region(geometry, triangle_planes)
    _require(triangle_region["status"] == "polygon" and len(triangle_region["vertices"]) == 3,
             "三测站反例应恰好生成三角形。")
    for vertex in triangle:
        _require(min(math.dist(vertex, actual) for actual in triangle_region["vertices"]) < 1e-6,
                 "反例计算顶点与解析顶点不一致。")
    _require(abs(triangle_region["diameter_m"] - 40.0) < 2e-6, "反例直径应为 40 米。")
    _require(abs(triangle_region["enclosing_radius_m"] - 40.0 / root3) < 2e-6,
             "反例最小包围圆半径不符解析结果。")
    _require(triangle_region["enclosing_radius_m"] > 20.0,
             "反例应证实直径 40 米仍不能被半径 20 米圆覆盖。")

    # 下列为算法边界输入，不假称其均来自正常测向反馈。
    boundary_definitions = [
        ("bounded_rectangle", "polygon", [(1, 0, 2), (-1, 0, 0), (0, 1, 1), (0, -1, 0)], math.sqrt(5.0)),
        ("empty", "empty", [(1, 0, 0), (-1, 0, -1)], None),
        ("unbounded_halfplane", "unbounded", [(1, 0, 0)], None),
        ("segment", "segment", [(1, 0, 0), (-1, 0, 0), (0, 1, 1), (0, -1, 0)], 1.0),
        ("point", "point", [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)], 0.0),
    ]
    boundaries = []
    for name, status, constraints, diameter in boundary_definitions:
        region = _region(geometry, constraints)
        _require(region["status"] == status, "边界状态分类失败：" + name)
        if diameter is not None:
            _require(abs(region["diameter_m"] - diameter) < 1e-6, "边界直径失败：" + name)
        boundaries.append({"name": name, "halfplanes": _halfplanes(constraints), "region": region})

    return {
        "schema": "q1_examples_v1",
        "example_type": "解析构造与边界检查；不是官方演练或正式测试",
        "coordinate_unit": "m",
        "angle_unit": "degree",
        "halfplane_convention": "a*x+b*y<=c；两角边界共同组成朝前闭角楔",
        "python_version": platform.python_version(),
        "frozen_geometry_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
        "sequential": {
            "delta_deg": DELTA_DEG,
            "reference_source_m": REFERENCE_SOURCE_M,
            "compatible_reception_radius_m": 1000.0,
            "field_or_range_clipping_used": False,
            "display_window_is_constraint": False,
            "observations": observations,
            "explanation": "第一站无界；第二至第四站持续收缩。第三站后已满足19.99米余量判据；第四站只演示一般多观测累积，并非清除前的必需动作。",
        },
        "equilateral_counterexample": {
            "delta_deg": 1.0,
            "stations_m": triangle_stations,
            "readings_deg": triangle_readings,
            "compatible_reception_radius_m": 1500.0,
            "analytic_vertices_m": triangle,
            "analytic_diameter_m": 40.0,
            "analytic_minimum_radius_m": 40.0 / root3,
            "halfplanes": _halfplanes(triangle_planes),
            "region": triangle_region,
        },
        "halfplane_boundary_cases": boundaries,
        "checks_passed": True,
    }


def validate(out, code_dir=None):
    """验证并写入 q1_examples.json，返回同一数据对象供主入口使用。"""
    result = build_examples(code_dir)
    output = Path(out)
    output.mkdir(parents=True, exist_ok=True)
    (output / "q1_examples.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return result


def render(out, code_dir=None):
    """提供统一简易入口；本模块输出数据，插图由论文图件脚本绘制。"""
    return validate(out, code_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results", help="结果目录，写入 q1_examples.json")
    parser.add_argument("--code", default=None, help="支撑包 code 目录；通常无需指定")
    args = parser.parse_args()
    result = validate(args.output, args.code)
    for observation in result["sequential"]["observations"]:
        region = observation["region"]
        if region["status"] == "unbounded":
            print("第 1 次：无界；未添加人为绘图边框约束。")
        else:
            print("第 %d 次：直径 %.6f 米，最小包围圆半径 %.6f 米。" %
                  (observation["step"], region["diameter_m"], region["enclosing_radius_m"]))
    print("Q1 四次观测、三测站反例及五类边界检查全部通过。")


if __name__ == "__main__":
    main()
