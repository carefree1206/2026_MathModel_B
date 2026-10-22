"""途中测向与路线改进；完整退出的条件保持不变。"""
import math
from 问题三四_模型加载 import m020_settings
from 问题三四_物理约束调度 import CorrectedMixin
from 问题三四_完整费用选点 import Cost5Q3, Cost5Q4
from 问题一_定位区域与包围圆 import distance, point_region_distance
from 问题三四_开放巡检路线优化 import optimize

class ControlMixin:
    def __init__(self,session,problem,settings=None):
        super().__init__(session,problem,settings)
        self.cfg.setdefault('strong_route',False)
        self.cfg.setdefault('route_exact_limit',10)
        self.cfg.setdefault('intercept_gain_m',float('inf'))
        self.cfg.setdefault('intercept_cap',2)
        self.cfg.setdefault('intercept_scans_only',False)
        self.cfg.setdefault('scan_gain_m',None)
        self.cfg.setdefault('scan_count_stop',False)
        self.intercepts={ch:0 for ch in self.tracks}
    def select_route(self,nodes):
        route=super().select_route(nodes)
        if not self.cfg['strong_route']:return route
        lookup={key:i for i,(key,p) in enumerate(nodes)}
        indices,certificate=optimize([p for _,p in nodes],self.s.position,[lookup[k] for k,p in route],self.cfg['route_exact_limit'])
        chosen=[nodes[i] for i in indices]
        self.route_suffix=[key for key,p in chosen]
        self.events.append(dict(method='predicted_route_optimization',start=self.s.position,
            nodes=nodes,order=indices,certificate=certificate))
        return chosen
    def scan(self,p,force=False):
        threshold=self.cfg['scan_gain_m']
        if threshold is None and not self.cfg['scan_count_stop']:return super().scan(p,force)
        if not force and self.scanned and min(distance(p,q) for q in self.scanned)<self.cfg['scan_spacing']:return
        self.scanned.append(tuple(p))
        for ch,t in sorted(self.tracks.items(),key=lambda kv:(kv[0]!=self.s.channel,kv[0])):
            if t.cleared:continue
            if self.cfg['scan_count_stop'] and not t.observations and sum(bool(z.observations) for z in self.tracks.values())==16:continue
            if self.cfg['skip_impossible'] and t.poly and not t.inconsistent and point_region_distance(p,t.poly)>1500.00001:continue
            if t.circle and t.circle[1]<19.99:continue
            if t.observations and min(distance(p,o['position']) for o in t.observations)<60:continue
            if threshold is not None and t.observations and not t.inconsistent and self.predicted_gain(t,p)<threshold:
                self.events.append(dict(method='optional_known_scan_skipped',channel=ch,position=p,threshold_m=threshold))
                continue
            self.observe(ch,p)
        if sum(bool(t.observations) for t in self.tracks.values())==16:self.count_stop=True;self.todo=[]
        elif self.cfg['adaptive_cover']:self.prune()
    def intercept(self,key,goal):
        threshold=self.cfg['intercept_gain_m']
        if not math.isfinite(threshold) or self.cfg['intercept_scans_only'] and key[0]!='scan':return False
        start=self.s.position;dx,dy=goal[0]-start[0],goal[1]-start[1];length=math.hypot(dx,dy)
        if length<150:return False
        choices=[]
        for t in self.tracks.values():
            if t.cleared or not t.circle or t.inconsistent or self.intercepts[t.channel]>=self.cfg['intercept_cap']:continue
            center,radius=t.circle
            if radius<80:continue
            fraction=((center[0]-start[0])*dx+(center[1]-start[1])*dy)/(length*length)
            fractions=sorted(set([.15,.3,.5,.7,.85,max(.1,min(.9,fraction))]))
            for alpha in fractions:
                if alpha*length<60 or (1-alpha)*length<30:continue
                p=(start[0]+alpha*dx,start[1]+alpha*dy)
                score=self.predicted_gain(t,p)
                if score>=threshold:choices.append((score,-alpha,-t.channel,p,t))
        if not choices:return False
        score,negative_alpha,_,point,t=max(choices,key=lambda row:row[:3])
        self.intercepts[t.channel]+=1
        self.events.append(dict(method='enroute_measure_choice',channel=t.channel,position=point,
            planned_next=key,planned_endpoint=goal,start=start,predicted_radius_gain_m=score,
            interpolation_fraction=-negative_alpha,attempt=self.intercepts[t.channel],
            note='Zero geometric detour relative to this predicted segment, not a total-cost guarantee'))
        self.observe(t.channel,point)
        return True
    def run(self):
        self.scan((0.,0.),True)
        self.todo=[(i,p) for i,p in self.todo if distance(p,(0.,0.))>1e-7]
        while self.todo or any(t.observations and not t.cleared for t in self.tracks.values()):
            self.gather()
            if not self.todo and not any(t.observations and not t.cleared for t in self.tracks.values()):
                break
            pending=[t for t in self.tracks.values() if t.observations and not t.cleared]
            if self.todo:pending=[t for t in pending if (t.near is not None or t.circle and t.circle[1]<=self.cfg['ready_radius']) and not self.defer(t)]
            nodes=[(('scan',i),p) for i,p in self.todo]
            if self.cfg['joint'] or not nodes:nodes += [(('target',t.channel),self.target_point(t)) for t in pending]
            if not nodes:raise RuntimeError('Pending state has no legal macro action')
            key,p=self.select_route(nodes)[0]
            if self.intercept(key,p):continue
            if key[0]=='scan':self.todo=[(i,q) for i,q in self.todo if i!=key[1]];self.scan(p,True)
            else:self.resolve(self.tracks[key[1]])
        self.coverage_complete=not self.todo
        cleared=sorted(ch for ch,t in self.tracks.items() if t.cleared)
        absent=sorted(ch for ch,t in self.tracks.items() if not t.observations)
        complete=not self.todo and len(cleared)+len(absent)==20 and 10<=len(cleared)<=16 and not any(t.inconsistent for t in self.tracks.values())
        return dict(termination='coverage_complete' if complete else 'incomplete',cleared_channels=cleared,absent_channels=absent,
            coverage_evidence=dict(kind='source_count_upper_bound' if self.count_stop else 'continuous_actual_sites' if self.cfg['adaptive_cover'] else 'fixed_sites',
                problem=self.problem,design=self.cfg['cover'],sites=self.fixed,actual_scan_sites=self.scanned,measurements_per_channel=self.measured),
            geometry_inconsistencies=[ch for ch,t in self.tracks.items() if t.inconsistent],events=self.events,
            tracks=[t.snapshot() for t in self.tracks.values() if t.observations])
class Q3(ControlMixin,CorrectedMixin,Cost5Q3):pass
class Q4(ControlMixin,CorrectedMixin,Cost5Q4):pass
def solve(session,problem,settings=None):return (Q3 if problem=='q3' else Q4)(session,problem,m020_settings(problem) if settings is None else settings).run()
