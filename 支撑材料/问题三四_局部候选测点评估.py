"""M020的观测定位候选，在M019几何与退出证书下比较动作。"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import 问题三四_模型加载 as bootstrap
from 问题三四_几何求解基线 import Solver
from 问题三_阴性观测收缩 import NegativeSolver
from 问题三四_光学清除覆盖 import clear_cover
from 问题一_定位区域与包围圆 import distance, unit, point_region_distance, clip, bearing_planes, enclosing_circle


def sample_polygon(poly):
    """确定性面积求积只用于候选排名，不用于排除位置。"""
    c = (sum(p[0] for p in poly)/len(poly),sum(p[1] for p in poly)/len(poly))
    out = []
    for a,b in zip(poly,poly[1:]+poly[:1]):
        area = abs((a[0]-c[0])*(b[1]-c[1])-(a[1]-c[1])*(b[0]-c[0]))/2
        if area < 1e-10:continue
        for wc,wa,wb in [(2/3,1/6,1/6),(1/6,2/3,1/6),(1/6,1/6,2/3)]:
            out.append(((wc*c[0]+wa*a[0]+wb*b[0],wc*c[1]+wa*a[1]+wb*b[1]),area/3))
    if not out:return [(p,1/len(poly)) for p in poly]
    total=sum(w for p,w in out)
    return [(p,w/total) for p,w in out]


def receive_probability(origin,probe,source):
    """在首次接收条件下采用均匀朝向先验，仅用于排名。"""
    x=(origin[0]-source[0],origin[1]-source[1]);y=(probe[0]-source[0],probe[1]-source[1])
    norm=math.hypot(*x)*math.hypot(*y)
    if norm<1e-10:return 1.
    return 1-math.acos(max(-1.,min(1.,(x[0]*y[0]+x[1]*y[1])/norm)))/math.pi


class LocalMixin:
    def __init__(self,session,problem,settings=None):
        super().__init__(session,problem,settings)
        self.cfg.setdefault('local_mode','optical')
        self.cfg.setdefault('optical_max_points',6)
        self.cfg.setdefault('optical_min_radius',20.)
        self.cfg.setdefault('pair_cost_weight',1.)

    def choose_pair(self,original,track,**kwargs):
        baseline=original(track,**kwargs)
        if not track.poly or track.inconsistent or track.cleared or not track.first:return baseline
        origin,bearing=track.first;u=unit(bearing)
        xs=[(p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1] for p in track.poly]
        lo,hi=min(xs),max(xs);span=hi-lo
        candidates=[]
        if baseline:candidates.append(baseline)
        for fraction in (.25,.4,.55,.7,.85):
            for lateral in (30.,60.,100.,180.):
                pair=original(track,forward=max(.001,lo+fraction*span),lateral=lateral)
                if pair:candidates.append(pair)
        if not candidates:return baseline
        samples=sample_polygon(track.poly)
        best=None
        for pair in candidates:
            points=sorted(pair['points'],key=lambda p:distance(self.s.position,p))
            if points!=pair['points']:
                pair=dict(pair,points=points,max_source_distance_m=list(reversed(pair['max_source_distance_m'])))
            q=points[0]
            estimate=distance(self.s.position,q)/5+3
            for source,weight in samples:
                poly=list(track.poly)
                angle=math.degrees(math.atan2(source[1]-q[1],source[0]-q[0]))
                for plane in bearing_planes(q,angle,1.005,1500):poly=clip(poly,plane)
                circle=enclosing_circle(poly) if poly else track.circle
                r=circle[1]
                positive=(max(0.,distance(q,circle[0])-max(0.,19.99-r))/5+5+
                          self.cfg['pair_cost_weight']*max(0.,r-19.99)*.25)
                probability=1. if self.problem=='q3' else receive_probability(origin,q,source)
                negative=distance(q,points[1])/5+3+distance(points[1],source)/5+5
                estimate+=weight*(probability*positive+(1-probability)*negative)
            key=(estimate,tuple(points))
            if best is None or key<best[0]:best=(key,pair)
        self.events.append(dict(method='m020_pair_ranking',channel=track.channel,
            evaluated_candidates=len(candidates),selected_estimated_cost_s=best[0][0],
            ranking_only=True,source_polygon=track.poly,selected_points=best[1]['points']))
        return best[1]

    def resolve(self,track):
        if (self.cfg['local_mode'] in ('optical','combined') and not track.cleared and
                track.near is None and track.poly and not track.inconsistent and
                track.circle and track.circle[1]>=self.cfg['optical_min_radius']):
            cover=clear_cover(track,start=self.s.position)
            if cover and len(cover['points'])<=self.cfg['optical_max_points']:
                self.events.append(dict(method='adaptive_clear_cover',channel=track.channel,
                    certificate=cover['certificate'],poly=track.poly,m020_early_cover=True))
                for p in cover['points']:
                    if self.attempt(track,p,'adaptive_clear_cell'):break
                if not track.cleared:
                    track.inconsistent=True
                    self.events.append(dict(method='adaptive_clear_cover_exhausted',channel=track.channel,success=False))
                else:
                    for other in self.tracks.values():
                        if other.cleared or not other.poly:continue
                        if point_region_distance(self.s.position,other.poly)<=19.99:
                            self.attempt(other,self.s.position,'shared_probe')
                    if self.cfg['extra_scan']:self.scan(self.s.position)
        if self.cfg['local_mode'] in ('pair','combined'):
            import 问题三四_安全定位候选 as localization
            original=localization.safe_pair_candidates
            def choose(track,**kwargs):return self.choose_pair(original,track,**kwargs)
            localization.safe_pair_candidates=choose
            try:return super().resolve(track)
            finally:localization.safe_pair_candidates=original
        return super().resolve(track)


class LocalQ3(LocalMixin,NegativeSolver):pass
class LocalQ4(LocalMixin,Solver):pass


def solve(session,problem,settings=None):
    cls=LocalQ3 if problem=='q3' else LocalQ4
    return cls(session,problem,bootstrap.baseline_settings(problem) if settings is None else settings).run()
