"""按观测历史构造排名先验；后验权重不排除几何可行位置。"""
import math
from 问题三四_局部候选测点评估 import LocalQ3, LocalQ4, distance, unit, clip, bearing_planes, enclosing_circle, sample_polygon, receive_probability
import 问题三四_模型加载 as bootstrap

TAU=2*math.pi


def angle_intervals(source,positive,negative):
    """计算同时满足各接收半平面符号条件的精确方向区间。"""
    constraints=[];cuts={0.,TAU}
    for points,sign in ((positive,1),(negative,-1)):
        for p in points:
            angle=math.atan2(p[1]-source[1],p[0]-source[0])
            constraints.append((angle,sign))
            cuts.add((angle-math.pi/2)%TAU);cuts.add((angle+math.pi/2)%TAU)
    cuts=sorted(cuts);result=[]
    for lo,hi in zip(cuts,cuts[1:]):
        mid=(lo+hi)/2
        if all(sign*math.cos(mid-angle)>=-1e-12 for angle,sign in constraints):result.append((lo,hi))
    return result


def halfplane_mass(intervals,source,probe):
    angle=math.atan2(probe[1]-source[1],probe[0]-source[0])
    cuts=sorted({0.,TAU,(angle-math.pi/2)%TAU,(angle+math.pi/2)%TAU})
    receive=[(lo,hi) for lo,hi in zip(cuts,cuts[1:]) if math.cos((lo+hi)/2-angle)>=0]
    return sum(max(0.,min(hi,b)-max(lo,a)) for lo,hi in intervals for a,b in receive)/TAU


def hypothesis_mass(source,positive,negative,problem,mode='full'):
    """积分计算均匀接收半径与两种源类型各半的参考先验。
    以阴性距离作半径分段，段内有效方向约束固定，积分精度仅受浮点运算限制。该先验用于动作决策，不是对官方生成规律的断言。"""
    if math.hypot(*source)>1800:return 0.,0.,[]
    lower=max([1000.]+[distance(source,p) for p in positive]);upper=1500.
    if lower>=upper:return 0.,0.,[]
    if problem=='q3':
        upper=min([upper]+[distance(source,p) for p in negative])
        mass=max(0.,upper-lower)/500
        return mass,mass,[]
    if mode=='radius':return (upper-lower)/500,(upper-lower)/500,[]
    distances=[(distance(source,p),p) for p in negative]
    breaks=sorted({lower,upper}.union(d for d,p in distances if lower<d<upper))
    omni=0.;components=[]
    for lo,hi in zip(breaks,breaks[1:]):
        active=[p for d,p in distances if d<(lo+hi)/2]
        weight=(hi-lo)/500
        if not active:omni+=.5*weight
        intervals=angle_intervals(source,positive,active)
        if intervals:components.append((.5*weight,intervals))
    mass=omni+sum(w*sum(hi-lo for lo,hi in intervals)/TAU for w,intervals in components)
    return mass,omni,components


class PosteriorMixin:
    def __init__(self,session,problem,settings=None):
        super().__init__(session,problem,settings)
        self.local_history={ch:[] for ch in self.tracks}
        self.cfg.setdefault('posterior_mode','full')

    def observe(self,ch,p):
        response=super().observe(ch,p)
        self.local_history[ch].append((tuple(p),response['measure_result']))
        return response

    def choose_pair(self,original,track,**kwargs):
        baseline=original(track,**kwargs)
        if self.cfg['posterior_mode']=='nearest':
            if baseline and distance(self.s.position,baseline['points'][1])<distance(self.s.position,baseline['points'][0])-1e-9:
                return dict(baseline,points=list(reversed(baseline['points'])),
                            max_source_distance_m=list(reversed(baseline['max_source_distance_m'])))
            return baseline
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
        positives=[p for p,r in self.local_history[track.channel] if r!='no_signal']
        negatives=[p for p,r in self.local_history[track.channel] if r=='no_signal']
        samples=[]
        for source,area_weight in sample_polygon(track.poly):
            mass,omni,components=hypothesis_mass(source,positives,negatives,self.problem,self.cfg['posterior_mode'])
            if mass>0:samples.append((source,area_weight*mass,mass,omni,components))
        if not samples:return super().choose_pair(original,track,**kwargs)
        total=sum(x[1] for x in samples);best=None
        for pair in candidates:
            points=sorted(pair['points'],key=lambda p:distance(self.s.position,p))
            if points!=pair['points']:
                pair=dict(pair,points=points,max_source_distance_m=list(reversed(pair['max_source_distance_m'])))
            q=points[0];estimate=distance(self.s.position,q)/5+3
            for source,weight,mass,omni,components in samples:
                poly=list(track.poly)
                angle=math.degrees(math.atan2(source[1]-q[1],source[0]-q[0]))
                for plane in bearing_planes(q,angle,1.005,1500):poly=clip(poly,plane)
                circle=enclosing_circle(poly) if poly else track.circle;r=circle[1]
                positive=max(0.,distance(q,circle[0])-max(0.,19.99-r))/5+5+self.cfg['pair_cost_weight']*max(0.,r-19.99)*.25
                if self.problem=='q3':probability=1.
                elif self.cfg['posterior_mode']=='radius':probability=receive_probability(origin,q,source)
                else:probability=(omni+sum(w*halfplane_mass(intervals,source,q) for w,intervals in components))/mass
                negative=distance(q,points[1])/5+3+distance(points[1],source)/5+5
                estimate+=weight/total*(probability*positive+(1-probability)*negative)
            key=(estimate,tuple(points))
            if best is None or key<best[0]:best=(key,pair)
        self.events.append(dict(method='m020_posterior_pair_ranking',channel=track.channel,
            evaluated_candidates=len(candidates),selected_estimated_cost_s=best[0][0],
            ranking_only=True,synthetic_prior='uniform_area_radius_50pct_directional',
            positive_points=positives,negative_points=negatives,source_polygon=track.poly,
            selected_points=best[1]['points'],posterior_mode=self.cfg['posterior_mode']))
        return best[1]


class PosteriorQ3(PosteriorMixin,LocalQ3):pass
class PosteriorQ4(PosteriorMixin,LocalQ4):pass


def solve(session,problem,settings=None):
    cls=PosteriorQ3 if problem=='q3' else PosteriorQ4
    return cls(session,problem,bootstrap.baseline_settings(problem) if settings is None else settings).run()
