"""固定覆盖构造与确定性开放路线改进。
测站在观测前确定，不使用隐藏场景信息。保留的45点构造以690米间距包夹1800米圆域，满足690小于1000/√2。"""
import math


def route_length(points, start=(0., 0.)):
    total = 0.
    for point in points:
        total += math.hypot(point[0] - start[0], point[1] - start[1])
        start = point
    return total


def two_opt_open(points):
    """仅接受严格缩短路线的片段翻转，起点固定、终点自由。"""
    route = list(points)
    while True:
        best_delta, best_pair = -1e-8, None
        for i in range(len(route) - 1):
            a = (0., 0.) if i == 0 else route[i - 1]
            b = route[i]
            for j in range(i + 1, len(route)):
                c = route[j]
                delta = math.dist(a, c) - math.dist(a, b)
                if j + 1 < len(route):
                    d = route[j + 1]
                    delta += math.dist(b, d) - math.dist(c, d)
                if delta < best_delta:
                    best_delta, best_pair = delta, (i, j)
        if best_pair is None:
            return route
        i, j = best_pair
        route[i:j + 1] = reversed(route[i:j + 1])


def improved_route(sites):
    # 将原路线保留为候选，保证本次固定测站的名义路长不增。
    candidates = [list(sites), two_opt_open(sites), two_opt_open(list(reversed(sites)))]
    remaining = set(sites)
    position = (0., 0.)
    greedy = []
    while remaining:
        target = min(remaining, key=lambda p: (math.dist(position, p), p))
        remaining.remove(target)
        greedy.append(target)
        position = target
    candidates.append(two_opt_open(greedy))
    return min(candidates, key=lambda r: (route_length(r), r))


def coverage_sites(config):
    design = config.get('coverage_design', 'square64')
    if design == 'triangular':
        from 问题四_三角网格覆盖 import triangular_mesh
        points, _ = triangular_mesh(config['triangular_side_m'], config['triangular_phase'])
        return improved_route(points) if config.get('scan_route') == 'two_opt' else points
    if design in ('omni7', 'omni13', 'omni7_compact'):
        n = 12 if design == 'omni13' else 6
        radius = config['omni_ring_radius_m'] if design == 'omni7_compact' else 1500
        points = [(0., 0.)] + [(radius*math.cos(2*math.pi*k/n), radius*math.sin(2*math.pi*k/n)) for k in range(n)]
        return improved_route(points) if config.get('scan_route') == 'two_opt' else points
    coords = config['grid_coordinates_m']
    points = [(x, y) for i, y in enumerate(coords)
              for x in (coords if i % 2 == 0 else list(reversed(coords)))]
    if config.get('coverage_design', 'square64') == 'trimmed45':
        points = [p for p in points if not (abs(p[0]) == 2070 and abs(p[1]) == 2070)]
    if config.get('scan_route', 'serpentine') == 'two_opt':
        points = improved_route(points)
    return points
