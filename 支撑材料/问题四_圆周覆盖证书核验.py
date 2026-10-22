"""独立重放21点圆周覆盖证书，仅使用Python标准库。

本程序改编自研究中另写的独立核验器，不导入证书生成器或求解算法。
所有圆弧包含、接收距离和区间分割均用Fraction精确计算。
"""
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import hashlib
import json
import time
import argparse
import math

ROOT=Path(__file__).resolve().parent/'数据/问题四覆盖证明/circle'
EXPECTED_GENERATOR='cc05802caec85420bc5239d26a98e5c18c6c78012fddb1282bce18d7ba991f73'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return a[0]*b[1]-a[1]*b[0]
def minus(a,b):return tuple(x-y for x,y in zip(a,b))
def value(p,t):return p[0]+t*(p[1]+t*p[2])


def extrema(poly,lo,hi):
    """比较闭区间两端与驻点，得到整个区间上的精确极值。"""
    lower,upper=sorted((value(poly,lo),value(poly,hi)))
    if poly[2]!=0:
        t=-poly[1]/(2*poly[2])
        if lo<=t<=hi:
            v=value(poly,t)
            lower=min(lower,v);upper=max(upper,v)
    return lower,upper


def curve_numerator(center,radius,quadrant):
    """直接构造圆周坐标的有理分子，避免三角函数近似。"""
    assert type(quadrant) is int and 0<=quadrant<4
    radial=((F(1),F(0),F(-1)),(F(0),F(2),F(0)))
    for _ in range(quadrant):
        radial=(tuple(-v for v in radial[1]),radial[0])
    return tuple(tuple(radius*radial[j][k]+(center[j] if k in (0,2) else 0)
                       for k in range(3)) for j in range(2))


def product(a,b):
    out=[F(0)]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        for j,y in enumerate(b):out[i+j]+=x*y
    return out


def distance_numerator(qnum,station,limit):
    # 先展开四次距离分子，再核对其能被1+t²整除；
    # 这样可独立检查降为二次式的恒等关系，避免漏项。
    difference=[tuple(qnum[j][k]-(station[j] if k in (0,2) else 0) for k in range(3)) for j in range(2)]
    square=[x+y for x,y in zip(product(difference[0],difference[0]),product(difference[1],difference[1]))]
    for k,coefficient in ((0,1),(2,2),(4,1)):square[k]-=limit*limit*coefficient
    assert square[3]==square[1] and square[2]==square[0]+square[4]
    return square[0],square[1],square[4]


def edge_numerator(qnum,a,b):
    edge=minus(b,a)
    return tuple(cross(edge,tuple(qnum[j][k]-(a[j] if k in (0,2) else 0) for j in range(2))) for k in range(3))


def parameters(points,circle,quadrant):
    assert type(circle) is int and -1<=circle<len(points)
    center=(F(0),F(0)) if circle==-1 else points[circle]
    radius=F(1800) if circle==-1 else F(1000)
    return curve_numerator(center,radius,quadrant)


def verify_coverage(data,points,require_all=True):
    if require_all:
        assert data['status']=='certified_coverage' and data['unresolved']==[]
    grouped=defaultdict(list)
    covered=outside=edges=range_checks=0
    depths=[]
    for leaf in data['leaves']:
        circle,quad=leaf['circle'],leaf['quadrant']
        qnum=parameters(points,circle,quad)
        lo,hi=F(leaf['lo']),F(leaf['hi'])
        assert 0<=lo<hi<=1
        width=hi-lo
        assert width.numerator==1 and width.denominator&(width.denominator-1)==0
        assert (lo/width).denominator==1
        depths.append(width.denominator.bit_length()-1)
        grouped[circle,quad].append((lo,hi))
        if leaf['kind']=='outside_source_interior':
            assert circle>=0,'源边界区间必须完成覆盖检查'
            poly=distance_numerator(qnum,(F(0),F(0)),F(1800))
            assert extrema(poly,lo,hi)[0]>=0
            outside+=1
            continue
        assert leaf['kind']=='covered'
        ids=leaf['hull']
        assert len(ids)>=3 and len(set(ids))==len(ids)
        assert all(type(i) is int and 0<=i<len(points) and i!=circle for i in ids)
        polygon=[points[i] for i in ids]
        # 逐边核对其他顶点严格位于左侧，确认顶点给出逆时针凸多边形；
        # 反向顺序、自交、内部点和共线退化都会被拒绝。
        for k,(a,b) in enumerate(zip(polygon,polygon[1:]+polygon[:1])):
            assert a!=b
            for j,p in enumerate(polygon):
                if j in (k,(k+1)%len(polygon)):continue
                assert cross(minus(b,a),minus(p,a))>0
            assert extrema(edge_numerator(qnum,a,b),lo,hi)[0]>=0
            edges+=1
        for p in polygon:
            assert extrema(distance_numerator(qnum,p,F(1000)),lo,hi)[1]<=0
            range_checks+=1
        covered+=1
    expected={(circle,quad) for circle in range(-1,len(points)) for quad in range(4)}
    if require_all:assert set(grouped)==expected
    completed=[]
    for key,intervals in grouped.items():
        endpoint=F(0);complete=True
        for lo,hi in sorted(intervals):
            assert lo>=endpoint,(key,'区间重叠或重复',endpoint,lo)
            if lo!=endpoint:complete=False
            endpoint=hi
        if endpoint!=1:complete=False
        if require_all:assert complete,(key,'区间存在缺口或遗漏端点')
        if complete:completed.append(key)
    if require_all:
        assert data['nodes']==2*len(data['leaves'])-len(expected)
        assert data['maximum_depth']==max(depths)
    return {'result':'coverage_certificate_passed' if require_all else 'saved_partial_leaves_passed',
            'circle_quadrant_groups':len(grouped),
            'all_groups_partition_closed_unit_interval':require_all,
            'completed_circle_quadrant_groups':completed,
            'source_boundary_all_four_quadrants_certified':all((-1,q) in completed for q in range(4)),
            'source_boundary_covered_leaves':sum(leaf['circle']==-1 for leaf in data['leaves']),
            'leaves':len(data['leaves']),
            'covered_leaves':covered,'outside_leaves':outside,'nodes':data['nodes'],
            'maximum_depth':max(depths,default=0),'convex_polygon_edge_checks':edges,
            'whole_arc_station_range_checks':range_checks,
            'current_circle_center_excluded_from_every_support':True,
            'outside_leaves_have_whole_arc_norm_at_least_source_radius':True}


def negative_controls(data,points):
    tests=[]
    mutations=[]
    d=deepcopy(data);d['leaves'].pop(0);mutations.append(('missing_interval',d))
    d=deepcopy(data);next(leaf for leaf in d['leaves'] if leaf['kind']=='covered')['hull'][0]=len(points)
    mutations.append(('invalid_hull_index',d))
    d=deepcopy(data);next(leaf for leaf in d['leaves'] if leaf['kind']=='covered')['hull'].reverse()
    mutations.append(('clockwise_hull',d))
    d=deepcopy(data);leaf=next(leaf for leaf in d['leaves'] if leaf['kind']=='covered' and leaf['circle']>=0)
    leaf['hull'][0]=leaf['circle'];mutations.append(('using_excluded_circle_center',d))
    for name,d in mutations:
        try:verify_coverage(d,points)
        except AssertionError:tests.append(name)
        else:raise AssertionError(('错误证书未被拒绝',name))
    assert len(tests)==4
    return tests


def verify_identity(data, support_root):
    """先确认坐标与参数身份，再进行独立的几何核验。"""
    reference = json.loads((ROOT/'reference_layout.json').read_text(encoding='utf-8'))
    points = [tuple(F(v, reference['scale']) for v in row) for row in reference['points_mm']]
    assert [tuple(F(v) for v in row) for row in data['stations']] == points
    assert len(points) == len(set(points)) == data['station_count'] == 21
    assert all(len(p) == 2 for p in points)
    assert F(data['source_radius']) == 1800 and F(data['reception_radius']) == 1000
    assert data['candidate_sha256'] == reference['original_box_certificate_sha256']
    assert data['script_sha256'] == EXPECTED_GENERATOR
    assert data['proof_sha256'] == sha(ROOT/'圆周覆盖判据.md')

    # 配置中的ring22是历史选项名称；实际站数由两圈参数和圆心站决定。
    config = reference['q4_config']
    required = dict(cover='ring22', q4_inner_n=8, q4_inner_radius=999,
                    q4_ring_n=12, q4_ring_radius=1867, q4_outer_phase=15)
    assert all(config[k] == v for k,v in required.items())
    rounded = [(0,0)]
    for number,radius,phase in ((8,999,0),(12,1867,15)):
        for k in range(number):
            angle = math.radians(phase)+2*math.pi*k/number
            # 这里只核对原算法的三位小数取整规则；后续证明全用精确毫米坐标。
            rounded.append(tuple(int(round(round(v,3)*1000)) for v in
                                 (radius*math.cos(angle),radius*math.sin(angle))))
    assert rounded == [tuple(row) for row in reference['points_mm']]
    identity = dict(reference_coordinates_matched=True, configured_ring_coordinates_matched=True,
                    original_box_certificate_sha256=reference['original_box_certificate_sha256'],
                    packaged_support_matched=False)

    if support_root is not None:
        support_root = Path(support_root).resolve()
        old_path = support_root/'数据/q4_coverage_certificate.json'
        config_path = support_root/'数据/参数/问题四_算法参数.json'
        old = json.loads(old_path.read_text(encoding='utf-8'))
        assert sha(old_path) == reference['original_box_certificate_sha256']
        assert old['points_mm'] == reference['points_mm'] and old['scale'] == 1000
        assert old['source_radius'] == 1800000 and old['reception_radius'] == 999990
        assert sha(config_path) == reference['q4_config_sha256']
        assert json.loads(config_path.read_text(encoding='utf-8')) == config
        identity['packaged_support_matched'] = True
    return points, identity


def main():
    parser = argparse.ArgumentParser(description='独立核验21点的连续圆周覆盖证书。')
    parser.add_argument('--output', type=Path, default=Path('results/circle_check.json'),
                        help='核验报告的保存路径，默认results/circle_check.json')
    parser.add_argument('--support-root', type=Path, help='同时比对支撑包的配置和原二维证书')
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('核验依赖完整断言，请勿使用python -O。')
    support_root = args.support_root
    if support_root is None:
        # 放入支撑包后自动识别包根目录；单独复制本目录也能核验存档坐标。
        for candidate in ROOT.parents:
            if (candidate/'数据/q4_coverage_certificate.json').is_file() and (candidate/'数据/参数/问题四_算法参数.json').is_file():
                support_root = candidate
                break
    start = time.perf_counter()
    certificate_path = ROOT/'circle_reference21.json'
    data = json.loads(certificate_path.read_text(encoding='utf-8'))
    points,identity = verify_identity(data, support_root)
    result = verify_coverage(data,points)
    controls = negative_controls(data,points)
    assert result['leaves'] == 720 and result['circle_quadrant_groups'] == 88
    assert result['convex_polygon_edge_checks'] == result['whole_arc_station_range_checks'] == 2148
    report = dict(passed=True, statement='21点固定布局完成整个源盘、全部半平面朝向的连续覆盖核验。',
                  generator_imported=False, identity=identity, coverage=result,
                  negative_controls_rejected=controls, certificate_sha256=sha(certificate_path),
                  checker_sha256=sha(Path(__file__)), seconds=time.perf_counter()-start)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True, leaves=720, groups=88, support_matched=identity['packaged_support_matched'],
                         output=str(args.output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
