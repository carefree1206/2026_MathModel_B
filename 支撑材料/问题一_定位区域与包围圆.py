"""有界示向误差的几何运算；坐标与距离容差均以米计。"""
import itertools
import math

EPS = 1e-7


def unit(deg):
    a = math.radians(deg)
    return math.cos(a), math.sin(a)


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bearing_planes(position, bearing, delta=1.005, max_range=None):
    """返回两条角边界对应的a*x+b*y≤c半平面。"""
    low, high = unit(bearing - delta), unit(bearing + delta)
    normals = [(low[1], -low[0]), (-high[1], high[0])]
    planes = [(a, b, a * position[0] + b * position[1]) for a, b in normals]
    if max_range is not None:
        a, b = unit(bearing)
        planes.append((a, b, a * position[0] + b * position[1] + max_range))
    return planes


def convex_hull(points):
    pts = sorted(set(tuple(p) for p in points))
    if len(pts) <= 1:
        return pts
    def half(seq):
        result = []
        for p in seq:
            while len(result) >= 2 and cross(sub(result[-1], result[-2]), sub(p, result[-1])) <= 0:
                result.pop()
            result.append(p)
        return result
    return half(pts)[:-1] + half(reversed(pts))[:-1]


def clip(poly, plane):
    """按略向外放宽的半平面裁剪，避免数值误差收缩真实边界。"""
    if not poly:
        return []
    a, b, c = plane
    c += EPS * math.hypot(a, b)
    out = []
    for p, q in zip(poly, poly[1:] + poly[:1]):
        fp, fq = a * p[0] + b * p[1] - c, a * q[0] + b * q[1] - c
        if fp <= 0:
            out.append(p)
        if (fp <= 0) != (fq <= 0):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return convex_hull(out)


def diameter(poly):
    """枚举全部顶点对计算直径，复杂度O(k²)，作为小区域的参考实现。"""
    if not poly:
        return None, None
    pair = max(itertools.combinations_with_replacement(poly, 2), key=lambda pq: distance(*pq))
    return distance(*pair), pair


def circle_two(a, b):
    c = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return c, distance(c, a)


def circle_three(a, b, c):
    """平移坐标后求三个点的最小包围圆。"""
    candidates = [circle_two(p, q) for p, q in ((a, b), (a, c), (b, c))]
    enclosing = [cr for cr in candidates if all(distance(cr[0], p) <= cr[1] + EPS for p in (a, b, c))]
    if enclosing:
        return min(enclosing, key=lambda cr: cr[1])
    u, v = sub(b, a), sub(c, a)
    d = 2 * cross(u, v)
    if abs(d) < 1e-18:
        # 机器精度下共线时，以最远点对圆为基础保守扩张。
        center, _ = max(candidates, key=lambda cr: cr[1])
        return center, max(distance(center, p) for p in (a, b, c))
    u2, v2 = sum(x*x for x in u), sum(x*x for x in v)
    center = (a[0] + (u2*v[1] - v2*u[1])/d,
              a[1] + (u[0]*v2 - v[0]*u2)/d)
    return center, max(distance(center, p) for p in (a, b, c))


def enclosing_circle(poly):
    """枚举1、2、3个边界支撑点，复杂度O(k⁴)，用于小多边形。
    候选圆若遗漏顶点就不接受；只有选出包住全部点的圆后才附加数值余量。"""
    if not poly:
        return None
    if len(poly) == 1:
        return poly[0], 0.0
    best = None
    candidates = (circle_two(*pair) for pair in itertools.combinations(poly, 2))
    for center, radius in itertools.chain(candidates,
            (circle_three(*triple) for triple in itertools.combinations(poly, 3))):
        if best is not None and radius >= best[1]:
            continue
        if all(distance(center, p) <= radius + EPS for p in poly):
            best = center, max(distance(center, p) for p in poly)
    if best is None:
        raise ArithmeticError('No enclosing circle found')
    return best[0], best[1] + EPS


def point_region_distance(point, poly):
    if not poly:
        return math.inf
    if len(poly) == 1:
        return distance(point, poly[0])
    if len(poly) >= 3 and all(cross(sub(q, p), sub(point, p)) >= -EPS
                              for p, q in zip(poly, poly[1:] + poly[:1])):
        return 0.0
    best = math.inf
    for p, q in zip(poly, poly[1:] + poly[:1]):
        v = sub(q, p)
        norm2 = v[0]*v[0] + v[1]*v[1]
        t = max(0, min(1, sum(a*b for a, b in zip(sub(point, p), v))/norm2)) if norm2 else 0
        best = min(best, distance(point, (p[0] + t*v[0], p[1] + t*v[1])))
    return best


def halfplane_region(planes):
    """Q1先用线性规划判可行性和有界性，再枚举合法边界交点。
    不添加人工外接框；独立分析需要SciPy。一般复杂度为O(m³)加线性规划，是便于核查的参考实现。"""
    from scipy.optimize import linprog
    normalized = []
    for a, b, c in planes:
        norm = math.hypot(a, b)
        if norm == 0:
            if c < 0:
                return {'status': 'empty', 'vertices': [], 'diameter_m': None}
        else:
            normalized.append((a/norm, b/norm, c/norm))
    if not normalized:
        return {'status': 'unbounded', 'vertices': [], 'diameter_m': None}
    kwargs = dict(A_ub=[p[:2] for p in normalized], b_ub=[p[2] for p in normalized],
                  bounds=[(None, None), (None, None)], method='highs')
    feasible = linprog([0, 0], **kwargs)
    if feasible.status == 2:
        return {'status': 'empty', 'vertices': [], 'diameter_m': None}
    if not feasible.success:
        raise ArithmeticError(feasible.message)
    for objective in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        result = linprog(objective, **kwargs)
        if result.status == 3:
            return {'status': 'unbounded', 'vertices': [], 'diameter_m': None}
        if not result.success:
            raise ArithmeticError(result.message)
    vertices = []
    for (a, b, c), (d, e, f) in itertools.combinations(normalized, 2):
        det = a*e - b*d
        if abs(det) < 1e-14:
            continue
        point = ((c*e - b*f)/det, (a*f - c*d)/det)
        if all(x*point[0] + y*point[1] <= z + EPS for x, y, z in normalized):
            if not any(distance(point, p) < EPS for p in vertices):
                vertices.append(point)
    hull = convex_hull(vertices)
    if not hull:
        raise ArithmeticError('Bounded feasible set without recoverable vertices')
    value, pair = diameter(hull)
    center, radius = enclosing_circle(hull)
    return {'status': 'point' if len(hull) == 1 else 'segment' if len(hull) == 2 else 'polygon',
            'vertices': hull, 'diameter_m': value, 'diameter_pair': pair,
            'enclosing_center': center, 'enclosing_radius_m': radius}


def second_point(position, bearing, lateral=500.0):
    u, v = unit(bearing), unit(bearing + 90)
    return (position[0] + 750*u[0] + lateral*v[0],
            position[1] + 750*u[1] + lateral*v[1])


def second_point_bounds(lateral=500.0, delta=1.005):
    d = math.radians(delta)
    farthest = max(math.hypot(750, lateral), math.hypot(1500*math.cos(d)-750,
                                                           1500*math.sin(d)+abs(lateral)))
    return {'max_source_distance_m': farthest, 'guaranteed_omni_reception': farthest <= 1000,
            'move_distance_m': math.hypot(750, lateral)}


def second_candidate_region(position, bearing, delta=1.005):
    """三个圆盘不等式给出连续接收安全域的充分条件。
    首测1500米扇区包含于顶点为原点及(1500,±1500tanδ)的三角形。距离为凸函数，三个顶点到候选均不超过1000米即可保证整域。"""
    u, v = unit(bearing), unit(bearing+90)
    lateral = 1500*math.tan(math.radians(delta))
    centers = [tuple(position)] + [(position[0]+1500*u[0]+sign*lateral*v[0],
                                   position[1]+1500*u[1]+sign*lateral*v[1]) for sign in (-1, 1)]
    return {'description': 'intersection of three closed disks; sufficient for omni reception',
            'disk_centers': centers, 'disk_radius_m': 1000.0,
            'chosen_point': second_point(position, bearing)}
