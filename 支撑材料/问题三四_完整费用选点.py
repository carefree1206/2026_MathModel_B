"""按检测5秒、失败清除3秒、成功清除5秒修正费用排名。
这些量是启发式费用估计，并非精确随机价值函数。候选几何和接收检查保持不变。"""
import math
from 问题三四_光学试清位置选择 import OpticalPosteriorQ3, OpticalPosteriorQ4, weighted_median_point
from 问题三四_候选区域概率计算 import hypothesis_mass, halfplane_mass
from 问题三四_局部候选测点评估 import sample_polygon, receive_probability, distance, unit, clip, bearing_planes, enclosing_circle
import 问题三四_模型加载 as bootstrap

MEASURE_S=5.
FAILED_CLEAR_S=3.
SUCCESSFUL_CLEAR_S=5.
SPEED_M_S=5.


class Cost5Mixin:
    def choose_pair(self,original,track,**kwargs):
        """同时替换后验排名与面积权重回退排名。"""
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
        area_fallback=not samples
        if area_fallback:
            samples=[(p,w,1.,1.,[]) for p,w in sample_polygon(track.poly)]
        total=sum(x[1] for x in samples);best=None
        for pair in candidates:
            points=sorted(pair['points'],key=lambda p:distance(self.s.position,p))
            if points!=pair['points']:
                pair=dict(pair,points=points,max_source_distance_m=list(reversed(pair['max_source_distance_m'])))
            q=points[0];estimate=distance(self.s.position,q)/SPEED_M_S+MEASURE_S
            for source,weight,mass,omni,components in samples:
                poly=list(track.poly)
                angle=math.degrees(math.atan2(source[1]-q[1],source[0]-q[0]))
                for plane in bearing_planes(q,angle,1.005,1500):poly=clip(poly,plane)
                circle=enclosing_circle(poly) if poly else track.circle;r=circle[1]
                positive=(max(0.,distance(q,circle[0])-max(0.,19.99-r))/SPEED_M_S+
                          SUCCESSFUL_CLEAR_S+self.cfg['pair_cost_weight']*max(0.,r-19.99)*.25)
                if self.problem=='q3':probability=1.
                elif area_fallback or self.cfg['posterior_mode']=='radius':probability=receive_probability(origin,q,source)
                else:probability=(omni+sum(w*halfplane_mass(intervals,source,q) for w,intervals in components))/mass
                negative=(distance(q,points[1])/SPEED_M_S+MEASURE_S+
                          distance(points[1],source)/SPEED_M_S+SUCCESSFUL_CLEAR_S)
                estimate+=weight/total*(probability*positive+(1-probability)*negative)
            key=(estimate,tuple(points))
            if best is None or key<best[0]:best=(key,pair)
        self.events.append(dict(method='m020_cost5_pair_ranking',channel=track.channel,
            evaluated_candidates=len(candidates),selected_surrogate_cost_s=best[0][0],
            ranking_only=True,measurement_cost_s=MEASURE_S,successful_clear_cost_s=SUCCESSFUL_CLEAR_S,
            synthetic_prior='uniform_area_radius_50pct_directional',area_fallback=area_fallback,
            positive_points=positives,negative_points=negatives,source_polygon=track.poly,
            selected_points=best[1]['points'],posterior_mode=self.cfg['posterior_mode']))
        return best[1]

    def select_optical(self,track,center):
        """只替代一次清除位置，失败后执行原中心5秒测量。"""
        samples=self.posterior_profile(track)
        if not samples:return None
        start=self.s.position
        candidates=[tuple(center),weighted_median_point(samples)]
        candidates.append((sum(p[0]*w for p,w,*_ in samples),sum(p[1]*w for p,w,*_ in samples)))
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
        candidates.append(tuple(start))
        continuation=[]
        for source,w,mass,omni,components in samples:
            reception=1. if self.problem=='q3' else (omni+sum(v*halfplane_mass(parts,source,center) for v,parts in components))/mass
            remaining=MEASURE_S+SUCCESSFUL_CLEAR_S+distance(center,source)/SPEED_M_S+40*(1-reception)
            continuation.append((source,w,remaining))
        def score(q):
            value=distance(start,q)/SPEED_M_S+FAILED_CLEAR_S
            back=distance(q,center)/SPEED_M_S;hit=0.
            for source,w,remaining in continuation:
                if distance(q,source)<=19.8:
                    hit+=w;value+=(SUCCESSFUL_CLEAR_S-FAILED_CLEAR_S)*w
                else:value+=w*(back+remaining)
            return value,hit
        original=score(center)
        best=min(((score(q),q) for q in candidates),key=lambda row:(row[0][0],row[1]))
        gain=original[0]-best[0][0]
        if gain<self.cfg['optical_gain_threshold'] or distance(best[1],center)<1e-5:return None
        return dict(point=best[1],gain_estimate_s=gain,old_score_s=original[0],new_score_s=best[0][0],
                    old_hit_probability_estimate=original[1],new_hit_probability_estimate=best[0][1],
                    samples=len(samples),candidates=len(candidates),measurement_cost_s=MEASURE_S,
                    failed_clear_cost_s=FAILED_CLEAR_S,successful_clear_cost_s=SUCCESSFUL_CLEAR_S,
                    interpretation='approximate ranking surrogate with physical action prices')


class Cost5Q3(Cost5Mixin,OpticalPosteriorQ3):pass
class Cost5Q4(Cost5Mixin,OpticalPosteriorQ4):pass


def solve(session,problem,settings=None):
    cls=Cost5Q3 if problem=='q3' else Cost5Q4
    return cls(session,problem,bootstrap.baseline_settings(problem) if settings is None else settings).run()
