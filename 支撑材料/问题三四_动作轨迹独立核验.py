"""仅用标准库独立核验物理、费用与退出。
不导入模拟器、策略、求解几何或已有核验实现。真值仅在策略结束后读取；不存在证书通过矩形细分及独立凸包计算核对。"""
import ast
import copy
import gzip
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path


def _read(value):
    if not isinstance(value, (str, Path)):
        return value
    path = Path(value)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig') as stream:
        if '.jsonl' in path.name:
            return [json.loads(line) for line in stream if line.strip()]
        return json.load(stream)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _norm(point):
    return math.sqrt(point[0] * point[0] + point[1] * point[1])


def _distance(a, b):
    return _norm((a[0] - b[0], a[1] - b[1]))


def _turn(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _hull(points):
    points = sorted(set(map(tuple, points)))
    if len(points) < 3:
        return points
    lower, upper = [], []
    for target, ordered in ((lower, points), (upper, reversed(points))):
        for point in ordered:
            while len(target) > 1 and _turn(target[-2], target[-1], point) <= 0:
                target.pop()
            target.append(point)
    return lower[:-1] + upper[:-1]


def _point_polygon_violation(point, polygon):
    """独立计算点到各支撑直线外侧的距离。"""
    # 规范化同时处理重复顶点和共线退化。
    polygon = _hull(polygon)
    if len(polygon) == 1:
        return _distance(point, polygon[0])
    if len(polygon) == 2:
        a, b = polygon
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx * dx + dy * dy
        fraction = max(0.0, min(1.0, ((point[0] - a[0]) * dx +
                                    (point[1] - a[1]) * dy) / length_sq)) if length_sq else 0.0
        return _distance(point, (a[0] + fraction * dx, a[1] + fraction * dy))
    signs = [_turn(a, b, point) / max(1e-30, _distance(a, b))
             for a, b in zip(polygon, polygon[1:] + polygon[:1])]
    return max(0.0, min(-min(signs), max(signs)))


def _pair_certificate_errors(pair):
    """在整个输入多边形上核验双阴性推论。"""
    errors = []
    try:
        origin = tuple(pair['origin'])
        bearing, forward = pair['bearing_deg'], pair['forward_m']
        polygon = [tuple(p) for p in pair['source_polygon_before']]
        probes = [tuple(p) for p in pair['points']]
        if len(probes) != 2 or not polygon or forward <= 0:
            return ['invalid_pair_certificate_shape']
        ux, uy = math.cos(math.radians(bearing)), math.sin(math.radians(bearing))
        def transform(point):
            dx, dy = point[0] - origin[0], point[1] - origin[1]
            return dx * ux + dy * uy, -dx * uy + dy * ux
        local, probe_local = list(map(transform, polygon)), list(map(transform, probes))
        if any(abs(p[0] - forward) > 1e-6 for p in probe_local):
            errors.append('pair_probes_not_on_transverse_line')
        lower, upper = sorted(p[1] for p in probe_local)
        if lower >= upper:
            errors.append('pair_probes_not_distinct')
        if any(_distance(p, q) > 1000 - 1e-7 for p in probes for q in polygon):
            errors.append('pair_distance_not_safe_for_entire_polygon')
        far_vertices = [p for p in local if p[0] >= forward]
        for a, b in zip(local, local[1:] + local[:1]):
            if min(a[0], b[0]) < forward < max(a[0], b[0]):
                fraction = (forward - a[0]) / (b[0] - a[0])
                far_vertices.append((forward, a[1] + fraction * (b[1] - a[1])))
        if not far_vertices:
            errors.append('pair_empty_far_cap')
        if any(not lower - 1e-7 <= forward * y / x <= upper + 1e-7
               for x, y in far_vertices):
            errors.append('pair_does_not_bracket_entire_far_cap')
        expected = ux, uy, ux * origin[0] + uy * origin[1] + forward
        if len(pair['plane']) != 3 or any(abs(a - b) > 1e-7 for a, b in zip(pair['plane'], expected)):
            errors.append('pair_clipping_plane_mismatch')
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        errors.append('malformed_pair_certificate')
    return errors


def audit_clear_certificate(certificate):
    """不依赖原生成器，重建并检查完整矩形光学覆盖。"""
    errors, centers = [], []
    try:
        c = certificate
        origin, u, v = [tuple(c[k]) for k in ('origin', 'axis_u', 'axis_v')]
        polygon = [tuple(p) for p in c['source_polygon_before']]
        bounds = c['bounds_local']
        if (any(len(p) != 2 or not all(_finite(x) for x in p) for p in [origin, u, v] + polygon)
                or not polygon or len(bounds) != 4 or not all(_finite(x) for x in bounds)):
            return dict(passed=False, errors=['invalid_clear_cover_coordinates'], points=[])
        if (abs(_norm(u) - 1) > 1e-10 or abs(_norm(v) - 1) > 1e-10 or
                abs(u[0] * v[0] + u[1] * v[1]) > 1e-10):
            errors.append('clear_cover_axes_not_orthonormal')
        x0, x1, y0, y1 = bounds
        nx, ny = c['columns'], c['rows']
        if (type(nx) is not int or type(ny) is not int or min(nx, ny) < 1 or nx * ny > 1000000):
            return dict(passed=False, errors=errors + ['invalid_clear_cover_grid_count'], points=[])
        width, height = x1 - x0, y1 - y0
        if width <= 0 or height <= 0:
            errors.append('nonpositive_clear_cover_rectangle')
        local = [((p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1],
                  (p[0]-origin[0])*v[0]+(p[1]-origin[1])*v[1]) for p in polygon]
        if any(not (x0-1e-9 <= x <= x1+1e-9 and y0-1e-9 <= y <= y1+1e-9) for x, y in local):
            errors.append('clear_cover_rectangle_excludes_polygon')
        padding = c['rectangle_padding_m']
        if not _finite(padding) or padding <= 0:
            errors.append('invalid_clear_cover_padding')
        else:
            expected_bounds = (min(p[0] for p in local)-padding, max(p[0] for p in local)+padding,
                               min(p[1] for p in local)-padding, max(p[1] for p in local)+padding)
            if max(abs(a-b) for a,b in zip(bounds, expected_bounds)) > 1e-7:
                errors.append('clear_cover_bounds_not_padded_extrema')
        dx, dy = width / nx, height / ny
        half = math.sqrt(dx*dx + dy*dy) / 2
        radius = c['certified_radius_m']
        if not _finite(radius) or not 0 < radius <= 19.99 or half > radius + 1e-9:
            errors.append('clear_cover_cell_exceeds_optical_radius')
        checks = [('cell_width_m', dx), ('cell_height_m', dy), ('cell_half_diagonal_m', half)]
        if any(not _finite(c[k]) or abs(c[k]-value) > 1e-8 for k,value in checks):
            errors.append('clear_cover_cell_geometry_mismatch')
        if c['point_count'] != nx*ny or c['removed_cells'] != 0:
            errors.append('clear_cover_missing_grid_cells')
        if c['snake_axis'] not in ('rows', 'columns') or type(c['flip_x']) is not bool or type(c['flip_y']) is not bool:
            return dict(passed=False, errors=errors + ['invalid_clear_cover_snake'], points=[])
        inner_count = nx if c['snake_axis'] == 'rows' else ny
        for rank in range(nx*ny):
            outer, inner = divmod(rank, inner_count)
            if outer % 2: inner = inner_count - 1 - inner
            j, k = (inner, outer) if c['snake_axis'] == 'rows' else (outer, inner)
            j = nx-1-j if c['flip_x'] else j
            k = ny-1-k if c['flip_y'] else k
            x, y = x0+(j+.5)*dx, y0+(k+.5)*dy
            centers.append((origin[0]+u[0]*x+v[0]*y, origin[1]+u[1]*x+v[1]*y))
        start = tuple(c['start'])
        if len(start) != 2 or not all(_finite(x) for x in start):
            errors.append('invalid_clear_cover_start')
        else:
            length = math.fsum(_distance(a, b) for a,b in zip([start]+centers[:-1], centers))
            if abs(length-c['complete_visit_length_m']) > 1e-6:
                errors.append('clear_cover_complete_route_length_mismatch')
            if abs(length/5+3*len(centers)-c['complete_failure_cost_s']) > 1e-6:
                errors.append('clear_cover_nominal_cost_mismatch')
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        errors.append('malformed_clear_cover_certificate')
    return dict(passed=not errors, errors=errors, points=centers)


@lru_cache(maxsize=4096)
def _continuous_cover(points, problem, max_depth=22, node_limit=250000):
    """对完整半径1800米闭圆域作连续覆盖认证。
    Q3要求整格处于带余量的接收圆内；Q4要求整格四角位于距整格均不超过1000米的站点凸包内。检查包含域外部分在内的全部矩形角点。预算用尽只返回未认证。"""
    points = tuple(sorted(set(points)))
    if not points:
        return dict(passed=False, cells=0, deepest=0, reason='no_measurements')
    stack = [(-1800.0, 1800.0, -1800.0, 1800.0, 0)]
    visited = accepted = pruned = deepest = 0
    while stack:
        x0, x1, y0, y1, depth = stack.pop()
        visited += 1
        deepest = max(deepest, depth)
        dx = max(x0, -x1, 0.0)
        dy = max(y0, -y1, 0.0)
        # 容差取外向，避免误删与圆域边界相交的格。
        if dx * dx + dy * dy > (1800.0 + 1e-7) ** 2:
            pruned += 1
            continue
        corners = ((x0, y0), (x0, y1), (x1, y0), (x1, y1))
        receivers = [p for p in points if
                     max(_distance(p, q) for q in corners) <= 1000.0 - 1e-7]
        covered = bool(receivers) if problem == 'q3' else False
        if problem == 'q4' and len(receivers) >= 3:
            hull = _hull(receivers)
            covered = len(hull) >= 3 and all(
                _turn(a, b, q) >= 1e-7 * max(1.0, _distance(a, b))
                for a, b in zip(hull, hull[1:] + hull[:1]) for q in corners)
        if covered:
            accepted += 1
            continue
        if depth >= max_depth or visited >= node_limit:
            return dict(passed=False, cells=visited, accepted_cells=accepted,
                        pruned_cells=pruned, deepest=deepest,
                        reason='subdivision_inconclusive',
                        unresolved_rectangle=[x0, x1, y0, y1])
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        stack.extend((a, b, c, d, depth + 1) for a, b in ((x0, xm), (xm, x1))
                     for c, d in ((y0, ym), (ym, y1)))
    return dict(passed=True, cells=visited, accepted_cells=accepted,
                pruned_cells=pruned, deepest=deepest,
                method='closed_disk_rectangle_cover' if problem == 'q3'
                else 'closed_disk_rectangle_receiver_hulls')


def continuous_cover(points, problem):
    if problem not in ('q3', 'q4'):
        raise ValueError('problem must be q3 or q4')
    return copy.deepcopy(_continuous_cover(tuple(sorted(set(tuple(p) for p in points))), problem))


def _case_errors(case):
    errors = []
    sources = case.get('sources')
    if not isinstance(sources, list):
        return ['sources_not_a_list']
    if case.get('case_kind', 'full') != 'unit' and not 10 <= len(sources) <= 16:
        errors.append('source_count_outside_10_to_16')
    channels = []
    for source in sources:
        channel = source.get('channel')
        if type(channel) is not int or not 1 <= channel <= 20 or channel in channels:
            errors.append('invalid_or_duplicate_source_channel')
        channels.append(channel)
        values = [source.get(k) for k in ('x_m', 'y_m', 'reception_radius_m')]
        if not all(_finite(v) for v in values):
            errors.append('nonfinite_source_geometry')
            continue
        if _norm(values[:2]) > 1800 + 1e-7:
            errors.append('source_outside_disk')
        if not 1000 <= values[2] <= 1500:
            errors.append('reception_radius_outside_bounds')
        angle = source.get('orientation_deg')
        if angle is not None and (not _finite(angle) or not 0 <= angle < 360):
            errors.append('invalid_source_orientation')
    return errors


def audit_records(records, case, solution=None, *, problem=None, clock_model='float',
                  check_absence=True):
    """核验全部观测、失败动作及最终退出。
    题号应取自预先固定的实验配置，不能由策略推断。未显式提供时优先采用场景元数据，否则按较保守的Q4处理。关闭不存在核验时，结论仅限物理反馈。"""
    records, case, solution = _read(records), _read(case), _read(solution)
    if clock_model not in ('float', 'microsecond'):
        raise ValueError('unsupported clock model')
    problem = problem or case.get('problem') or 'q4'
    problem = str(problem).lower()
    if problem not in ('q3', 'q4'):
        raise ValueError('problem must be q3 or q4')
    errors = [dict(record=None, kind=kind) for kind in _case_errors(case)]
    if errors:
        return dict(passed=False, errors=errors, all_cleared=False,
                    scope='invalid_case', virtual_s=None, costs={})
    truth = {source['channel']: source for source in case['sources']}
    if problem == 'q3' and any(s.get('orientation_deg') is not None for s in truth.values()):
        errors.append(dict(record=None, kind='directional_source_in_q3'))
    position, measure_channel = (0.0, 0.0), 1
    entered = exited = False
    cleared, observed, negative_points, fixed_readings = set(), set(), {}, {}
    committed, pending = {}, {}
    costs = dict(move_m=0.0, move_s=0.0, measure_s=0, switch_s=0,
                 optical_s=0, laser_s=0, measures=0, clears=0, successes=0)
    ideal = last_clock = floating_budget = 0.0
    positive_moves = rejected = duplicates = boundary_checks = measurements = 0
    maximum_step_error = maximum_total_error = maximum_angle_error = 0.0
    accepted_count = 0
    measure_trace, action_trace = [], []

    def error(index, kind, **details):
        errors.append(dict(record=index, kind=kind, **details))

    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            error(index, 'invalid_record')
            continue
        endpoint, request, response = row.get('endpoint'), row.get('request'), row.get('response')
        if not isinstance(request, dict):
            error(index, 'invalid_request')
            continue
        rid = request.get('request_id')
        if not isinstance(rid, str) or not 1 <= len(rid.encode('utf-8')) <= 128:
            error(index, 'invalid_request_id')
            continue
        if row.get('request_id', rid) != rid:
            error(index, 'request_id_log_mismatch')
        signature = json.dumps([endpoint, request], sort_keys=True, allow_nan=False)
        if isinstance(response, dict) and response.get('accepted') is False:
            rejected += 1
            continue
        if not isinstance(response, dict) or response.get('accepted') is not True:
            if rid in pending and pending[rid] != signature:
                error(index, 'unconfirmed_payload_changed')
            pending[rid] = signature
            continue
        if row.get('http_status') != 200:
            error(index, 'accepted_without_http_200')
        if row.get('accepted', True) is not True:
            error(index, 'accepted_log_mismatch')
        if rid in committed:
            duplicates += 1
            if committed[rid] != (signature, response):
                error(index, 'idempotent_response_or_payload_changed')
            continue
        if rid in pending:
            if pending[rid] != signature:
                error(index, 'unconfirmed_payload_changed')
            del pending[rid]
        if pending:
            error(index, 'new_action_before_pending_resolved', ids=sorted(pending))
        committed[rid] = signature, copy.deepcopy(response)
        accepted_count += 1
        allowed = {'arena_id', 'robot_id', 'request_id'}
        if endpoint in ('/measure', '/clear'):
            allowed |= {'position', 'channel'}
        if set(request) != allowed or request.get('arena_id') != 'default':
            error(index, 'invalid_accepted_request_schema')
        increment = move = 0.0
        if endpoint == '/enter':
            if entered or exited:
                error(index, 'invalid_enter_lifecycle')
            entered = True
        elif endpoint == '/exit':
            if not entered or exited:
                error(index, 'invalid_exit_lifecycle')
            if response.get('exit_reason') != 'user_exit':
                error(index, 'not_user_exit')
            exited = True
        elif endpoint in ('/measure', '/clear'):
            if not entered or exited:
                error(index, 'action_outside_active_session')
            p, channel = request.get('position'), request.get('channel')
            if (not isinstance(p, dict) or set(p) != {'x', 'y'} or
                    not all(_finite(v) and abs(v) <= 2000000 for v in p.values()) or
                    type(channel) is not int or not 1 <= channel <= 20):
                error(index, 'invalid_action_coordinates_or_channel')
                continue
            point = p['x'], p['y']
            action_trace.append(dict(endpoint=endpoint, channel=channel, point=point,
                                     start=position, response=copy.deepcopy(response), record=index))
            move = _distance(position, point)
            costs['move_m'] += move
            costs['move_s'] += move / 5
            increment += move / 5
            positive_moves += int(move > 0)
            position = point
            source = truth.get(channel) if channel not in cleared else None
            distance = _distance(point, (source['x_m'], source['y_m'])) if source else math.inf
            if endpoint == '/clear':
                result = response.get('clear_result')
                if result not in ('success', 'no_target_in_range'):
                    error(index, 'invalid_clear_result')
                success = result == 'success'
                if success and (not source or distance > 20 + 1e-7):
                    error(index, 'physically_impossible_clear_success', distance_m=distance if source else None)
                if not success and distance < 20 - 1e-7:
                    error(index, 'physically_impossible_clear_failure', distance_m=distance)
                if source and abs(distance - 20) <= 1e-7:
                    boundary_checks += 1
                costs['clears'] += 1
                costs['optical_s'] += 3
                costs['laser_s'] += 2 * success
                costs['successes'] += int(success)
                increment += 3 + 2 * success
                if success:
                    if channel in cleared:
                        error(index, 'duplicate_clear_success')
                    if source and distance <= 20 + 1e-7:
                        cleared.add(channel)
            else:
                measurements += 1
                measure_trace.append(dict(channel=channel, point=point,
                                          response=copy.deepcopy(response), record=index,
                                          already_cleared=channel in cleared))
                switch = int(measure_channel != channel)
                costs['measures'] += 1
                costs['measure_s'] += 5
                costs['switch_s'] += switch
                measure_channel = channel
                increment += 5 + switch
                result = response.get('measure_result')
                possible_visibility = certain_visibility = bool(source)
                if source:
                    radius = source['reception_radius_m']
                    possible_visibility = distance <= radius + 1e-7
                    certain_visibility = distance < radius - 1e-7
                    orientation = source.get('orientation_deg')
                    if orientation is not None and distance > 0:
                        receiver_angle = math.degrees(math.atan2(point[1] - source['y_m'], point[0] - source['x_m']))
                        gap = abs((receiver_angle - orientation + 180) % 360 - 180)
                        possible_visibility = possible_visibility and gap <= 90 + 1e-8
                        certain_visibility = certain_visibility and gap < 90 - 1e-8
                legal = set()
                if not certain_visibility:
                    legal.add('no_signal')
                if possible_visibility:
                    if distance <= 5 + 1e-7:
                        legal.add('near')
                    if distance >= 5 - 1e-7:
                        legal.add('direction')
                if possible_visibility != certain_visibility:
                    boundary_checks += 1
                if source and abs(distance - 5) <= 1e-7 and possible_visibility:
                    boundary_checks += 1
                if result not in legal:
                    error(index, 'illegal_measurement_class', actual=result, legal=sorted(legal), channel=channel)
                if result == 'no_signal':
                    negative_points.setdefault(channel, []).append(point)
                elif result in ('direction', 'near'):
                    observed.add(channel)
                if result == 'direction':
                    angle = response.get('svd_deg')
                    if not _finite(angle) or not 0 <= angle < 360:
                        error(index, 'invalid_bearing')
                    elif source:
                        if abs(angle * 100 - round(angle * 100)) > 1e-8:
                            error(index, 'bearing_not_rounded_to_two_decimals')
                        true_angle = math.degrees(math.atan2(source['y_m'] - point[1], source['x_m'] - point[0]))
                        difference = abs((angle - true_angle + 180) % 360 - 180)
                        maximum_angle_error = max(maximum_angle_error, difference)
                        if difference > 1.005 + 1e-10:
                            error(index, 'bearing_outside_error_bound', error_deg=difference)
                        key = channel, point
                        if key in fixed_readings and fixed_readings[key] != angle:
                            error(index, 'fixed_location_bearing_changed')
                        fixed_readings[key] = angle
        else:
            error(index, 'unknown_endpoint')
        ideal += increment
        floating = 64 * math.ulp(max(1.0, abs(ideal), abs(increment)))
        floating_budget += floating
        quantum = 1e-6 if clock_model == 'microsecond' else 0.0
        step_bound = floating + quantum * int(move > 0)
        total_bound = floating_budget + positive_moves * quantum
        clock = response.get('virtual_time_s')
        if not _finite(clock) or clock < 0:
            error(index, 'missing_or_invalid_clock')
        else:
            step_error, total_error = clock - last_clock - increment, clock - ideal
            maximum_step_error = max(maximum_step_error, abs(step_error))
            maximum_total_error = max(maximum_total_error, abs(total_error))
            if abs(step_error) > step_bound:
                error(index, 'step_clock_mismatch', error_s=step_error, tolerance_s=step_bound)
            if abs(total_error) > total_bound:
                error(index, 'total_clock_mismatch', error_s=total_error, tolerance_s=total_bound)
            last_clock = clock
        if ideal >= 360000:
            error(index, 'virtual_time_limit')
    if not entered:
        error(None, 'missing_enter')
    if not exited:
        error(None, 'missing_exit')
    if pending:
        error(None, 'unresolved_requests', ids=sorted(pending))
    uncleared = sorted(set(truth) - cleared)
    if uncleared:
        error(None, 'sources_not_cleared', channels=uncleared)
    absence_checks = {}
    polygon_checks = pair_checks = clear_cover_checks = clear_cover_cells = 0
    maximum_polygon_violation = 0.0
    declared_absent = []
    if solution is not None:
        if solution.get('geometry_inconsistencies'):
            error(None, 'reported_geometry_inconsistencies', channels=solution['geometry_inconsistencies'])
        original_events = list(solution.get('events', []))
        has_observation_events = any(event.get('method') == 'observe' for event in original_events)
        event_measure_index = 0
        first_bearings, prior_regions = {}, {}
        event_action_index = 0
        active_clear_cover = None
        for event_index, event in enumerate(original_events):
            channel = event.get('channel')
            action_event = has_observation_events and (event.get('method') == 'observe' or
                            (type(event.get('success')) is bool and 'position' in event))
            if active_clear_cover and event.get('method') != 'adaptive_clear_cell':
                error(None, 'clear_cover_prefix_ended_without_success', event=event_index,
                      channel=active_clear_cover['channel'])
                active_clear_cover = None
            if action_event:
                if event_action_index >= len(action_trace):
                    error(None, 'extra_action_event', event=event_index)
                else:
                    actual = action_trace[event_action_index]
                    expected_endpoint = '/measure' if event.get('method') == 'observe' else '/clear'
                    expected_result = actual['response'].get('clear_result') == 'success'
                    if (actual['endpoint'] != expected_endpoint or actual['channel'] != channel or
                            tuple(event['position']) != actual['point'] or
                            (expected_endpoint == '/clear' and event['success'] != expected_result)):
                        error(None, 'action_event_trace_mismatch', event=event_index)
                event_action_index += 1
            if event.get('guaranteed') is True and event.get('success') is False:
                error(None, 'guaranteed_clear_reported_failure', event=event_index, channel=channel)
            if event.get('method') == 'adaptive_clear_cell':
                clear_cover_cells += 1
                if active_clear_cover is None:
                    error(None, 'clear_cell_without_active_certificate', event=event_index)
                else:
                    active = active_clear_cover
                    prefix_index = active['visited']
                    if (channel != active['channel'] or prefix_index >= len(active['points']) or
                            _distance(tuple(event['position']), active['points'][prefix_index]) > 1e-7):
                        error(None, 'clear_cells_not_complete_snake_prefix', event=event_index)
                    active['visited'] += 1
                    if event.get('success') is True:
                        active_clear_cover = None
                    elif active['visited'] >= len(active['points']):
                        error(None, 'certified_clear_cover_all_cells_failed', event=event_index, channel=channel)
                        active_clear_cover = None
            if event.get('method') == 'adaptive_clear_cover':
                clear_cover_checks += 1
                certificate = event.get('certificate', {})
                value = audit_clear_certificate(certificate)
                for kind in value['errors']:
                    error(None, kind, event=event_index, channel=channel)
                if certificate.get('channel') != channel:
                    error(None, 'clear_cover_channel_mismatch', event=event_index)
                current_position = action_trace[event_action_index-1]['point'] if event_action_index else (0., 0.)
                if _distance(tuple(certificate.get('start', (math.inf, math.inf))), current_position) > 1e-7:
                    error(None, 'clear_cover_start_not_actual_position', event=event_index)
                before, prior = certificate.get('source_polygon_before'), prior_regions.get(channel)
                if (not before or not prior or
                        any(_point_polygon_violation(p, before) > 2e-5 for p in prior) or
                        any(_point_polygon_violation(p, prior) > 2e-5 for p in before)):
                    error(None, 'clear_cover_polygon_differs_from_actual_prior_region', event=event_index)
                active_clear_cover = dict(channel=channel, points=value['points'], visited=0)
            if event.get('method') == 'observe':
                if event_measure_index >= len(measure_trace):
                    error(None, 'extra_observation_event', event=event_index)
                else:
                    actual = measure_trace[event_measure_index]
                    if (channel != actual['channel'] or tuple(event['position']) != actual['point'] or
                            event.get('response') != actual['response'].get('measure_result')):
                        error(None, 'observation_event_action_mismatch', event=event_index)
                    if actual['response'].get('measure_result') == 'direction' and channel not in first_bearings:
                        first_bearings[channel] = actual
                event_measure_index += 1
            if event.get('method') == 'two_sided_negative_halfplane':
                pair_checks += 1
                pair = event.get('pair', {})
                for kind in _pair_certificate_errors(pair):
                    error(None, kind, event=event_index, channel=channel)
                first = first_bearings.get(channel)
                if (first is None or tuple(pair.get('origin', ())) != first['point'] or
                        pair.get('bearing_deg') != first['response'].get('svd_deg')):
                    error(None, 'pair_not_based_on_first_positive_observation', event=event_index)
                recent = measure_trace[max(0, event_measure_index-2):event_measure_index]
                if (len(recent) != 2 or len(pair.get('points', [])) != 2 or
                        any(r['channel'] != channel or r['already_cleared'] or
                            r['response'].get('measure_result') != 'no_signal' for r in recent) or
                        [r['point'] for r in recent] != [tuple(p) for p in pair.get('points', [])] or
                        [r['response'] for r in recent] != event.get('responses')):
                    error(None, 'pair_negative_responses_do_not_match_real_actions', event=event_index)
                before, prior = pair.get('source_polygon_before'), prior_regions.get(channel)
                if (not before or not prior or
                        any(_point_polygon_violation(p, before) > 2e-5 for p in prior) or
                        any(_point_polygon_violation(p, prior) > 2e-5 for p in before)):
                    error(None, 'pair_polygon_differs_from_actual_prior_region', event=event_index)
            if event.get('poly'):
                prior_regions[channel] = event['poly']
        if event_measure_index and event_measure_index != len(measure_trace):
            error(None, 'missing_observation_events', recorded=len(measure_trace), events=event_measure_index)
        if event_measure_index and event_action_index != len(action_trace):
            error(None, 'missing_action_events', recorded=len(action_trace), events=event_action_index)
        if active_clear_cover is not None:
            error(None, 'unfinished_certified_clear_cover', channel=active_clear_cover['channel'])
        region_rows = original_events
        region_rows += [dict(method='final_track_snapshot', channel=track.get('channel'),
                            poly=track.get('region_vertices'), circle=track.get('circle'),
                            inconsistent=track.get('inconsistent'))
                        for track in solution.get('tracks', [])]
        for event_index, event in enumerate(region_rows):
            if event.get('inconsistent'):
                error(None, 'inconsistent_track_snapshot', event=event_index, channel=event.get('channel'))
            polygon = event.get('poly')
            if polygon is None:
                continue
            channel = event.get('channel')
            if not polygon:
                # 未知频道没有定位域可为空；正测后定位域若变空，
                # 则在实际运行中记录几何矛盾。
                if event.get('response') in ('direction', 'near'):
                    error(None, 'empty_positive_observation_polygon', event=event_index, channel=channel)
                continue
            if channel not in truth:
                error(None, 'polygon_for_nonexistent_channel', event=event_index, channel=channel)
                continue
            if any(not isinstance(p, (tuple, list)) or len(p) != 2 or
                   not all(_finite(v) for v in p) for p in polygon):
                error(None, 'invalid_polygon_vertices', event=event_index)
                continue
            polygon = [tuple(p) for p in polygon]
            if len(polygon) >= 3:
                turns = [_turn(polygon[i-2], polygon[i-1], polygon[i]) for i in range(len(polygon))]
                if min(turns) < -1e-6 and max(turns) > 1e-6:
                    error(None, 'nonconvex_production_polygon', event=event_index, channel=channel)
            target = truth[channel]['x_m'], truth[channel]['y_m']
            violation = _point_polygon_violation(target, polygon)
            polygon_checks += 1
            maximum_polygon_violation = max(maximum_polygon_violation, violation)
            if violation > 2e-5:
                error(None, 'truth_excluded_by_observation_polygon', event=event_index,
                      channel=channel, violation_m=violation)
            circle = event.get('circle')
            if circle is not None:
                center, radius = circle
                if (len(center) != 2 or not all(_finite(v) for v in center) or
                        not _finite(radius) or radius < 0 or
                        any(_distance(center, p) > radius + 2e-5 for p in polygon)):
                    error(None, 'circle_does_not_enclose_polygon', event=event_index, channel=channel)
        certificate = solution.get('coverage_certificate', {})
        declared_cleared = solution.get('cleared_channels', certificate.get('cleared_channels'))
        declared_absent = solution.get('absent_channels', certificate.get('absent_channels', []))
        if declared_cleared is None or set(declared_cleared) != cleared or len(declared_cleared) != len(cleared):
            error(None, 'solution_cleared_channels_mismatch')
        if len(declared_absent) != len(set(declared_absent)):
            error(None, 'duplicate_absent_channel')
        if set(declared_absent) & observed:
            error(None, 'detected_channel_declared_absent', channels=sorted(set(declared_absent) & observed))
        if set(declared_absent) & set(truth):
            error(None, 'existing_channel_declared_absent')
        if len(cleared) < 16 and set(declared_absent) | cleared != set(range(1, 21)):
            error(None, 'not_all_channels_resolved')
        if solution.get('termination') in (None, 'incomplete', 'failed', 'error'):
            error(None, 'incomplete_solution_termination')
    else:
        declared_absent = sorted(set(range(1, 21)) - cleared)
    if check_absence and len(cleared) < 16:
        for channel in declared_absent:
            result = continuous_cover(negative_points.get(channel, []), problem)
            absence_checks[str(channel)] = result
            if not result['passed']:
                error(None, 'absence_continuous_coverage_unproven', channel=channel, detail=result)
    successes = len(cleared & set(truth))
    return dict(passed=not errors, errors=errors,
                scope='physical_timing_clearance_and_continuous_absence' if check_absence else 'physics_only_absence_not_checked',
                costs=costs, virtual_s=ideal, observed_virtual_s=last_clock,
                per_source_s=ideal / successes if successes else None,
                average_denominator='independently_verified_successful_clearances',
                initial_sources=len(truth), cleared_sources=successes,
                clearance_ratio=successes / len(truth) if truth else 1.0,
                all_cleared=not uncleared and cleared == set(truth),
                cleared_channels=sorted(cleared), uncleared_channels=uncleared,
                observed_channels=sorted(observed), entered=entered, exited=exited,
                final_measure_channel=measure_channel, logical_accepted_actions=accepted_count,
                rejected_records=rejected, idempotent_duplicate_records=duplicates,
                measurement_checks=measurements, near_boundary_checks=boundary_checks,
                maximum_angle_error_deg=maximum_angle_error,
                polygon_checks=polygon_checks,
                negative_pair_certificate_checks=pair_checks,
                adaptive_clear_certificate_checks=clear_cover_checks,
                adaptive_clear_cell_checks=clear_cover_cells,
                maximum_polygon_violation_m=maximum_polygon_violation,
                maximum_step_clock_error_s=maximum_step_error,
                maximum_total_clock_error_s=maximum_total_error,
                clock_model=clock_model, absence_checks=absence_checks,
                termination_basis='source_count_upper_bound_16' if len(cleared) == 16
                else 'continuous_absence_and_observed_clearances')


class ReplayTransport:
    """仅按观测确定性重放，不保存场景或源数据。
    应使用新Session和新策略，结束后检查全部请求已匹配。单局一致性支持该次执行未预知未来，但不替代静态访问检查或普遍性证明。"""
    def __init__(self, records):
        self._rows, self._index = [], 0
        seen = set()
        for row in _read(records):
            response = row.get('response', {})
            if row.get('http_status') == 200 and response.get('accepted') is True:
                rid = row['request']['request_id']
                if rid not in seen:
                    self._rows.append(copy.deepcopy(row))
                    seen.add(rid)

    def send(self, endpoint, request, timeout=None):
        if self._index >= len(self._rows):
            raise AssertionError('Policy issued an extra action after replay ended')
        row = self._rows[self._index]
        expected = {k: v for k, v in row['request'].items() if k != 'request_id'}
        actual = {k: v for k, v in request.items() if k != 'request_id'}
        if endpoint != row['endpoint'] or actual != expected:
            raise AssertionError('Replay action mismatch at %s: expected %r %r, got %r %r' %
                                 (self._index + 1, row['endpoint'], expected, endpoint, actual))
        self._index += 1
        return 200, copy.deepcopy(row['response'])

    def assert_complete(self):
        if self._index != len(self._rows):
            raise AssertionError('Policy stopped before consuming the complete observation trace')
        return dict(passed=True, replayed_actions=self._index, truth_supplied=False)


def audit_policy_source(paths):
    """保守扫描语法树；调用方需显式提供全部本地依赖。"""
    violations, files = [], []
    forbidden_attributes = {'_transport', 'transport', 'sources', 'case', 'reception_radius_m',
                            'orientation_deg', '__dict__', '__globals__', '__closure__', '__subclasses__'}
    forbidden_calls = {'open', 'eval', 'exec', '__import__', 'getattr', 'setattr',
                       'vars', 'globals', 'locals', 'compile', 'input'}
    forbidden_imports = {'os', 'sys', 'pathlib', 'pickle', 'inspect', 'importlib', 'requests',
                         'urllib', 'http', 'socket', 'subprocess', 'ctypes'}
    for value in paths:
        path = Path(value)
        raw = path.read_bytes()
        tree = ast.parse(raw.decode('utf-8-sig'), filename=str(path))
        files.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))
        for node in ast.walk(tree):
            reason = None
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                reason = 'forbidden_attribute:' + node.attr
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                # 以固定字段名读取公开观测状态不会
                # 暴露真值或执行动态反射；其他
                # 属性反射调用仍禁止，包括动态字段名。
                public_track_read = (node.func.id == 'getattr' and len(node.args) >= 2 and
                    isinstance(node.args[0], ast.Name) and node.args[0].id == 'track' and
                    isinstance(node.args[1], ast.Constant) and node.args[1].value in
                    ('inconsistent', 'cleared', 'poly', 'first'))
                if not public_track_read:
                    reason = 'dynamic_or_io_call:' + node.func.id
            elif isinstance(node, ast.Import):
                if any(n.name.split('.')[0] in forbidden_imports for n in node.names):
                    reason = 'io_or_introspection_import'
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if module.split('.')[0] in forbidden_imports or any(s in module for s in ('simulator', 'experiment', 'audit')):
                    reason = 'evaluation_or_io_import:' + module
            if reason:
                violations.append(dict(path=str(path), line=node.lineno, reason=reason))
    return dict(passed=not violations, files=files, violations=violations,
                limitation='Static scan plus supplied dependency list is a check, not a Python security sandbox.')
