"""为观测产生的保守多边形建立有限光学覆盖。
覆盖整个旋转外接矩形，不凭抽样相交删除网格。几何不一致或覆盖未成功时，调用方仍保留原153点条带后备。"""
import math


def _finite_point(point):
    return (len(point) == 2 and all(isinstance(x, (int, float))
                                  and math.isfinite(x) for x in point))


def clear_cover(track, start=None, radius=19.99):
    """返回光学点集与覆盖证书；无效多边形返回空值。
    依据当前多边形及机器狗位置比较坐标轴、行列数和蛇形方向，以移动/5加3倍尝试数估计全失败费用。每格半对角线不超过工作半径且小于20米，覆盖保证独立于费用排名。"""
    if not math.isfinite(radius) or not 0 < radius < 20:
        raise ValueError('Require a finite optical-cover radius strictly between 0 and 20')
    if (getattr(track, 'inconsistent', True) or getattr(track, 'cleared', True)
            or not getattr(track, 'poly', None) or not getattr(track, 'first', None)):
        return None
    polygon = [tuple(p) for p in track.poly]
    if not all(_finite_point(p) for p in polygon):
        return None
    origin, bearing = track.first
    if not _finite_point(origin) or not math.isfinite(bearing):
        return None
    if start is None:
        start = origin
    if not _finite_point(start):
        raise ValueError('Require a finite actual starting position')
    start = tuple(start)
    angle = math.radians(bearing)
    axes = [('first_bearing', (math.cos(angle), math.sin(angle)))]
    farthest = None
    maximum = 0.
    for i, p in enumerate(polygon):
        for q in polygon[i+1:]:
            length = math.hypot(p[0]-q[0], p[1]-q[1])
            if length > maximum:
                maximum = length
                farthest = (p, q)
    if farthest is not None and maximum > 1e-10:
        p, q = farthest
        axes.append(('longest_vertex_chord', ((q[0]-p[0])/maximum,
                                              (q[1]-p[1])/maximum)))
    padding = 1e-5
    working_radius = radius-1e-6
    if working_radius <= 0:
        raise ValueError('Radius is smaller than the numerical coverage margin')
    best = None
    for axis_name, u in axes:
        v = (-u[1], u[0])
        local = [((p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1],
                  (p[0]-origin[0])*v[0]+(p[1]-origin[1])*v[1]) for p in polygon]
        lo_x, hi_x = min(p[0] for p in local)-padding, max(p[0] for p in local)+padding
        lo_y, hi_y = min(p[1] for p in local)-padding, max(p[1] for p in local)+padding
        width, height = hi_x-lo_x, hi_y-lo_y
        # 每行高度不超过工作半径时，横向已有充分覆盖空间；
        # 为取得有效网格无需再增加超过两行。
        # 候选点数按启发式费用选择，完整性由覆盖条件单独保证：
        # 每个参与比较的网格都覆盖整个外接矩形。
        maximum_rows = max(1, math.ceil(height/working_radius)+2)
        for rows in range(1, maximum_rows+1):
            dy = height/rows
            remaining = working_radius**2-(dy*.5)**2
            if remaining <= 0:
                continue
            max_dx = 2*math.sqrt(remaining)
            columns = max(1, math.ceil(width/max_dx))
            dx = width/columns
            half_diagonal = math.hypot(dx, dy)*.5
            if half_diagonal > radius:
                continue
            count = rows*columns
            internal_lengths = {
                'rows': rows*(columns-1)*dx+(rows-1)*dy,
                'columns': columns*(rows-1)*dy+(columns-1)*dx}
            for snake_axis, internal_length in internal_lengths.items():
                for flip_x in (False, True):
                    for flip_y in (False, True):
                        x = hi_x-dx*.5 if flip_x else lo_x+dx*.5
                        y = hi_y-dy*.5 if flip_y else lo_y+dy*.5
                        entry = (origin[0]+x*u[0]+y*v[0], origin[1]+x*u[1]+y*v[1])
                        length = math.hypot(entry[0]-start[0], entry[1]-start[1])+internal_length
                        cost = length/5+3*count
                        key = (cost, count, length, axis_name, rows, columns,
                               snake_axis, flip_x, flip_y)
                        if best is None or key < best['key']:
                            best = dict(key=key, axis_name=axis_name, u=u, v=v,
                                        bounds=(lo_x, hi_x, lo_y, hi_y), rows=rows,
                                        columns=columns, dx=dx, dy=dy,
                                        half_diagonal=half_diagonal,
                                        snake_axis=snake_axis,
                                        flip_x=flip_x, flip_y=flip_y,
                                        nominal_length=length)
    if best is None:
        return None
    nx, ny = best['columns'], best['rows']
    if best['snake_axis'] == 'rows':
        indices = [(j, k) for k in range(ny)
                   for j in (range(nx) if k % 2 == 0 else range(nx-1, -1, -1))]
    else:
        indices = [(j, k) for j in range(nx)
                   for k in (range(ny) if j % 2 == 0 else range(ny-1, -1, -1))]
    lo_x, hi_x, lo_y, hi_y = best['bounds']
    u, v = best['u'], best['v']
    points = []
    for j, k in indices:
        if best['flip_x']:
            j = nx-1-j
        if best['flip_y']:
            k = ny-1-k
        x, y = lo_x+(j+.5)*best['dx'], lo_y+(k+.5)*best['dy']
        points.append((origin[0]+x*u[0]+y*v[0], origin[1]+x*u[1]+y*v[1]))
    if not all(_finite_point(p) for p in points):
        return None
    length = sum(math.hypot(p[0]-q[0], p[1]-q[1])
                 for p, q in zip([start]+points[:-1], points))
    certificate = dict(kind='complete_rotated_rectangle_cells',
                       channel=track.channel, source_polygon_before=polygon,
                       origin=tuple(origin), axis_name=best['axis_name'],
                       axis_u=u, axis_v=v, bounds_local=best['bounds'],
                       rows=ny, columns=nx, point_count=len(points),
                       cell_width_m=best['dx'], cell_height_m=best['dy'],
                       cell_half_diagonal_m=best['half_diagonal'],
                       certified_radius_m=radius,
                       rectangle_padding_m=padding,
                       snake_axis=best['snake_axis'], flip_x=best['flip_x'],
                       flip_y=best['flip_y'], start=start,
                       complete_visit_length_m=length,
                       complete_failure_cost_s=length/5+3*len(points),
                       removed_cells=0)
    return dict(points=points, certificate=certificate)
