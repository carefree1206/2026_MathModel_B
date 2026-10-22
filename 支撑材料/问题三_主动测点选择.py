"""仅依观测，为全向源选择具有接收证书的探针。
角度区间是完整响应外包，不是未来观测的抽样；每个区间先扩张角楔再界定后验。只在有限候选中作启发式费用比较，不是全局连续极小极大求解。"""
import math

from 问题一_定位区域与包围圆 import EPS, bearing_planes, clip, diameter, distance, point_region_distance


def _axes(poly):
    _, pair = diameter(poly)
    length = distance(*pair)
    if length <= EPS:
        return (1., 0.), (0., 1.)
    u = ((pair[1][0]-pair[0][0])/length, (pair[1][1]-pair[0][1])/length)
    return u, (-u[1], u[0])


def _box_radius(poly, axes):
    spans = []
    for u in axes:
        values = [p[0]*u[0]+p[1]*u[1] for p in poly]
        spans.append(max(values)-min(values))
    return .5*math.hypot(*spans) + 10*EPS


def bearing_support(poly, point, delta):
    """包含全部可能示向读数的连续角度区间。"""
    if point_region_distance(point, poly) <= 10*EPS:
        return 0., 360.
    angles = sorted(math.degrees(math.atan2(p[1]-point[1], p[0]-point[0])) % 360
                    for p in poly)
    gaps = [((angles[(i+1) % len(angles)]-a) % 360, i)
            for i, a in enumerate(angles)]
    gap, index = max(gaps)
    # 单点只对应一条射线，不覆盖整周角度。
    span = 0. if len(angles) == 1 else 360.-gap
    start = angles[(index+1) % len(angles)]
    return start-delta, start+span+delta


def posterior_radius_bound(poly, point, delta=1.005, bin_width_deg=2., prior_radius=None):
    """为全部未来正常示向及近距响应计算包围半径上界。
    区间内任一示向角楔都被中心示向加区间半宽的角楔包含；与当前域求交后用矩形包围圆界定。各区间与5米近距圆的最大值覆盖连续响应空间，旧包围圆可继续收紧上界。无信号不在该界内，接收保证需另查。"""
    if not poly or not 0 < bin_width_deg <= 30 or not 0 < delta < 45:
        raise ValueError('Invalid polygon or angular interval width')
    axes = _axes(poly)
    start, stop = bearing_support(poly, point, delta)
    count = max(1, int(math.ceil((stop-start)/bin_width_deg)))
    width = (stop-start)/count
    bound = min(5., prior_radius) if prior_radius is not None else 5.
    nonempty = 0
    for i in range(count):
        beta = start+(i+.5)*width
        region = list(poly)
        for plane in bearing_planes(point, beta, delta+.5*width+1e-9):
            region = clip(region, plane)
        if not region:
            continue
        nonempty += 1
        a = math.radians(beta)
        rotated = ((math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a)))
        radius = min(_box_radius(region, axes), _box_radius(region, rotated))
        if prior_radius is not None:
            radius = min(radius, prior_radius)
        bound = max(bound, radius)
    return bound, dict(interval_count=count, nonempty_intervals=nonempty,
                       reported_bearing_interval_deg=[start, stop],
                       actual_max_bin_width_deg=width)


def choose_probe(track, position, config):
    """返回候选点和诊断；不适用时返回空点与原因。
    角度分箱默认2°，剩余不确定性惩罚默认60秒。该透明评分只比较候选，不代表预测或保证的完整结束时间。"""
    if config.get('problem_scope') != 'omni':
        return None, {'status': 'requires_omni_scope'}
    if track.cleared or track.near is not None or track.inconsistent or not track.poly or not track.circle:
        return None, {'status': 'track_not_eligible'}
    options = config.get('policy_options', {})
    bin_width = options.get('active_probe_bin_deg', 2.)
    penalty = options.get('active_probe_penalty_s', 60.)
    if (isinstance(bin_width, bool) or not isinstance(bin_width, (int, float)) or
            not math.isfinite(bin_width) or not .25 <= bin_width <= 10):
        raise ValueError('active_probe_bin_deg must be in [0.25,10]')
    if (isinstance(penalty, bool) or not isinstance(penalty, (int, float)) or
            not math.isfinite(penalty) or not 0 <= penalty <= 1000):
        raise ValueError('active_probe_penalty_s must be in [0,1000]')
    center, radius = track.circle
    target_radius = 20.-config['clearance_margin_m']
    if radius <= target_radius:
        return None, {'status': 'already_certified_clear'}
    u, v = _axes(track.poly)
    points = [tuple(position), tuple(center)]
    for offset in (25., 50., 100., 200., 400., 600.):
        points.extend((center[0]+sign*offset*v[0], center[1]+sign*offset*v[1])
                      for sign in (-1, 1))
    # 当多边形主轴
    # 已偏离首测示向时，仍将旧启发式保留在候选中。
    if track.first:
        a = math.radians(track.first[1]+90)
        offset = options.get('refine_offset_m', 100.)
        points.extend((center[0]+sign*offset*math.cos(a), center[1]+sign*offset*math.sin(a))
                      for sign in (-1, 1))
    candidates = []
    rejected = 0
    for point in sorted(set(points)):
        farthest = max(distance(point, p) for p in track.poly)
        if farthest > 1000.-1e-5:
            rejected += 1
            continue
        bound, details = posterior_radius_bound(track.poly, point, config['angle_bound_deg'],
                                                bin_width, radius)
        move = distance(position, point)
        score = move/5.+5.+penalty*max(0., bound/target_radius-1.)
        candidates.append(dict(point=point, farthest_vertex_m=farthest,
                               guaranteed_reception=True, radius_upper_bound_m=bound,
                               one_probe_clear_certificate=bound <= target_radius,
                               movement_m=move, heuristic_score_s=score, **details))
    if not candidates:
        return None, {'status': 'no_reception_certified_candidate', 'rejected_count': rejected}
    best = min(candidates, key=lambda c: (c['heuristic_score_s'], c['radius_upper_bound_m'],
                                         c['movement_m'], c['point']))
    return best['point'], dict(status='selected', method='interval_enclosure_active_probe',
                               candidate_count=len(candidates), rejected_count=rejected,
                               prior_radius_m=radius, penalty_s=penalty,
                               selected=best, candidates=candidates)
