"""仅由已知源圆域生成有限三角格覆盖。
保留与1800米闭圆相交的全部闭三角形，边和顶点附近的邻接三角形均保留；顶点提供严格正向投影，距离不超过格边长。本模块不读取真值或观测。"""
import math


def segment_distance_sq(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return (p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2


def triangle_distance_sq(p, triangle):
    cross = []
    for a, b in zip(triangle, triangle[1:]+triangle[:1]):
        cross.append((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
    if min(cross) >= -1e-7 or max(cross) <= 1e-7:
        return 0.
    return min(segment_distance_sq(p, a, b)
               for a, b in zip(triangle, triangle[1:]+triangle[:1]))


def triangular_mesh(side=990., phase='vertex'):
    """返回选定顶点和三角形，向外留10⁻⁵米余量。
    枚举索引范围覆盖源域及完整邻格；距离使用实际浮点坐标检查。"""
    if isinstance(side, bool) or not isinstance(side, (float, int)) or not 891 <= side <= 999:
        raise ValueError('Certified triangular side must be between 891 and 999 m')
    if phase not in ('vertex', 'centroid'):
        raise ValueError('Unknown triangular lattice phase')
    height = math.sqrt(3.)*side/2
    shift = (0., 0.) if phase == 'vertex' else (side/2., height/3.)

    def vertex(i, j):
        return side*(i+j/2.)-shift[0], height*j-shift[1]

    indices = set()
    triangles = []
    for i in range(-6, 7):
        for j in range(-6, 7):
            for ids in (((i,j), (i+1,j), (i,j+1)),
                        ((i+1,j+1), (i,j+1), (i+1,j))):
                triangle = [vertex(*k) for k in ids]
                if triangle_distance_sq((0., 0.), triangle) <= (1800.+1e-5)**2:
                    indices.update(ids)
                    triangles.append(triangle)
    return [vertex(*k) for k in sorted(indices)], triangles
