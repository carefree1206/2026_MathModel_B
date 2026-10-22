"""答辩补充核验：读取冻结资料，新增输出；不修改论文、参数或旧结果。"""
from pathlib import Path
import collections
import datetime
import gzip
import hashlib
import importlib
import json
import math
import platform
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / '支撑材料'
OUT = Path(__file__).resolve().parent / '实验'
SEED = 20261006
BOOTSTRAP_REPS = 50000


def read(path):
    raw = path.read_bytes()
    if path.suffix == '.gz':
        raw = gzip.decompress(raw)
    return json.loads(raw.decode('utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                      allow_nan=False) + '\n', encoding='utf-8')


def exact_sign_p(wins, losses):
    """双侧精确符号检验，零差异剔除；检验胜率，不检验均值。"""
    n = wins + losses
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)


def paired_analysis(rows, problem, chosen):
    part = [r for r in rows if r['panel'] == 'fresh_confirmation' and r['problem'] == problem]
    baseline = {r['case_id']: r for r in part if r['variant'] == 'm019'}
    adopted = {r['case_id']: r for r in part if r['variant'] == chosen}
    assert set(baseline) == set(adopted) and len(baseline) == 84
    ids = sorted(baseline)
    b = np.array([baseline[k]['per_source_s'] for k in ids])
    a = np.array([adopted[k]['per_source_s'] for k in ids])
    counts = np.array([baseline[k]['source_count'] for k in ids])
    for key in ids:
        assert baseline[key]['source_count'] == adopted[key]['source_count']
        assert baseline[key]['passed'] and adopted[key]['passed']
        assert baseline[key]['cleared_count'] == baseline[key]['source_count']
        assert adopted[key]['cleared_count'] == adopted[key]['source_count']
    assert collections.Counter(counts.tolist()) == {n: 12 for n in range(10, 17)}
    rng = np.random.default_rng(SEED + (3 if problem == 'q3' else 4))
    bs = np.zeros(BOOTSTRAP_REPS)
    ads = np.zeros(BOOTSTRAP_REPS)
    strata = []
    for n in range(10, 17):
        mask = counts == n
        bn, an = b[mask], a[mask]
        indices = rng.integers(0, len(bn), size=(BOOTSTRAP_REPS, len(bn)))
        bs += bn[indices].mean(axis=1) / 7
        ads += an[indices].mean(axis=1) / 7
        strata.append(dict(source_count=n, n=len(bn), baseline_mean_s=float(bn.mean()),
                           adopted_mean_s=float(an.mean()), saving_s=float((bn-an).mean()),
                           saving_percent=float(100*(bn.mean()-an.mean())/bn.mean())))
    diff = b - a
    pct = 100 * (bs - ads) / bs
    tol = 1e-8
    wins, losses = int((diff > tol).sum()), int((diff < -tol).sum())
    changes = 100 * (a / b - 1)
    worst = int(np.argmax(changes))
    return dict(problem=problem, baseline='m019', adopted=chosen, n=84,
                baseline_mean_s=float(b.mean()), adopted_mean_s=float(a.mean()),
                mean_saving_s=float(diff.mean()),
                mean_saving_percent=float(100*(b.mean()-a.mean())/b.mean()),
                saving_s_ci95=np.quantile(bs-ads, [.025, .975]).tolist(),
                saving_percent_ci95=np.quantile(pct, [.025, .975]).tolist(),
                paired_difference_sd_s=float(diff.std(ddof=1)),
                wins=wins, losses=losses, ties=84-wins-losses,
                sign_test_two_sided_p=exact_sign_p(wins, losses),
                sign_test_null='Independent synthetic worlds; P(saving>0)=1/2 conditional on non-ties',
                worst_relative_increase_percent=float(changes[worst]), worst_case_id=ids[worst],
                strata=strata,
                pooled_per_source_s=float(sum(adopted[k]['virtual_s'] for k in ids)/sum(counts)),
                limitation='Post-hoc supplemental analysis of archived synthetic confirmation; does not establish official-distribution performance or worst-case guarantee')


def statistics():
    path = SUPPORT / '数据/benchmark.json.gz'
    rows = read(path)['rows']
    seen = set()
    max_cost_error = 0.
    for r in rows:
        key = (r['panel'], r['problem'], r['case_id'], r['variant'])
        assert key not in seen
        seen.add(key)
        assert r['passed'] and r['cleared_count'] == r['source_count']
        c = r['costs']
        total = c['move_m']/5 + 5*c['measures'] + c['switch_s'] + 3*c['clears'] + 2*c['successes']
        error = abs(total-r['virtual_s'])
        assert error < 1e-7 and abs(r['per_source_s'] - total/r['cleared_count']) < 1e-7
        max_cost_error = max(max_cost_error, error)
    results = [paired_analysis(rows, 'q3', 'm020'), paired_analysis(rows, 'q4', 'm021')]
    ordered = sorted(range(2), key=lambda i: results[i]['sign_test_two_sided_p'])
    running = 0.
    for rank, i in enumerate(ordered):
        running = max(running, min(1., (2-rank)*results[i]['sign_test_two_sided_p']))
        results[i]['sign_test_holm_adjusted_p'] = running
    save('配对统计补充.json', dict(passed=True, input_sha256=digest(path), rows_audited=len(rows),
                              maximum_cost_error_s=max_cost_error, seed=SEED,
                              bootstrap_reps=BOOTSTRAP_REPS,
                              method='Within each source-count stratum, resample 12 whole paired worlds; preserve 7 equal strata; percentile 95% intervals. No action/source-level pseudoreplication.',
                              multiplicity='Holm correction for two adopted-policy sign tests', results=results))
    return results


def formal_ledgers():
    folder = SUPPORT / '数据/正式测试'
    summary = read(folder/'正式结果摘要.json')
    results = []
    for item in summary['结果']:
        base = SUPPORT / item['资料目录']
        actions = base/'原始动作.jsonl'
        assert digest(actions) == item['动作记录SHA256']
        records = [json.loads(line) for line in actions.read_text('utf-8-sig').splitlines() if line.strip()]
        position, channel, total, length = (0., 0.), 1, 0., 0.
        counts = collections.Counter()
        accepted_ids = set()
        max_error = 0.
        max_step_error = 0.
        previous_clock = 0.
        positive_moves = 0
        floating_budget = 0.
        for row in records:
            assert row['http_status'] == 200 and row['accepted'] is True
            req, res, endpoint = row['request'], row['response'], row['endpoint']
            assert req['request_id'] not in accepted_ids, 'Duplicated accepted action must be deduplicated before accounting'
            accepted_ids.add(req['request_id'])
            increment = 0.
            moving = False
            if endpoint in ('/measure', '/clear'):
                target = (req['position']['x'], req['position']['y'])
                step = math.dist(position, target)
                length += step
                increment += step/5
                moving = step > 0
                positive_moves += int(moving)
                position = target
                if endpoint == '/measure':
                    counts['M'] += 1
                    counts['K'] += int(req['channel'] != channel)
                    increment += 5 + int(req['channel'] != channel)
                    channel = req['channel']
                else:
                    counts['C'] += 1
                    success = res['clear_result'] == 'success'
                    counts['S'] += int(success)
                    increment += 3 + 2*int(success)
            else:
                assert endpoint in ('/enter', '/exit')
            total += increment
            floating = 64*math.ulp(max(1., abs(total), abs(increment)))
            floating_budget += floating
            error = abs(total-res['virtual_time_s'])
            step_error = abs(res['virtual_time_s']-previous_clock-increment)
            max_error = max(max_error, error)
            max_step_error = max(max_step_error, step_error)
            # 官方响应以微秒表示时间。按移动次数累计量化误差预算，
            # 另外检查每步误差；不以任意放宽的固定容差掩盖计费错误。
            assert step_error <= floating + 1e-6*int(moving)
            assert error <= floating_budget + positive_moves*1e-6
            previous_clock = res['virtual_time_s']
        assert records[0]['endpoint'] == '/enter' and records[-1]['endpoint'] == '/exit'
        assert counts['S'] == item['成功清除数']
        assert abs(previous_clock-item['虚拟总耗时_s']) < 1e-9
        assert item['官方总源数'] is None and item['官方全清比例'] is None
        official_path = next(base.glob('*.result.json'))
        identity = read(official_path)
        jlog = next(base.glob('*.jlog'))
        assert digest(jlog) == identity['package_sha256'] == item['官方日志SHA256']
        assert identity['problem_no'] == int(item['问题'][1:])
        assert identity['case_code'] == item['测试编码']
        results.append(dict(problem=item['问题'], case_code=item['测试编码'], records=len(records),
                            L_m=length, **dict(counts), ideal_unquantized_total_s=total,
                            total_s=previous_clock, per_source_s=previous_clock/counts['S'],
                            maximum_clock_error_s=max_error, maximum_step_clock_error_s=max_step_error,
                            quantization_budget_s=positive_moves*1e-6,
                            official_identity_hash_matched=True,
                            official_source_count=None, official_full_clear_ratio=None,
                            user_exit_is_request_reason=True))
    assert sum(r['records'] for r in results) == 1171
    save('正式账本独立计费.json', dict(passed=True, records=1171, results=results,
                                scope='Recalculated every archived accepted API action from coordinates, channel state and problem action costs; matched official log identity hashes. No solver replay, encrypted-jlog decryption, hidden-truth check or new official test.'))
    return results


def counterexamples():
    sys.path.insert(0, str(SUPPORT))
    geo = importlib.import_module('问题一_定位区域与包围圆')
    q2 = importlib.import_module('问题二_安全第二测点')
    triangle = [(0., 0.), (40., 0.), (20., 20*math.sqrt(3))]
    diameter, _ = geo.diameter(triangle)
    center, radius = geo.enclosing_circle(triangle)
    assert abs(diameter-40) < 1e-8 and radius > 20
    true_angle, fixed_error = .0049, -1.
    displayed = round((true_angle+fixed_error) % 360, 2) % 360
    truth = tuple(1000*x for x in geo.unit(true_angle))
    def violation(delta):
        return max((a*truth[0]+b*truth[1]-c)/math.hypot(a,b)
                   for a,b,c in geo.bearing_planes((0,0), displayed, delta=delta))
    assert violation(1.) > 0 and violation(1.005) <= 0
    base_planes = geo.bearing_planes((0,0), 0., delta=1.005) + [(1,0,1500),(-1,0,0)]
    once = geo.halfplane_region(base_planes)
    repeated = geo.halfplane_region(base_planes + geo.bearing_planes((0,0),0.,delta=1.005)*9)
    assert abs(once['diameter_m']-repeated['diameter_m']) < 1e-7
    source = (1800.,0.)
    stations = [(0.,0.)] + [tuple(1125*x for x in geo.unit(k*60)) for k in range(6)]
    close = [q for q in stations if math.dist(q,source) <= 1000]
    visible = [q for q in close if q[0]-source[0] >= 0]
    assert close and not visible
    grid_bound = math.hypot(15.,10.)
    assert grid_bound < 19.99 and 1500*math.sin(math.radians(1.005))-20 < 10
    choices = {k:q2.select_second_point(preference=k) for k in q2.CHOICES}
    save('几何反例与边界核验.json', dict(passed=True,
        diameter_counterexample=dict(diameter_m=diameter, enclosing_center_m=center,
                                     enclosing_radius_m=radius, guaranteed_20m_clear=False),
        rounding_counterexample=dict(true_bearing_deg=true_angle, fixed_error_deg=fixed_error,
                                     displayed_deg=displayed, exclusion_violation_at_1deg_m=violation(1.),
                                     exclusion_violation_at_1_005deg_m=violation(1.005)),
        repeated_fixed_bearing=dict(single_diameter_m=once['diameter_m'], ten_repeats_diameter_m=repeated['diameter_m']),
        q3_layout_directional_counterexample=dict(source_m=source, direction_deg=0,
                                                radius_m=1000, nearby_stations_m=close,
                                                visible_nearby_stations_m=visible),
        final_backup=dict(point_count=153, nearest_point_bound_m=grid_bound,
                          requires_legal_feedback_and_sufficient_resources=True), q2_safe_candidates=choices))


def main():
    start = time.monotonic()
    watched = [ROOT/'我的论文.docx', ROOT/'我的论文.pdf', SUPPORT/'数据/benchmark.json.gz',
               SUPPORT/'数据/参数/问题三四_正式算法选型.json'] + sorted(SUPPORT.glob('*.py'))
    before = {str(p.relative_to(ROOT)):digest(p) for p in watched}
    stats = statistics()
    formal = formal_ledgers()
    counterexamples()
    after = {str(p.relative_to(ROOT)):digest(p) for p in watched}
    assert before == after
    save('补充核验总览.json', dict(passed=True, date='2026-10-06', timezone='Asia/Shanghai',
                               python=sys.version, numpy=np.__version__, executable=sys.executable,
                               elapsed_s=time.monotonic()-start, source_hashes=before,
                               original_files_unchanged=True, network_requests=0,
                               official_new_runs=0, formal_api_records_recalculated=1171,
                               archived_benchmark_rows_recalculated=1008,
                               bootstrap_reps=BOOTSTRAP_REPS,
                               scope='New defense-preparation analysis, not competition-era evidence; geometry/Q2/theory reruns have separate outputs.'))
    print(json.dumps(dict(statistics=stats, formal_records=sum(r['records'] for r in formal),
                          passed=True, original_files_unchanged=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
