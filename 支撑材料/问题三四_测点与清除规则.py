"""仅依观测的可选调度规则，不依赖模拟器。"""
import math

from 问题三四_巡检点与路线生成 import two_opt_open
from 问题一_定位区域与包围圆 import distance, unit, point_region_distance


def validate_options(config):
    options = config.get('policy_options', {})
    allowed = {'early_detour_m', 'clear_order', 'refine_steps', 'refine_offset_m',
               'opportunistic', 'dynamic_scan', 'safe_clear_shift', 'failed_probe_threshold',
               'refine_policy', 'active_probe_bin_deg', 'active_probe_penalty_s',
               'iterative_probe_rounds', 'pursue_detour_m', 'shared_clear', 'count_stop_unsettled'}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError('Unknown policy options')
    if options and config['strategy'] != 'geometry':
        raise ValueError('Policy options require geometry')
    if type(options.get('shared_clear', False)) is not bool:
        raise ValueError('shared_clear must be boolean')
    limit = options.get('count_stop_unsettled')
    if limit is not None and (type(limit) is not int or not 0 <= limit <= 16):
        raise ValueError('count_stop_unsettled must be zero to sixteen, or null')
    if options.get('refine_policy', 'lateral') not in ('lateral', 'active_interval'):
        raise ValueError('Unknown refinement policy')
    if options.get('refine_policy') == 'active_interval' and config.get('problem_scope') != 'omni':
        raise ValueError('Active interval refinement requires explicit omni scope')
    for key, default, low, high in (('active_probe_bin_deg', 2, .25, 10),
                                   ('active_probe_penalty_s', 60, 0, 1000),
                                   ('pursue_detour_m', 0, 0, 1000)):
        value = options.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid '+key)
    rounds = options.get('iterative_probe_rounds', 0)
    if type(rounds) is not int or not 0 <= rounds <= 6:
        raise ValueError('Iterative reprobe supports zero to six rounds')
    if options.get('pursue_detour_m', 0) and (config.get('problem_scope') != 'omni' or not options.get('refine_steps', 0)):
        raise ValueError('Early pursuit requires omni scope and enabled refinement')
    threshold = options.get('failed_probe_threshold', 0)
    if type(threshold) is not int or not 0 <= threshold <= 153:
        raise ValueError('Invalid failed-probe threshold')
    d = options.get('early_detour_m', 0)
    if isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d) or not 0 <= d <= 1000:
        raise ValueError('Invalid early detour budget')
    if options.get('clear_order', 'greedy') not in ('greedy', 'two_opt', 'exact12'):
        raise ValueError('Unknown clear order')
    n = options.get('refine_steps', 0)
    if type(n) is not int or not 0 <= n <= 2:
        raise ValueError('Refinement supports zero, one or two probes')
    r = options.get('refine_offset_m', 100)
    if isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) or not 20 <= r <= 500:
        raise ValueError('Invalid refinement offset')
    if type(options.get('safe_clear_shift', False)) is not bool:
        raise ValueError('safe_clear_shift must be boolean')
    if type(options.get('dynamic_scan', False)) is not bool:
        raise ValueError('dynamic_scan must be boolean')
    if type(options.get('opportunistic', False)) is not bool:
        raise ValueError('opportunistic must be boolean')


def settled(track, margin):
    return track.cleared or track.near is not None or bool(
        track.circle is not None and track.circle[1] <= 20-margin)


def ordered_targets(tracks, start, target):
    """近邻初始化后作开放2-opt，坐标重合时仍保留不同任务身份。"""
    remaining = list(tracks)
    greedy = []
    position = start
    while remaining:
        t = min(remaining, key=lambda t: (distance(position, target(t)), t.channel))
        remaining.remove(t)
        greedy.append(t)
        position = target(t)
    buckets = {}
    points = []
    for t in greedy:
        p = (target(t)[0]-start[0], target(t)[1]-start[1])
        points.append(p)
        buckets.setdefault(p, []).append(t)
    return [buckets[p].pop(0) for p in two_opt_open(points)]


def refine(session, track, config, events):
    """在估计中心两侧取探针，再保留继承的后备。
    这是名义交会角启发式，不能保证定向源接收；探测前固定中心以约束额外行走。"""
    options = config.get('policy_options', {})
    if not options.get('refine_steps', 0) or settled(track, config['clearance_margin_m']) or not track.circle or track.inconsistent:
        return
    if options.get('refine_policy') == 'active_interval':
        from 问题三_主动测点选择 import choose_probe
        visited = set()
        for _ in range(options['refine_steps']):
            point, diagnostics = choose_probe(track, session.position, config)
            if point is None or point in visited:
                break
            visited.add(point)
            before = track.circle[1]
            response = session.measure(point, track.channel)
            track.observe(point, response, config['angle_bound_deg'])
            events.append(dict(channel=track.channel, method='active_refinement',
                position=point, result=response['measure_result'], radius_before_m=before,
                radius_after_m=track.circle[1] if track.circle else None,
                selection={k:v for k,v in diagnostics.items() if k != 'candidates'}))
            if settled(track, config['clearance_margin_m']) or track.inconsistent:
                break
        return
    center = track.circle[0]
    u = unit(track.first[1]+90)
    r = options.get('refine_offset_m', 100)
    points = [(center[0]+sign*r*u[0], center[1]+sign*r*u[1]) for sign in (1, -1)]
    points.sort(key=lambda p: (distance(session.position, p), p))
    for p in points[:options['refine_steps']]:
        before = track.circle[1] if track.circle else None
        response = session.measure(p, track.channel)
        track.observe(p, response, config['angle_bound_deg'])
        events.append(dict(channel=track.channel, method='local_refinement',
                           position=p, result=response['measure_result'], radius_before_m=before,
                           radius_after_m=track.circle[1] if track.circle else None))
        if settled(track, config['clearance_margin_m']) or track.inconsistent:
            break


def exact_targets(tracks, start, target):
    """点身份不超过12个时精确求名义开放路线，否则用2-opt改进。"""
    tracks = sorted(tracks, key=lambda t: t.channel)
    n = len(tracks)
    if n > 12:
        return ordered_targets(tracks, start, target)
    if not n:
        return []
    points = [target(t) for t in tracks]
    dp = {(1 << j, j): (distance(start, points[j]), -1) for j in range(n)}
    for mask in range(1, 1 << n):
        for j in range(n):
            if not mask & (1 << j) or mask == 1 << j:
                continue
            prev = mask ^ (1 << j)
            dp[mask, j] = min((dp[prev, k][0] + distance(points[k], points[j]), k)
                             for k in range(n) if prev & (1 << k))
    mask = (1 << n)-1
    j = min(range(n), key=lambda j: (dp[mask, j][0], j))
    order = []
    while mask:
        order.append(tracks[j]); old = j
        j = dp[mask, j][1]; mask ^= 1 << old
    return list(reversed(order))


def safe_clear_point(track, position, config):
    """在保证清除圆的内部充分域中选择最近点，不使用隐藏真值。"""
    if track.near is not None:
        center, radius = track.near, 5.
    elif track.circle is not None:
        center, radius = track.circle
    else:
        return track.first[0]
    slack = max(0., 20-config['clearance_margin_m']-radius)
    length = distance(center, position)
    if not config.get('policy_options', {}).get('safe_clear_shift', False) or not length:
        return center
    factor = min(slack, length)/length
    return (center[0]+factor*(position[0]-center[0]), center[1]+factor*(position[1]-center[1]))


def iterative_reprobe(session, track, config, events):
    """清除失败后，交替在原地测向并移到新中心。
    轮数受配置限制，原有有限后备仍保留。无信号不用于排除位置，定向源也如此；本策略希望缩小定位域，但不保证每轮收缩。"""
    rounds = config.get('policy_options', {}).get('iterative_probe_rounds', 0)
    for index in range(rounds):
        if track.cleared or track.inconsistent or not track.poly or not track.circle:
            break
        point = session.position
        before = track.circle[1]
        response = session.measure(point, track.channel)
        track.observe(point, response, config['angle_bound_deg'])
        events.append(dict(channel=track.channel, method='iterative_probe_measure',
            round=index+1, position=point, result=response['measure_result'],
            radius_before_m=before, radius_after_m=track.circle[1] if track.circle else None))
        if response['measure_result'] == 'no_signal' or track.inconsistent or not track.circle:
            break
        target = safe_clear_point(track, point, config)
        if distance(point, target) <= 1e-5 and track.near is None:
            break
        guaranteed = settled(track, config['clearance_margin_m'])
        track.cleared = session.clear(target, track.channel)['clear_result'] == 'success'
        track.inconsistent |= guaranteed and not track.cleared
        events.append(dict(channel=track.channel, method='iterative_probe_clear',
            round=index+1, guaranteed=guaranteed, success=track.cleared,
            radius_m=track.circle[1]))


def opportunistic_clear(session, tracks, config, events, attempted):
    """在成功清除位置试清其他几何上可能同处的已知频道。
    整域未被光学圆包含时属于非保证试探；没有额外移动，每个频道和位置组合只试一次，失败圆不用于收缩凸多边形。成功位置至多16个。"""
    if not config.get('policy_options', {}).get('shared_clear', False):
        return
    point = session.position
    for track in sorted(tracks, key=lambda t:t.channel):
        if track.cleared or track.inconsistent or not track.observations:
            continue
        key = (track.channel, point)
        if key in attempted:
            continue
        if track.poly:
            if point_region_distance(point, track.poly) > 20.+1e-5:
                continue
            guaranteed = max(distance(point,p) for p in track.poly) <= 20.-config['clearance_margin_m']
        elif track.near is not None:
            if distance(point,track.near) > 25.+1e-5:
                continue
            guaranteed = distance(point,track.near)+5 <= 20.-config['clearance_margin_m']
        else:
            continue
        attempted.add(key)
        track.cleared = session.clear(point,track.channel)['clear_result'] == 'success'
        track.inconsistent |= guaranteed and not track.cleared
        events.append(dict(channel=track.channel, method='shared_position_clear',
            position=point, guaranteed=guaranteed, success=track.cleared))
