"""仅依观测的基线，保留有限几何后备。
策略不导入模拟器，也不接收源位置、类型或真实数量。"""
import math

from 问题三四_巡检点与路线生成 import coverage_sites, improved_route
from 问题一_定位区域与包围圆 import bearing_planes, clip, distance, enclosing_circle, point_region_distance, unit
from 问题三四_测点与清除规则 import validate_options, settled, ordered_targets, refine, exact_targets, safe_clear_point, iterative_reprobe, opportunistic_clear


def validate_config(config):
    validate_options(config)
    if config['strategy'] not in ('fallback', 'geometry'):
        raise ValueError('Unknown strategy')
    design = config.get('coverage_design', 'square64')
    expected = {'square64': list(range(-2100, 2101, 600)),
                'trimmed45': list(range(-2070, 2071, 690)), 'omni7': [], 'omni13': [], 'triangular': [], 'omni7_compact': []}
    if design.startswith('omni') and config.get('problem_scope') != 'omni':
        raise ValueError('Sparse coverage requires explicit omni problem scope')
    if design not in expected or config['grid_coordinates_m'] != expected[design]:
        raise ValueError('Use one of the explicitly certified coverage grids')
    if design == 'triangular':
        from 问题四_三角网格覆盖 import triangular_mesh
        triangular_mesh(config.get('triangular_side_m'), config.get('triangular_phase'))
    if design == 'omni7_compact':
        radius = config.get('omni_ring_radius_m')
        if isinstance(radius,bool) or not isinstance(radius,(int,float)) or not 1125 <= radius <= 1500:
            raise ValueError('Certified compact omni ring radius must be in [1125,1500]')
    if config.get('scan_route', 'serpentine') not in ('serpentine', 'two_opt'):
        raise ValueError('Unknown scan route')
    if not 1.005 <= config['angle_bound_deg'] <= 1.01:
        raise ValueError('Angle bound must include rounding and fit fallback rectangle')
    if not 0 < config['clearance_margin_m'] < 1:
        raise ValueError('Use a small positive clearance safety margin')
    if type(config['min_sources']) is not int or not 0 <= config['min_sources'] <= 10:
        raise ValueError('Invalid minimum count')
    if config['transport_timeout_s'] <= 0 or config['exit_reserve_s'] <= 0 or config['transport_retries'] < 0:
        raise ValueError('Invalid execution configuration')


def scan_sites(config):
    return coverage_sites(config)


def local_point(origin, bearing, x, y):
    u, v = unit(bearing), unit(bearing+90)
    return origin[0]+x*u[0]+y*v[0], origin[1]+x*u[1]+y*v[1]


def fallback_sites(origin, bearing):
    return [local_point(origin, bearing, x, y) for i, y in enumerate((-20, 0, 20))
            for x in (range(0, 1501, 30) if i % 2 == 0 else range(1500, -1, -30))]


class Track:
    def __init__(self, channel):
        self.channel = channel
        self.observations = []
        self.first = None
        self.near = None
        self.poly = None
        self.circle = None
        self.inconsistent = False
        self.cleared = False

    def observe(self, position, response, delta):
        result = response['measure_result']
        if result == 'no_signal':
            return
        self.observations.append({'position': position, 'result': result,
                                  'bearing_deg': response.get('svd_deg')})
        if result == 'near':
            self.near = position
            return
        bearing = response['svd_deg']
        if self.first is None:
            self.first = position, bearing
            self.poly = [local_point(position, bearing, x, y)
                         for x, y in ((0, -30), (1500, -30), (1500, 30), (0, 30))]
            for plane in ((1, 0, 1800), (-1, 0, 1800), (0, 1, 1800), (0, -1, 1800)):
                self.poly = clip(self.poly, plane)
        if not self.inconsistent:
            for plane in bearing_planes(position, bearing, delta, max_range=1500):
                self.poly = clip(self.poly, plane)
            if not self.poly:
                self.inconsistent = True
                self.circle = None
            else:
                self.circle = enclosing_circle(self.poly)

    def snapshot(self):
        return {'channel': self.channel, 'observations': self.observations,
                'first_bearing': self.first, 'near_position': self.near,
                'region_vertices': self.poly, 'circle': self.circle,
                'inconsistent': self.inconsistent, 'cleared': self.cleared}


def solve(session, config):
    validate_config(config)
    tracks = {channel: Track(channel) for channel in range(1, 21)}
    counts = {channel: 0 for channel in tracks}
    events = []
    margin = config['clearance_margin_m']
    geometric = config['strategy'] == 'geometry'
    options = config.get('policy_options', {})
    early_attempted = set()
    pursued = set()
    shared_attempted = set()
    count_stop = False
    sites = scan_sites(config)
    for site_index, site in enumerate(sites):
        # 优先检测当前频道，尽可能省去一次换频。
        order = [session.channel] + [ch for ch in tracks if ch != session.channel]
        for ch in order:
            track = tracks[ch]
            is_settled = track.cleared or track.near is not None or (track.first is not None and not geometric)
            is_settled |= bool(track.circle is not None and track.circle[1] <= 20-margin)
            if is_settled:
                continue
            result = session.measure(site, ch)
            counts[ch] += 1
            track.observe(site, result, config['angle_bound_deg'])
        scan_end_position = session.position
        if options.get('pursue_detour_m', 0) > 0 and site_index + 1 < len(sites):
            next_site = sites[site_index+1]
            eligible = [t for t in tracks.values() if t.first and t.circle and
                        not t.inconsistent and not settled(t, margin) and t.channel not in pursued]
            eligible.sort(key=lambda t: (distance(session.position, t.circle[0])+
                distance(t.circle[0], next_site), t.channel))
            for t in eligible:
                center = t.circle[0]
                detour = distance(session.position, center)+distance(center, next_site)-distance(session.position, next_site)
                if detour > options['pursue_detour_m']+1e-8:
                    continue
                pursued.add(t.channel)
                refine(session, t, config, events)
                if settled(t, margin) and not t.inconsistent:
                    t.cleared = session.clear(safe_clear_point(t, session.position, config),t.channel)['clear_result'] == 'success'
                    t.inconsistent |= not t.cleared
                events.append(dict(channel=t.channel, method='early_pursuit',
                    nominal_detour_m=detour, success=t.cleared))
        if options.get('early_detour_m', 0) > 0 and site_index + 1 < len(sites):
            next_site = sites[site_index+1]
            for t in sorted(tracks.values(), key=lambda t: t.channel):
                if t.cleared or t.channel in early_attempted or not settled(t, margin) or t.inconsistent:
                    continue
                p = safe_clear_point(t, session.position, config)
                detour = distance(session.position, p)+distance(p, next_site)-distance(session.position, next_site)
                if detour <= options['early_detour_m'] + 1e-8:
                    early_attempted.add(t.channel)
                    t.cleared = session.clear(p, t.channel)['clear_result'] == 'success'
                    t.inconsistent |= not t.cleared
                    events.append(dict(channel=t.channel, method='early_guaranteed',
                                       detour_m=detour, success=t.cleared))
                    if t.cleared:
                        opportunistic_clear(session, tracks.values(), config, events, shared_attempted)
        if options.get('count_stop_unsettled') is not None:
            found_so_far = sum(bool(t.observations) for t in tracks.values())
            unsettled_count = sum(bool(t.observations) and not settled(t, margin) for t in tracks.values())
            if found_so_far == 16 and unsettled_count <= options['count_stop_unsettled']:
                count_stop = True
                events.append(dict(method='source_count_discovery_stop', observed_channels=16,
                    unsettled_channels=unsettled_count, visited_scan_sites=site_index+1))
                break
        if options.get('dynamic_scan', False) and session.position != scan_end_position:
            # 只重排尚未访问的后缀，保留全部已认证站点。
            x, y = session.position
            remaining = [(p[0]-x, p[1]-y) for p in sites[site_index+1:]]
            lookup = {(p[0]-x, p[1]-y): p for p in sites[site_index+1:]}
            sites[site_index+1:] = [lookup[p] for p in improved_route(remaining)]
    found = sum(bool(t.observations) for t in tracks.values())
    pending = [t for t in tracks.values() if t.observations and not t.cleared]
    def target(track):
        if track.near is not None:
            return track.near
        if geometric and track.circle is not None:
            return track.circle[0]
        return track.first[0]
    clear_order = ordered_targets(pending, session.position, target) if options.get('clear_order') == 'two_opt' else None
    if options.get('clear_order') == 'exact12':
        clear_order = exact_targets(pending, session.position, target)
    while pending:
        track = clear_order.pop(0) if clear_order is not None else min(pending, key=lambda t: (distance(session.position, target(t)), t.channel))
        pending.remove(track)
        if track.cleared:
            continue
        refine(session, track, config, events)
        if track.near is not None:
            track.cleared = session.clear(safe_clear_point(track, session.position, config), track.channel)['clear_result'] == 'success'
            events.append({'channel': track.channel, 'method': 'near', 'success': track.cleared})
        elif geometric and track.circle is not None:
            center, radius = track.circle
            track.cleared = session.clear(safe_clear_point(track, session.position, config), track.channel)['clear_result'] == 'success'
            events.append({'channel': track.channel, 'method': 'circle_guaranteed' if radius <= 20-margin else 'circle_probe',
                           'radius_m': radius, 'success': track.cleared})
            if radius <= 20-margin and not track.cleared:
                track.inconsistent = True
        if not track.cleared:
            iterative_reprobe(session, track, config, events)
        threshold = options.get('failed_probe_threshold', 0)
        if threshold and not track.cleared and track.first and track.poly and not track.inconsistent:
            candidates = sum(point_region_distance(p, track.poly) <= 20+1e-5 for p in fallback_sites(*track.first))
            if candidates >= threshold:
                point = session.position
                response = session.measure(point, track.channel)
                track.observe(point, response, config['angle_bound_deg'])
                events.append(dict(channel=track.channel, method='failed_probe_measure', candidates=candidates, result=response['measure_result']))
                if settled(track, margin) and not track.inconsistent:
                    track.cleared = session.clear(safe_clear_point(track, session.position, config), track.channel)['clear_result'] == 'success'
                    track.inconsistent |= not track.cleared
                    events.append(dict(channel=track.channel, method='post_probe_guaranteed', success=track.cleared))
        if not track.cleared and track.first is not None:
            all_sites = fallback_sites(*track.first)
            if distance(session.position, all_sites[-1]) < distance(session.position, all_sites[0]):
                all_sites.reverse()
            selected = all_sites
            if geometric and track.poly and not track.inconsistent:
                selected = [p for p in all_sites if point_region_distance(p, track.poly) <= 20 + 1e-5]
            tried = set()
            # 保留原蛇形访问次序，删点不会增加该次序的路径长度。
            for phase, points in (('filtered_fallback', selected), ('full_fallback', all_sites)):
                for point in points:
                    if point in tried:
                        continue
                    tried.add(point)
                    if session.clear(point, track.channel)['clear_result'] == 'success':
                        track.cleared = True
                        events.append({'channel': track.channel, 'method': phase, 'attempts': len(tried), 'success': True})
                        break
                if track.cleared:
                    break
                if phase == 'filtered_fallback' and len(selected) < len(all_sites):
                    track.inconsistent = True
                    events.append({'channel': track.channel, 'method': 'region_exhausted', 'success': False})
        if not track.cleared:
            events.append({'channel': track.channel, 'method': 'exhausted', 'success': False})
        else:
            opportunistic_clear(session, tracks.values(), config, events, shared_attempted)
        if options.get('opportunistic', False):
            # 全部未知频道已经完成扫描；此处的
            # 额外测量只精化已知待清目标，不作不存在证据。
            point = session.position
            for other in sorted(pending, key=lambda t: (t.channel != session.channel, t.channel)):
                if settled(other, margin) or other.inconsistent:
                    continue
                response = session.measure(point, other.channel)
                other.observe(point, response, config['angle_bound_deg'])
                events.append(dict(channel=other.channel, method='opportunistic_measure',
                                   result=response['measure_result'], position=point))
    cleared = [ch for ch, track in tracks.items() if track.cleared]
    absent = [ch for ch, track in tracks.items() if not track.observations and (count_stop or counts[ch] == len(sites))]
    complete = len(cleared) + len(absent) == 20 and config['min_sources'] <= len(cleared) <= 16
    inconsistent = [ch for ch, track in tracks.items() if track.inconsistent]
    return {'termination': 'coverage_complete' if complete else 'incomplete',
            'coverage_certificate': {'scan_grid': ('trimmed-45-spacing-690'
                if config.get('coverage_design', 'square64') == 'trimmed45' else ('square-64-spacing-600' if config.get('coverage_design', 'square64') == 'square64' else config['coverage_design'])),
                'coverage_design': config.get('coverage_design', 'square64'),
                'problem_scope': config.get('problem_scope', 'general'), 'site_count': len(sites), 'scan_route': config.get('scan_route', 'serpentine'),
                'scan_sites_m': sites,
                'measurements_per_channel': counts, 'absent_channels': absent,
                **({'absence_basis': 'source_count_upper_bound', 'source_count_upper_bound': 16,
                    'visited_scan_sites': site_index+1} if count_stop else {}),
                'cleared_channels': cleared, 'all_channels_resolved': complete},
            'detected_count': found, 'cleared_count': len(cleared),
            'geometry_inconsistencies': inconsistent, 'events': events,
            'tracks': [track.snapshot() for track in tracks.values() if track.observations]}
