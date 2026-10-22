"""独立精确核验定向阴影补集，不调用求解器的裁剪实现。"""
from fractions import Fraction
import 问题三四_模型加载 as bootstrap
from 问题三_阴性观测几何核验 import D, clip, hull, contains


def audit(records,solution):
    measures=[r for r in records if r['endpoint']=='/measure' and r.get('accepted')]
    positives={ch:[] for ch in range(1,21)};negatives={ch:[] for ch in range(1,21)}
    index=0;count=0;errors=[]
    for ei,e in enumerate(solution['events']):
        ch=e.get('channel')
        if e['method']=='observe':
            r=measures[index];index+=1
            p=tuple(r['request']['position'][k] for k in ('x','y'))
            target=negatives if r['response']['measure_result']=='no_signal' else positives
            target[ch].append(p)
        if e['method']!='q4_negative_shadow':continue
        count+=1;p=tuple(e['positive']);a,b=map(tuple,e['negatives'])
        if p not in positives[ch] or a not in negatives[ch] or b not in negatives[ch]:errors.append((ei,'unobserved_witness'))
        P,A,B=[tuple(map(D,q)) for q in (p,a,b)]
        before=[tuple(map(D,q)) for q in e['source_polygon_before']]
        after=[tuple(map(D,q)) for q in e['poly']]
        if any((n[0]-v[0])**2+(n[1]-v[1])**2>=D(1000)**2 for n in (A,B) for v in before):errors.append((ei,'negative_outside_guaranteed_reception'))
        ax,ay=A[0]-P[0],A[1]-P[1];bx,by=B[0]-P[0],B[1]-P[1]
        det=ax*by-ay*bx
        if not det:errors.append((ei,'collinear_witness'));continue
        if det<0:A,B=B,A;ax,ay,bx,by=bx,by,ax,ay
        dx,dy=B[0]-A[0],B[1]-A[1]
        planes=[(ay,-ax,ay*P[0]-ax*P[1]),(-by,bx,-by*P[0]+bx*P[1]),(-dy,dx,-dy*A[0]+dx*A[1])]
        remain=[]
        for u,v,w in planes:remain.extend(clip(before,(-u,-v,-w)))
        if not contains(after,hull(remain)):errors.append((ei,'feasible_complement_removed'))
    return dict(passed=not errors,errors=errors,shadow_certificates=count,method='exact rational complement containment and reception/witness check')
