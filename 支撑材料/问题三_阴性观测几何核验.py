"""独立连续核验Q3阴性接收更新。
使用精确有理数半平面裁剪和被排除部分的顶点极值，不调用求解器的圆交、裁剪或凸包实现，只需合法观测历史。"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
import math
from contextlib import nullcontext
from fractions import Fraction
from pathlib import Path

HERE=Path(__file__).resolve().parent


def D(value):
    return Fraction.from_float(value) if isinstance(value,float) else Fraction(value)


def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def hull(points):
    points=sorted(set(points))
    if len(points)<=2:return points
    sides=[]
    for sequence in (points,list(reversed(points))):
        side=[]
        for p in sequence:
            while len(side)>1 and cross(side[-2],side[-1],p)<=0:side.pop()
            side.append(p)
        sides.append(side[:-1])
    return sides[0]+sides[1]


def clip(poly,plane):
    if not poly:return []
    a,b,c=plane;out=[]
    for p,q in zip(poly,poly[1:]+poly[:1]):
        fp=a*p[0]+b*p[1]-c;fq=a*q[0]+b*q[1]-c
        if fp<=0:out.append(p)
        if (fp<0<fq) or (fq<0<fp):
            t=fp/(fp-fq)
            out.append((p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])))
    return hull(out)


def supporting_planes(poly):
    poly=hull(poly)
    if len(poly)==1:
        x,y=poly[0]
        return [(D(1),D(0),x),(D(-1),D(0),-x),(D(0),D(1),y),(D(0),D(-1),-y)]
    if len(poly)==2:
        p,q=poly;ux,uy=q[0]-p[0],q[1]-p[1]
        return [(uy,-ux,uy*p[0]-ux*p[1]),(-uy,ux,-uy*p[0]+ux*p[1]),
                (ux,uy,ux*q[0]+uy*q[1]),(-ux,-uy,-ux*p[0]-uy*p[1])]
    return [(b[1]-a[1],a[0]-b[0],(b[1]-a[1])*a[0]+(a[0]-b[0])*a[1])
            for a,b in zip(poly,poly[1:]+poly[:1])]


def outside_violation(inner,outer):
    if not inner:return D(0)
    if not outer:return math.inf
    return max([0.0]+[float(a*x+b*y-c)/math.sqrt(float(a*a+b*b))
                for a,b,c in supporting_planes(outer) if a*a+b*b
                for x,y in inner])


def contains(outer,inner):
    """精确检查闭集包含关系，不用距离容差掩盖被误删的细小区域。"""
    if not inner:return True
    if not outer:return False
    return all(a*x+b*y<=c for a,b,c in supporting_planes(outer) for x,y in inner)


def verify_update(event,positive_positions,prior_poly=None):
    """核验单次更新是否保留全部可行源位置。
    旧事件缺少中间多边形时，以半平面交和记录的10⁻⁷米外扩重建；报告会明确标出这种较弱的事件来源。"""
    with nullcontext():
        errors=[]
        before=[tuple(map(D,p)) for p in event['prior_poly']]
        after=[tuple(map(D,p)) for p in event['poly']]
        negative=tuple(map(D,event['negative_position']))
        if prior_poly is not None:
            prior=[tuple(map(D,p)) for p in prior_poly]
            if not (contains(before,prior) and contains(prior,before)):
                errors.append('event_prior_polygon_mismatch')
        stored_planes=event.get('radius_comparison_planes',[])
        if stored_planes and len(stored_planes)!=len(positive_positions):errors.append('positive_plane_count_mismatch')
        exact_intersection=before
        padded_intersection=before
        plane_checks=0
        for index,position in enumerate(positive_positions if stored_planes else []):
            positive=tuple(map(D,position))
            dx,dy=negative[0]-positive[0],negative[1]-positive[1]
            plane=(2*dx,2*dy,negative[0]**2+negative[1]**2-positive[0]**2-positive[1]**2)
            recorded=tuple(map(D,stored_planes[index]))
            scale=max(1.0,math.sqrt(float(plane[0]**2+plane[1]**2)))
            if max(abs(recorded[i]-plane[i])/scale for i in range(3))>D('0.000000001'):
                errors.append('distance_comparison_plane_wrong')
            exact_intersection=clip(exact_intersection,plane)
            padding=D(1e-7*math.sqrt(float(recorded[0]**2+recorded[1]**2)))
            padded_intersection=clip(padded_intersection,(recorded[0],recorded[1],recorded[2]+padding))
            plane_checks+=1
        has_intermediate='poly_after_radius_comparison' in event
        middle=[tuple(map(D,p)) for p in event['poly_after_radius_comparison']] if has_intermediate else padded_intersection
        plane_violation=outside_violation(exact_intersection,middle)
        if not contains(middle,exact_intersection):
            errors.append('radius_comparison_excludes_feasible_region')
        cap_checks=0;largest_excluded_radius=D(0)
        if event.get('excluded_radius_m') is not None:
            if not D(0)<D(event['excluded_radius_m'])<D(1000):errors.append('invalid_negative_exclusion_radius')
            if not after:
                caps=[exact_intersection]
            else:
                caps=[]
                for a,b,c in supporting_planes(after):
                    # 若某个支撑半平面已包含整个输入域，它不会删掉
                    # 任何位置，不能将其边界线误当成新的截断。
                    # 核验合法半平面的精确交集，不将
                    # 边界另加10⁻⁷米实现余量。该外包
                    # 是人为加入的数值包络，并非源的真实
                    # 它当作真实可行域；其舍入可能产生无关细条。
                    if not any(a*x+b*y>c for x,y in exact_intersection):continue
                    caps.append(clip(exact_intersection,(-a,-b,-c)))
            for cap in caps:
                if not cap:continue
                cap_checks+=1
                max_sq=max((x-negative[0])**2+(y-negative[1])**2 for x,y in cap)
                largest_excluded_radius=max(largest_excluded_radius,math.sqrt(float(max_sq)))
                if max_sq>=D(1000)**2:
                    errors.append('removed_cap_not_entirely_inside_guaranteed_reception_disk')
        elif not contains(after,exact_intersection):
            errors.append('no_disk_output_excludes_radius_feasible_region')
        return dict(passed=not errors,errors=errors,halfplane_checks=plane_checks,
                    excluded_cap_checks=cap_checks,
                    max_excluded_cap_radius_m=float(largest_excluded_radius),
                    halfplane_containment_violation_m=float(plane_violation),
                    explicit_intermediate_polygon=has_intermediate,
                    arithmetic='Exact rational half-plane and cap decisions on IEEE-754 input values; metric display uses float',
                    containment_tolerance_m=0.)


def audit_trace(records,solution):
    measures=[r for r in records if r['endpoint']=='/measure' and r.get('accepted') is True]
    history={ch:[] for ch in range(1,21)};prior={};cursor=0;checks=[];errors=[]
    for event_index,event in enumerate(solution['events']):
        ch=event.get('channel')
        if event.get('method')=='observe':
            row=measures[cursor];cursor+=1
            p=tuple(row['request']['position'][axis] for axis in ('x','y'))
            if row['request']['channel']!=ch or p!=tuple(event['position']):errors.append('observation_trace_mismatch')
            history[ch].append(dict(position=p,result=row['response']['measure_result']))
        if event.get('method')=='q3_negative_reception':
            point=tuple(event['negative_position'])
            negatives=[i for i,r in enumerate(history[ch],1) if r['position']==point and r['result']=='no_signal']
            if not negatives:errors.append('unobserved_negative_position')
            if 'negative_measure_index' in event and event['negative_measure_index'] not in negatives:
                errors.append('negative_measure_index_mismatch')
            positive_positions=[r['position'] for r in history[ch] if r['result'] in ('direction','near')]
            if 'positives_used' in event:
                recorded=event['positives_used']
                coords=[tuple(r['position']) if isinstance(r,dict) else tuple(r) for r in recorded]
                if coords!=positive_positions:errors.append('positive_history_mismatch')
            value=verify_update(event,positive_positions,prior.get(ch))
            checks.append(dict(event=event_index,channel=ch,**value))
        if event.get('poly'):prior[ch]=event['poly']
    if cursor!=len(measures):errors.append('unmatched_measurements')
    return dict(passed=not errors and all(r['passed'] for r in checks),errors=errors,
                events=len(checks),halfplane_checks=sum(r['halfplane_checks'] for r in checks),
                excluded_cap_checks=sum(r['excluded_cap_checks'] for r in checks),
                max_excluded_cap_radius_m=max([r['max_excluded_cap_radius_m'] for r in checks]+[0]),
                missing_intermediate_events=sum(not r['explicit_intermediate_polygon'] for r in checks),
                failures=[r for r in checks if not r['passed']])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--workers',type=int,default=1)
    args=parser.parse_args();rows=[]
    paths=sorted((HERE/args.folder).glob('*/*/solution.json'))
    if args.workers>1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            rows=list(pool.map(audit_file,paths))
    else:rows=[audit_file(path) for path in paths]
    result=dict(passed=all(r['passed'] for r in rows),runs=len(rows),events=sum(r['events'] for r in rows),
                halfplane_checks=sum(r['halfplane_checks'] for r in rows),
                excluded_cap_checks=sum(r['excluded_cap_checks'] for r in rows),
                max_excluded_cap_radius_m=max([r['max_excluded_cap_radius_m'] for r in rows]+[0]),
                failures=[r for r in rows if not r['passed']],rows=rows,
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                containment_tolerance_m=0.,source_truth_read=False)
    target=HERE/args.output;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


def audit_file(path):
    path=Path(path)
    solution=json.loads(path.read_text(encoding='utf-8-sig'))
    with gzip.open(path.parent/'actions.jsonl.gz','rt',encoding='utf-8') as stream:
        records=[json.loads(line) for line in stream]
    value=audit_trace(records,solution)
    return dict(path=path.parent.relative_to(HERE).as_posix(),**value)


if __name__=='__main__':main()
