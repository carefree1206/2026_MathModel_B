"""不读取真值的有限定向覆盖构造及连续证书。
证书覆盖完整源圆域；坐标以整数毫米记录，检查只用整数平方距离和叉积，不导入模拟器。"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path


def ring_points(rings, include_center=True):
    """每条环参数依次为点数、半径米数、起始角度。"""
    points = [(0., 0.)] if include_center else []
    for number, radius, phase in rings:
        for k in range(number):
            a = math.radians(phase) + 2 * math.pi * k / number
            points.append((round(radius * math.cos(a), 3),
                           round(radius * math.sin(a), 3)))
    return points


def route_length(points, start=(0., 0.)):
    ans = 0.
    for p in points:
        ans += math.dist(p, start)
        start = p
    return ans


def open_route(points, start=(0., 0.)):
    """多起点近邻路线加开放2-opt改进，不宣称整体最优。"""
    points = list(dict.fromkeys(map(tuple, points)))
    if not points:
        return []

    def improve(route):
        while True:
            best, change = -1e-7, None
            for i in range(len(route) - 1):
                a, b = (start if i == 0 else route[i-1]), route[i]
                for j in range(i + 1, len(route)):
                    c = route[j]
                    delta = math.dist(a, c) - math.dist(a, b)
                    if j + 1 < len(route):
                        d = route[j+1]
                        delta += math.dist(b, d) - math.dist(c, d)
                    if delta < best:
                        best, change = delta, (i, j)
            if change is None:
                return route
            i, j = change
            route[i:j+1] = reversed(route[i:j+1])

    candidates = [improve(points[:]), improve(list(reversed(points)))]
    for first in points:
        todo = set(points)
        todo.remove(first)
        route = [first]
        while todo:
            nxt = min(todo, key=lambda p: (math.dist(route[-1], p), p))
            route.append(nxt)
            todo.remove(nxt)
        candidates.append(improve(route))
    return min(candidates, key=lambda r: (route_length(r, start), r))


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _hull(indices, points):
    order = sorted(set(indices), key=lambda i: points[i])
    lower, upper = [], []
    for i in order:
        while len(lower) >= 2 and _cross(points[lower[-2]], points[lower[-1]], points[i]) <= 0:
            lower.pop()
        lower.append(i)
    for i in reversed(order):
        while len(upper) >= 2 and _cross(points[upper[-2]], points[upper[-1]], points[i]) <= 0:
            upper.pop()
        upper.append(i)
    return lower[:-1] + upper[:-1]


def _corners(box):
    x0, y0, x1, y1 = box
    return [(x0,y0), (x1,y0), (x1,y1), (x0,y1)]


def _outside(box, radius):
    x0,y0,x1,y1 = box
    dx = max(x0, -x1, 0)
    dy = max(y0, -y1, 0)
    return dx*dx + dy*dy > radius*radius


def _split(box):
    x0,y0,x1,y1 = box
    xm,ym = (x0+x1)//2, (y0+y1)//2
    return [(x0,y0,xm,ym),(xm,y0,x1,ym),(xm,ym,x1,y1),(x0,ym,xm,y1)]


def _box_witness(box, points, reception):
    corners = _corners(box)
    ids = [i for i,s in enumerate(points)
           if max((s[0]-c[0])**2+(s[1]-c[1])**2 for c in corners) <= reception*reception]
    if len(ids) < 3:
        return None
    hull = _hull(ids, points)
    if len(hull) < 3:
        return None
    # 支撑直线留2毫米余量，也覆盖任意
    # 实际测站取整到毫米引入的不超过√2/2毫米误差。
    if all(_cross(points[i], points[j], c) > 0 and
           _cross(points[i], points[j], c)**2 >
           4*((points[i][0]-points[j][0])**2+(points[i][1]-points[j][1])**2)
           for i,j in zip(hull, hull[1:]+hull[:1]) for c in corners):
        return hull
    return None


def directional_certificate(points, source_radius=1800., reception_radius=999.99,
                            minimum_box_m=1., max_nodes=1000000):
    """返回有限格证书或明确列出未认证格。
    失败只表示未取得此充分证书，不自动构成反例。通过的格严格位于局部凸包内，接收半径略小于1000米以保留余量。"""
    pts = [tuple(round(v*1000) for v in p) for p in points]
    radius, reception = round(source_radius*1000), round(reception_radius*1000)
    side = 1
    while side < radius:
        side *= 2
    root = (-side,-side,side,side)
    queue, leaves, unresolved, count = [root], [], [], 0
    min_mm = round(minimum_box_m*1000)
    while queue:
        box = queue.pop()
        count += 1
        if _outside(box,radius):
            leaves.append({'box':box,'outside':True})
            continue
        witness = _box_witness(box, pts, reception)
        if witness is not None:
            leaves.append({'box':box,'hull':witness})
        elif max(box[2]-box[0],box[3]-box[1]) <= min_mm or count >= max_nodes:
            unresolved.append(box)
        else:
            queue.extend(_split(box))
    return {'schema':'m019-directional-integer-box-v1', 'passed':not unresolved,
            'scale':1000,'source_radius':radius,'reception_radius':reception,
            'points_mm':pts,'root':root,'visited_nodes':count,'leaves':leaves,
            'unresolved':unresolved}


def certify(points, problem='q4', minimum_box_m=16., max_nodes=12000,
            fail_fast=True):
    """为任意实际测站集合快速生成保守在线证书。
    返回是否通过、未认证格及格中心。失败不等于找到真实漏检源，调用方可保留旧后备站。坐标取整到毫米的误差不超过0.707107毫米；接收距离留10毫米、凸包边留2毫米余量，兼顾原坐标。默认最小格边长16米，节点预算只限制核验工作量，用尽时返回未认证。"""
    if str(problem).lower() not in ('3','4','q3','q4'):
        raise ValueError('problem must be 3, 4, q3 or q4')
    omni = str(problem).lower() in ('3','q3')
    pts = [tuple(round(v*1000) for v in p) for p in points]
    radius,reception,side = 1800000,999990,2097152
    queue = [(-side,-side,side,side)]
    count, covered, unresolved = 0,0,[]
    minimum = round(minimum_box_m*1000)
    while queue:
        box = queue.pop()
        count += 1
        if _outside(box,radius):
            continue
        if omni:
            cs = _corners(box)
            passed = any(max((s[0]-c[0])**2+(s[1]-c[1])**2 for c in cs)
                         <= reception*reception for s in pts)
        else:
            passed = _box_witness(box,pts,reception) is not None
        if passed:
            covered += 1
        elif max(box[2]-box[0],box[3]-box[1]) <= minimum or count >= max_nodes:
            unresolved.append(box)
            if fail_fast:
                break
        else:
            queue.extend(_split(box))
    return {'passed':not unresolved and not queue,'problem':'q3' if omni else 'q4',
            'visited_nodes':count,'covered_cells':covered,'unresolved':unresolved,
            'gap_points':[((b[0]+b[2])/2000.,(b[1]+b[3])/2000.) for b in unresolved],
            'certificate_type':'integer_box_local_disk' if omni else 'integer_box_local_hull',
            'minimum_box_m':minimum_box_m}


def verify_certificate(certificate):
    """独立遍历分区并核对给定见证。
    不调用凸包生成器或原格检查函数，以整数运算检查凸性、逆时针方向及每个角点的严格内含。"""
    c = certificate
    if not c['passed'] or c['unresolved']:
        return False
    pts, radius, reception = c['points_mm'],c['source_radius'],c['reception_radius']
    rows = {tuple(x['box']):x for x in c['leaves']}
    if len(rows) != len(c['leaves']):
        return False
    root = tuple(c['root'])
    if root[0] > -radius or root[1] > -radius or root[2] < radius or root[3] < radius:
        return False
    stack, used, traversed = [root],set(),0
    while stack:
        box = stack.pop()
        traversed += 1
        if traversed > 4*len(rows)+1:
            return False
        row = rows.get(box)
        if row is None:
            if box[2]-box[0] <= 1 or box[3]-box[1] <= 1:
                return False
            stack.extend(_split(box))
            continue
        used.add(box)
        if row.get('outside'):
            if not _outside(box,radius):
                return False
            continue
        ids = row['hull']
        if len(ids)<3 or len(set(ids))!=len(ids) or any(i<0 or i>=len(pts) for i in ids):
            return False
        polygon = [pts[i] for i in ids]
        if any(_cross(a,b,p) < 0 for a,b in zip(polygon,polygon[1:]+polygon[:1])
               for p in polygon):
            return False
        for p in polygon:
            for corner in _corners(box):
                if (p[0]-corner[0])**2+(p[1]-corner[1])**2 > reception*reception:
                    return False
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            for corner in _corners(box):
                cross = _cross(a,b,corner)
                if cross <= 0 or cross*cross <= 4*((a[0]-b[0])**2+(a[1]-b[1])**2):
                    return False
    return used == set(rows)


def sampled_margin(points, probes):
    """仅作探索：在有限探测点上计算局部凸包的有符号余量。"""
    import numpy as np
    s,p = np.asarray(points,float),np.asarray(probes,float)
    diff = s[None,:,:] - p[:,None,:]
    distance = np.linalg.norm(diff,axis=2)
    angle = np.arctan2(diff[:,:,1],diff[:,:,0])
    angle[distance > 999.99] = np.nan
    angle.sort(axis=1)
    count = np.sum(np.isfinite(angle),axis=1)
    angle[~np.isfinite(angle)] = 1e9
    gap = np.diff(angle,axis=1)
    gap[angle[:,1:] > 1e8] = 0
    maximum = np.max(gap,axis=1)
    last = angle[np.arange(len(p)),np.maximum(count-1,0)]
    maximum = np.maximum(maximum,2*math.pi + angle[:,0]-last)
    maximum[count < 3] = 2*math.pi
    return float(np.min(math.pi-maximum)),p[np.argmin(math.pi-maximum)].tolist()


def disk_probes(spacing=30.):
    import numpy as np
    q = np.arange(-1800,1800.001,spacing)
    x,y = np.meshgrid(q,q)
    inside = x*x+y*y <= 1800**2
    theta = np.arange(0,2*math.pi,.004)
    return np.concatenate([np.column_stack([x[inside],y[inside]]),
                           np.column_stack([1800*np.cos(theta),1800*np.sin(theta)])])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--points',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--minimum-box-m',type=float,default=1.)
    args = parser.parse_args()
    raw = json.loads(args.points.read_text(encoding='utf8'))
    points = raw['points'] if isinstance(raw,dict) else raw
    cert = directional_certificate(points,minimum_box_m=args.minimum_box_m)
    cert['independent_verifier_passed'] = verify_certificate(cert)
    route = open_route(points)
    cert['route'] = route
    cert['route_length_m'] = route_length(route)
    cert['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cert,indent=2),encoding='utf8')
    print(json.dumps({k:cert[k] for k in ['passed','visited_nodes','independent_verifier_passed','route_length_m']}))
    print('unresolved_cells',len(cert['unresolved']),'leaves',len(cert['leaves']))


if __name__ == '__main__':
    main()
