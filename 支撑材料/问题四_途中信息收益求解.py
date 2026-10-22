"""只插入有利用价值的信息动作，比较较早采样与最大几何收益。"""
import math
from 问题三四_模型加载 import m020_settings
from 问题三四_信息费用调度 import Q3 as ParentQ3, Q4 as ParentQ4
class InterceptMixin:
    def intercept(self,key,goal):
        threshold=self.cfg['intercept_gain_m']
        if not math.isfinite(threshold) or self.cfg['intercept_scans_only'] and key[0]!='scan':return False
        start=self.s.position;dx,dy=goal[0]-start[0],goal[1]-start[1];length=math.hypot(dx,dy)
        if length<150:return False
        choices=[]
        for t in self.tracks.values():
            if t.cleared or not t.circle or t.inconsistent or self.intercepts[t.channel]>=self.cfg['intercept_cap']:continue
            if self.cfg.get('intercept_other_only',False) and key==('target',t.channel):continue
            center,radius=t.circle
            if radius<80:continue
            fraction=((center[0]-start[0])*dx+(center[1]-start[1])*dy)/(length*length)
            for alpha in sorted(set([.15,.3,.5,.7,.85,max(.1,min(.9,fraction))])):
                if alpha*length<60 or (1-alpha)*length<30:continue
                p=(start[0]+alpha*dx,start[1]+alpha*dy);score=self.predicted_gain(t,p)
                ranking=score/(30+alpha*length) if self.cfg.get('intercept_efficiency',False) else score
                if score>=threshold:choices.append((ranking,-alpha,-t.channel,p,t,score))
        if not choices:return False
        ranking,negative_alpha,_,point,t,score=max(choices,key=lambda row:row[:3])
        self.intercepts[t.channel]+=1
        self.events.append(dict(method='enroute_measure_choice',channel=t.channel,position=point,
            planned_next=key,planned_endpoint=goal,start=start,predicted_radius_gain_m=score,
            interpolation_fraction=-negative_alpha,attempt=self.intercepts[t.channel],ranking=ranking,
            note='Planning heuristic; no deletion of coverage or guarantee of lower total cost'))
        self.observe(t.channel,point);return True
class Q3(InterceptMixin,ParentQ3):pass
class Q4(InterceptMixin,ParentQ4):pass
def solve(session,problem,settings=None):return (Q3 if problem=='q3' else Q4)(session,problem,m020_settings(problem) if settings is None else settings).run()
