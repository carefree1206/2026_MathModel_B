"""一次有界的后验光学试探与后验路线预测。
后验只用于排名，抽样不排除几何可能性。替代试清失败后立即回原中心实测，并保留有限后备。"""
import math
from 问题三四_候选区域概率计算 import PosteriorQ3, PosteriorQ4, hypothesis_mass, halfplane_mass, distance, unit
import 问题三四_模型加载 as bootstrap


def radical_inverse(index,base):
    value=0.;scale=1./base
    while index:
        index,digit=divmod(index,base);value+=digit*scale;scale/=base
    return value


def polygon_quadrature(polygon,count=512):
    """按凸多边形面积作确定性取点，只用于动作排名。"""
    c=(sum(p[0] for p in polygon)/len(polygon),sum(p[1] for p in polygon)/len(polygon))
    triangles=[];total=0.
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        area=abs((a[0]-c[0])*(b[1]-c[1])-(a[1]-c[1])*(b[0]-c[0]))/2
        if area>1e-12:
            triangles.append((total,total+area,a,b));total+=area
    if total<1e-10:return [(p,1/len(polygon)) for p in polygon]
    result=[]
    for i in range(1,count+1):
        x=radical_inverse(i,2)*total;y=radical_inverse(i,3)
        lo,hi,a,b=next(t for t in triangles if t[0]<=x<t[1])
        r=math.sqrt((x-lo)/(hi-lo));wa=r*(1-y);wb=r*y;wc=1-r
        result.append(((wc*c[0]+wa*a[0]+wb*b[0],wc*c[1]+wa*a[1]+wb*b[1]),1/count))
    return result


def weighted_median_point(samples):
    c=(sum(p[0]*w for p,w,*_ in samples),sum(p[1]*w for p,w,*_ in samples))
    for _ in range(30):
        weighted=[(p,w/max(1e-5,distance(c,p))) for p,w,*_ in samples]
        total=sum(w for p,w in weighted)
        q=(sum(p[0]*w for p,w in weighted)/total,sum(p[1]*w for p,w in weighted)/total)
        if distance(c,q)<1e-4:break
        c=q
    return c


class OpticalPosteriorMixin:
    def __init__(self,session,problem,settings=None):
        super().__init__(session,problem,settings)
        self.cfg.setdefault('posterior_target',False)
        self.cfg.setdefault('posterior_optical',True)
        self.cfg.setdefault('optical_gain_threshold',2.)
        self.cfg.setdefault('optical_samples',512)
        self._optical_used=set()
        self._profile_cache={}

    def posterior_profile(self,track):
        key=(track.channel,tuple(track.poly or ()),len(self.local_history[track.channel]))
        if key in self._profile_cache:return self._profile_cache[key]
        positives=[p for p,r in self.local_history[track.channel] if r!='no_signal']
        negatives=[p for p,r in self.local_history[track.channel] if r=='no_signal']
        result=[]
        for source,area_weight in polygon_quadrature(track.poly,self.cfg['optical_samples']):
            mass,omni,components=hypothesis_mass(source,positives,negatives,self.problem,'full')
            if mass>1e-16:result.append((source,area_weight*mass,mass,omni,components))
        if result:
            total=sum(x[1] for x in result)
            result=[(p,w/total,m,o,c) for p,w,m,o,c in result]
        self._profile_cache[key]=result
        return result

    def target_point(self,track):
        if (self.cfg.get('posterior_target',False) and track.poly and not track.inconsistent and
                track.near is None and track.circle and track.circle[1]>25):
            samples=self.posterior_profile(track)
            if samples:
                c=weighted_median_point(samples)
                if len(track.observations)==1 and track.circle[1]>=200:
                    v=unit(track.first[1]+90);offset=self.cfg['lateral']
                    candidates=[(c[0]+sign*offset*v[0],c[1]+sign*offset*v[1]) for sign in (-1,1)]
                    c=min(candidates,key=lambda p:distance(self.s.position,p))
                return c
        return super().target_point(track)

    def select_optical(self,track,center):
        samples=self.posterior_profile(track)
        if not samples:return None
        start=self.s.position
        candidates=[tuple(center),weighted_median_point(samples)]
        candidates.append((sum(p[0]*w for p,w,*_ in samples),sum(p[1]*w for p,w,*_ in samples)))
        # 沿不确定性长轴寻找光学候选，以横向条件
        # 均值避免稀疏求积点造成任意离散位置。
        u=unit(track.first[1]);origin=track.first[0]
        projected=sorted(((p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1],p,w)
                         for p,w,*_ in samples)
        quantiles=[i/20 for i in range(1,20)];cumulative=0.;j=0
        for x,p,w in projected:
            cumulative+=w
            while j<len(quantiles) and cumulative>=quantiles[j]:
                nearby=[(q,v) for y,q,v in projected if abs(y-x)<=18]
                total=sum(v for q,v in nearby)
                candidates.append((sum(q[0]*v for q,v in nearby)/total,sum(q[1]*v for q,v in nearby)/total))
                j+=1
        # 尚无明确清除位置时，原地或附近补测也可能有价值。
        candidates.append(tuple(start))
        continuation=[]
        for source,w,mass,omni,components in samples:
            reception=1. if self.problem=='q3' else (omni+sum(v*halfplane_mass(parts,source,center) for v,parts in components))/mass
            remaining=3+5+distance(center,source)/5+40*(1-reception)
            continuation.append((source,w,remaining))
        def score(q):
            value=distance(start,q)/5+3
            back=distance(q,center)/5;hit=0.
            for source,w,remaining in continuation:
                if distance(q,source)<=19.8:
                    hit+=w;value+=2*w
                else:value+=w*(back+remaining)
            return value,hit
        original=score(center)
        best=min(((score(q),q) for q in candidates),key=lambda row:(row[0][0],row[1]))
        gain=original[0]-best[0][0]
        if gain<self.cfg['optical_gain_threshold'] or distance(best[1],center)<1e-5:return None
        return dict(point=best[1],gain_estimate_s=gain,old_score_s=original[0],new_score_s=best[0][0],
                    old_hit_probability_estimate=original[1],new_hit_probability_estimate=best[0][1],
                    samples=len(samples),candidates=len(candidates))

    def attempt(self,track,p,method):
        if (method=='center_probe' and self.cfg['posterior_optical'] and track.channel not in self._optical_used and
                track.poly and not track.inconsistent and track.circle and track.circle[1]>20):
            self._optical_used.add(track.channel)
            choice=self.select_optical(track,p)
            if choice:
                self.events.append(dict(method='m020_posterior_optical_choice',channel=track.channel,
                    original_center=p,source_polygon=track.poly,ranking_only=True,choice=choice,
                    failure_continuation='original center measurement and unchanged bounded fallback'))
                # 每频道仅替代一次；失败时由调用方测量原来的
                # 中心p，然后继续原有有界循环。
                return super().attempt(track,choice['point'],'m020_posterior_optical_probe')
        return super().attempt(track,p,method)


class OpticalPosteriorQ3(OpticalPosteriorMixin,PosteriorQ3):pass
class OpticalPosteriorQ4(OpticalPosteriorMixin,PosteriorQ4):pass


def solve(session,problem,settings=None):
    cls=OpticalPosteriorQ3 if problem=='q3' else OpticalPosteriorQ4
    return cls(session,problem,bootstrap.baseline_settings(problem) if settings is None else settings).run()
