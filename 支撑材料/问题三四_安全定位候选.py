"""由已有正测向构造可核验的双侧探针。
本模块只接收观测产生的多边形，不访问模拟器或源位置、数量、类型、接收半径和朝向。"""
import math


def _local(point, origin, u, v):
    dx, dy = point[0]-origin[0], point[1]-origin[1]
    return dx*u[0]+dy*u[1], dx*v[0]+dy*v[1]


def _cap_vertices(local_polygon, forward):
    """求多边形与前向半平面的交点和顶点，兼顾线段退化。"""
    out = [p for p in local_polygon if p[0] >= forward]
    for p, q in zip(local_polygon, local_polygon[1:]+local_polygon[:1]):
        if (p[0] < forward < q[0]) or (q[0] < forward < p[0]):
            fraction = (forward-p[0])/(q[0]-p[0])
            out.append((forward, p[1]+fraction*(q[1]-p[1])))
    return out


def safe_pair_candidates(track, forward=600.0, lateral=100.0,
                         safety_margin=1e-4):
    """返回两个探针及连续接收证书，或返回空值。
    安全表示两点到整个当前多边形的距离均处于保证接收范围内。"""
    if (not track.first or not track.poly or track.inconsistent or track.cleared
            or track.near is not None):
        return None
    if not (math.isfinite(forward) and forward > 0
            and math.isfinite(lateral) and lateral >= 0
            and math.isfinite(safety_margin) and 0 < safety_margin < 1):
        raise ValueError('Require finite forward > 0, lateral >= 0, and 0 < margin < 1')
    origin, bearing = track.first
    angle = math.radians(bearing)
    u = (math.cos(angle), math.sin(angle))
    v = (-u[1], u[0])
    polygon = [tuple(p) for p in track.poly]
    local = [_local(p, origin, u, v) for p in polygon]
    cap = _cap_vertices(local, forward)
    if not cap:
        return None
    ray_low = forward*min(y/x for x, y in cap)
    ray_high = forward*max(y/x for x, y in cap)
    actual_lateral = max(lateral, abs(ray_low), abs(ray_high))+safety_margin
    points = [(origin[0]+forward*u[0]+sign*actual_lateral*v[0],
               origin[1]+forward*u[1]+sign*actual_lateral*v[1])
              for sign in (-1, 1)]
    maxima = [max(math.hypot(p[0]-q[0], p[1]-q[1]) for q in polygon)
              for p in points]
    if max(maxima) > 1000.0-safety_margin:
        return None
    return dict(kind='two_sided_negative_halfplane', origin=list(origin),
                bearing_deg=bearing, forward_m=forward,
                lateral_m=actual_lateral, points=points,
                source_polygon_before=polygon,
                cap_vertices_local=cap,
                ray_cross_section_y=[ray_low, ray_high],
                max_source_distance_m=maxima,
                safety_margin_m=safety_margin,
                plane=(u[0], u[1], u[0]*origin[0]+u[1]*origin[1]+forward))


def negative_pair_plane(pair, responses):
    """仅在两次实际阴性后返回已认证裁剪半平面。
    须按给定顺序对同一频道检测两个点，其间不能成功清除该源；先保存点对和真实反馈，再更新位置域，便于独立核验。"""
    if pair is None or len(responses) != 2:
        return None
    if any(r.get('measure_result') != 'no_signal' or r.get('accepted') is not True
           for r in responses):
        return None
    return tuple(pair['plane'])
