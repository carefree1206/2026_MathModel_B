"""仅适用于Q3全向源的可移动测站环扇区覆盖。
每个1000至1800米环扇区以四个端点距离检查认证连续覆盖，角半宽为π/n；几何依据为径向凸性与角度端点极值。"""
import math


DEFAULT_RADII = {6: 1125., 7: 998., 8: 940., 9: 905.,
                10: 882., 11: 867., 12: 855.}


def minimum_ring_radius(n, margin=0.0):
    if isinstance(n, bool) or not isinstance(n, int) or n < 6:
        raise ValueError('Require an integer ring-point count n >= 6')
    if not math.isfinite(margin) or not 0 <= margin < 1:
        raise ValueError('Require 0 <= finite margin < 1 metre')
    alpha = math.pi/n
    return 1800*math.cos(alpha)-math.sqrt((1000-margin)**2-(1800*math.sin(alpha))**2)


def _point(point):
    if len(point) != 2 or not all(math.isfinite(x) for x in point):
        raise ValueError('Require two finite point coordinates')
    return float(point[0]), float(point[1])


def make_sectors(n=8, radius=None, rotation_deg=0.0, margin=0.01):
    """返回n个闭环扇区及已认证后备点。
    每个未知频道须在原点实测以覆盖1000米内区域，在每个扇区的安全点也须实际检测，机器狗仅路过不能代替。"""
    required = minimum_ring_radius(n, margin)
    if not math.isfinite(rotation_deg):
        raise ValueError('Require a finite rotation')
    if radius is None:
        radius = DEFAULT_RADII.get(n, math.ceil(required)+1.)
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('Require a finite positive fallback radius')
    output = []
    for i in range(n):
        beta = rotation_deg+i*360./n
        half = 180./n
        corners = [(r*math.cos(math.radians(beta+side*half)),
                    r*math.sin(math.radians(beta+side*half)))
                   for r in (1000., 1800.) for side in (-1, 1)]
        fallback = (radius*math.cos(math.radians(beta)),
                    radius*math.sin(math.radians(beta)))
        sector = dict(id=i, beta_deg=beta, half_width_deg=half,
                      inner_radius_m=1000., outer_radius_m=1800.,
                      corners=corners, fallback=fallback,
                      margin_m=margin, ring_radius_m=radius,
                      ring_count=n)
        if not safe_sector(fallback, sector):
            raise ValueError('Fallback radius fails the four-endpoint coverage certificate')
        output.append(sector)
    return output


def safe_sector(point, sector):
    """四个端点距离均满足显式余量时才返回真。"""
    point = _point(point)
    limit = 1000.-sector['margin_m']
    return all(math.hypot(point[0]-v[0], point[1]-v[1]) <= limit
               for v in sector['corners'])


def sector_certificate(point, sector):
    point = _point(point)
    distances = [math.hypot(point[0]-v[0], point[1]-v[1])
                 for v in sector['corners']]
    return dict(kind='q3_annular_sector_four_endpoints', sector_id=sector['id'],
                point=point, corners=sector['corners'],
                beta_deg=sector['beta_deg'], half_width_deg=sector['half_width_deg'],
                endpoint_distances_m=distances, max_distance_m=max(distances),
                certified_radius_m=1000.-sector['margin_m'],
                valid=max(distances) <= 1000.-sector['margin_m'])


def project_sector(desired, sector, max_iterations=256):
    """近似寻找四圆盘交集中的最近点，并保留回退。
    Dykstra凸投影只负责产生候选；返回前的四项距离检查负责接收保证，迭代次数或收敛本身不作证据。投影失败时返回已验证的固定环点。"""
    desired = _point(desired)
    fallback = _point(sector['fallback'])
    if not safe_sector(fallback, sector):
        raise ValueError('Cannot use an uncertified fallback')
    if safe_sector(desired, sector):
        return desired
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or max_iterations < 0:
        raise ValueError('Require a nonnegative integer iteration count')
    # 额外工作余量用于吸收浮点舍入，并留给
    # 最终独立端点检查使用。
    radius = 1000.-sector['margin_m']-1e-6
    point = desired
    corrections = [(0., 0.) for _ in sector['corners']]
    for _ in range(max_iterations):
        before = point
        for i, center in enumerate(sector['corners']):
            shifted = (point[0]+corrections[i][0], point[1]+corrections[i][1])
            dx, dy = shifted[0]-center[0], shifted[1]-center[1]
            length = math.hypot(dx, dy)
            if length > radius:
                projected = (center[0]+radius*dx/length, center[1]+radius*dy/length)
            else:
                projected = shifted
            corrections[i] = (shifted[0]-projected[0], shifted[1]-projected[1])
            point = projected
        if math.hypot(point[0]-before[0], point[1]-before[1]) < 1e-9:
            break
    return point if safe_sector(point, sector) else fallback
