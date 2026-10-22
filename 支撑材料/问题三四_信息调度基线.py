"""只依实际观测联合安排原地测量、扫描与延后服务。
几何、有限清除后备及连续覆盖检查沿用原条件；预测信息收益只改变顺序，不删除覆盖任务或可行源位置。"""
import math
from 问题三四_模型加载 import baseline_settings
from 问题三四_几何求解基线 import Solver, shifted_route
from 问题三_阴性观测收缩 import NegativeSolver
from 问题一_定位区域与包围圆 import distance, clip, enclosing_circle, bearing_planes


def angle_delta(a,b):
    return (a-b+180.)%360.-180.


class SchedulingMixin:
    def __init__(self,session,problem,settings=None):
        super().__init__(session,problem,settings)
        self.cfg.setdefault('stationary_gain_m',float('inf'))
        self.cfg.setdefault('defer_factor',0.)
        self.cfg.setdefault('defer_radius_m',80.)
        self.cfg.setdefault('route_mode','two_opt')
        self.cfg.setdefault('service_projection',False)
        self.cfg.setdefault('route_action_points',False)
        self.cfg.setdefault('resolution_recourses',0)
        self.cfg.setdefault('warm_route',False)
        self.cfg.setdefault('warm_optimize',False)
        self.recourses={ch:0 for ch in self.tracks}
        self.route_suffix=[]
        if self.cfg.get('prospective') or self.sectors:
            raise ValueError('Scheduling prototype does not silently handle prospective/sectors')

    def predicted_gain(self,t,p):
        if t.cleared or t.inconsistent or not t.circle or not t.poly:return 0.
        center,radius=t.circle
        if radius<40:return 0.
        if self.measured[t.channel] and min(distance(p,q) for q in self.measured[t.channel])<60:return 0.
        length=distance(p,center)
        if not 25.<length<1450.:return 0.
        # 名义示向仅用于优先级估计，不写作真实观测。
        angle=math.degrees(math.atan2(center[1]-p[1],center[0]-p[0]))%360.
        narrowed=list(t.poly)
        for plane in bearing_planes(p,angle,1.005,max_range=1500.):
            narrowed=clip(narrowed,plane)
        if not narrowed:return 0.
        expected_radius=enclosing_circle(narrowed)[1]
        gain=max(0.,radius-expected_radius)
        if self.problem=='q4':
            # 以中心估计的接收概率仅用于选动作；实际
            # 无信号仍由冻结物理模型决定。
            views=[math.degrees(math.atan2(o['position'][1]-center[1],
                                         o['position'][0]-center[0])) for o in t.observations]
            view=math.degrees(math.atan2(p[1]-center[1],p[0]-center[0]))
            allowed=[a for a in range(0,360,5) if all(abs(angle_delta(a,v))<=60 for v in views)]
            directional=sum(abs(angle_delta(a,view))<=60 for a in allowed)/len(allowed) if allowed else 0.
            gain*=.5+.5*directional
        return gain

    def gather(self):
        threshold=self.cfg['stationary_gain_m']
        if not math.isfinite(threshold):return
        pending=[t for t in self.tracks.values() if t.observations and not t.cleared]
        scored=[(self.predicted_gain(t,self.s.position),t) for t in pending]
        for score,t in sorted(scored,key=lambda row:(-row[0],row[1].channel)):
            if score<threshold:continue
            p=tuple(self.s.position)
            self.events.append(dict(method='stationary_information_choice',channel=t.channel,
                                    point=p,predicted_radius_gain_m=score))
            self.observe(t.channel,p)

    def defer(self,t):
        factor=self.cfg['defer_factor']
        if not factor or not self.todo or not t.circle or t.circle[1]<self.cfg['defer_radius_m']:
            return False
        target=self.target_point(t);origin=self.s.position
        for _,p in self.todo:
            extra=distance(origin,p)+distance(p,target)-distance(origin,target)
            gain=self.predicted_gain(t,p)
            if gain>60. and extra<factor*gain:
                return True
        return False

    def attempt(self,track,p,method):
        if self.cfg['service_projection'] and method=='center_probe' and track.poly and not track.inconsistent:
            radius=max(distance(p,q) for q in track.poly)
            budget=max(0.,19.99-radius)
            length=distance(self.s.position,p)
            if budget and length:
                fraction=min(1.,budget/length)
                p=(p[0]+fraction*(self.s.position[0]-p[0]),p[1]+fraction*(self.s.position[1]-p[1]))
        return super().attempt(track,p,method)

    def resolve(self,t):
        """定位更新代价较大时返回联合调度。
        每源中断次数有界，原定位器继续作为后备，避免破坏有限完成条件。"""
        cap=self.cfg['resolution_recourses']
        if (not cap or t.cleared or t.near is not None or not t.circle or t.inconsistent
                or t.circle[1]<80. or self.recourses[t.channel]>=cap):
            return super().resolve(t)
        if self.cfg.get('pre_sense') and hasattr(self,'useful') and self.useful(t):
            self.observe(t.channel,self.s.position);return
        self.recourses[t.channel]+=1
        if len(t.observations)==1 and t.circle[1]>=200.:
            from 问题三四_安全定位候选 import safe_pair_candidates, negative_pair_plane
            from 问题一_定位区域与包围圆 import unit
            pair=None
            if self.cfg['pair_probe']:
                forward=600.;lateral=self.cfg['lateral']
                if self.cfg['adaptive_pair']:
                    u=unit(t.first[1]);o=t.first[0]
                    xs=[(q[0]-o[0])*u[0]+(q[1]-o[1])*u[1] for q in t.poly]
                    forward=(min(xs)+max(xs))/2
                    lateral=min(120.,max(30.,(max(xs)-min(xs))*.15))
                pair=safe_pair_candidates(t,forward=forward,lateral=lateral)
            if pair:
                if self.cfg.get('nearest_pair') and distance(self.s.position,pair['points'][1])<distance(self.s.position,pair['points'][0])-1e-9:
                    pair=dict(pair,points=list(reversed(pair['points'])),max_source_distance_m=list(reversed(pair['max_source_distance_m'])))
                responses=[]
                for q in pair['points']:
                    responses.append(self.observe(t.channel,q))
                    if responses[-1]['measure_result']!='no_signal':break
                plane=negative_pair_plane(pair,responses)
                if plane:
                    t.poly=clip(t.poly,plane)
                    if not t.poly:t.inconsistent=True
                    else:t.circle=enclosing_circle(t.poly)
                    self.events.append(dict(method='two_sided_negative_halfplane',channel=t.channel,pair=pair,responses=responses,poly=t.poly))
            else:self.observe(t.channel,self.target_point(t))
        else:
            p=t.circle[0]
            if not self.attempt(t,p,'center_probe'):
                self.observe(t.channel,p)
        self.events.append(dict(method='localization_recourse',channel=t.channel,recourse=self.recourses[t.channel]))
        if t.cleared:
            # 即使近距
            # 反馈已清除本轮定位目标，仍保留Q3带证书的条件替站。
            return super().resolve(t)

    def action_points(self,t):
        """预测定位器首个付费停车点及源服务点。
        路线目标与定位器实际首先使用的双侧点或圆心可能不同；预测只服务排序，真实动作仍由定位器提交。"""
        if t.near is not None:return t.near,t.near
        entry=self.target_point(t)
        destination=t.circle[0] if t.circle and not t.inconsistent else entry
        if t.circle and not t.inconsistent:
            if len(t.observations)==1 and t.circle[1]>=200:
                if self.cfg['pair_probe']:
                    from 问题三四_安全定位候选 import safe_pair_candidates
                    from 问题一_定位区域与包围圆 import unit
                    forward=600.;lateral=self.cfg['lateral']
                    if self.cfg['adaptive_pair']:
                        u=unit(t.first[1]);o=t.first[0]
                        xs=[(q[0]-o[0])*u[0]+(q[1]-o[1])*u[1] for q in t.poly]
                        forward=(min(xs)+max(xs))/2
                        lateral=min(120.,max(30.,(max(xs)-min(xs))*.15))
                    pair=safe_pair_candidates(t,forward=forward,lateral=lateral)
                    if pair:
                        entry=pair['points'][0]
                        if self.cfg.get('nearest_pair'):
                            entry=min(pair['points'],key=lambda q:distance(self.s.position,q))
            else:entry=destination
        return entry,destination

    def action_route(self,nodes):
        endpoints=[]
        for key,p in nodes:
            entry,end=self.action_points(self.tracks[key[1]]) if key[0]=='target' else (p,p)
            endpoints.append((entry,end))
        origin=self.s.position
        def cost(order):
            total=0.;previous=origin
            for i in order:
                entry,end=endpoints[i];total+=distance(previous,entry);previous=end
            return total
        remaining=list(range(len(nodes)));order=[];previous=origin
        while remaining:
            i=min(remaining,key=lambda i:distance(previous,endpoints[i][0]))
            order.append(i);remaining.remove(i);previous=endpoints[i][1]
        best=cost(order)
        # 开放有向路线的2-opt比较中，任务内部从进入到离开的费用与
        # 排列位置无关，因此不加入这项顺序比较。
        changed=True
        while changed:
            changed=False
            for i in range(len(order)-1):
                for j in range(i+1,len(order)):
                    candidate=order[:i]+list(reversed(order[i:j+1]))+order[j+1:]
                    value=cost(candidate)
                    if value<best-1e-7:
                        order,best=candidate,value;changed=True
        return [nodes[i] for i in order]

    def select_route(self,nodes):
        fresh=shifted_route(nodes,self.s.position)
        if not self.cfg['warm_route']:return fresh
        by_key={key:p for key,p in nodes}
        previous=[(key,by_key[key]) for key in self.route_suffix if key in by_key]
        included={key for key,p in previous}
        origin=self.s.position
        def cost(route):
            return sum(distance(p,q) for p,q in zip([origin]+[p for _,p in route[:-1]],[p for _,p in route]))
        for key,p in nodes:
            if key in included:continue
            trials=[previous[:i]+[(key,p)]+previous[i:] for i in range(len(previous)+1)]
            previous=min(trials,key=cost);included.add(key)
        chosen=min((fresh,previous),key=cost)
        if self.cfg['warm_optimize']:
            best=cost(chosen);changed=True
            while changed:
                changed=False
                for i in range(len(chosen)-1):
                    for j in range(i+1,len(chosen)):
                        candidate=chosen[:i]+list(reversed(chosen[i:j+1]))+chosen[j+1:]
                        value=cost(candidate)
                        if value<best-1e-7:
                            chosen,best=candidate,value;changed=True
        self.route_suffix=[key for key,p in chosen]
        return chosen

    def run(self):
        self.scan((0.,0.),True)
        self.todo=[(i,p) for i,p in self.todo if distance(p,(0.,0.))>1e-7]
        while self.todo or any(t.observations and not t.cleared for t in self.tracks.values()):
            self.gather()
            pending=[t for t in self.tracks.values() if t.observations and not t.cleared]
            if self.todo:
                pending=[t for t in pending if (t.near is not None or
                    (t.circle and t.circle[1]<=self.cfg['ready_radius'])) and not self.defer(t)]
            active_todo=self.todo
            if self.problem=='q4' and self.cfg['inner_first']:
                inner=[(i,p) for i,p in active_todo if math.hypot(*p)<1100]
                if inner:active_todo=inner
            nodes=[(('scan',i),p) for i,p in active_todo]
            if self.cfg['joint'] or not nodes:
                nodes += [(('target',t.channel),self.target_point(t)) for t in pending]
            if not nodes:break
            if self.cfg['route_action_points']:
                key,p=self.action_route(nodes)[0]
            elif self.cfg['route_mode']=='nearest':
                key,p=min(nodes,key=lambda row:distance(self.s.position,row[1]))
            else:
                key,p=self.select_route(nodes)[0]
            if key[0]=='scan':
                self.todo=[(i,q) for i,q in self.todo if i!=key[1]]
                self.scan(p,True)
            else:self.resolve(self.tracks[key[1]])
        self.coverage_complete=not self.todo
        cleared=sorted(ch for ch,t in self.tracks.items() if t.cleared)
        absent=sorted(ch for ch,t in self.tracks.items() if not t.observations)
        complete=not self.todo and len(cleared)+len(absent)==20 and 10<=len(cleared)<=16 and not any(t.inconsistent for t in self.tracks.values())
        return dict(termination='coverage_complete' if complete else 'incomplete',cleared_channels=cleared,absent_channels=absent,
            coverage_evidence=dict(kind='source_count_upper_bound' if self.count_stop else ('continuous_actual_sites' if self.cfg['adaptive_cover'] else 'fixed_sites'),
                problem=self.problem,design=self.cfg['cover'],sites=self.fixed,actual_scan_sites=self.scanned,
                measurements_per_channel=self.measured),
            geometry_inconsistencies=[ch for ch,t in self.tracks.items() if t.inconsistent],
            events=self.events,tracks=[t.snapshot() for t in self.tracks.values() if t.observations])


class Q3SchedulingSolver(SchedulingMixin,NegativeSolver):pass
class Q4SchedulingSolver(SchedulingMixin,Solver):pass


def solve(session,problem,settings=None):
    cls=Q3SchedulingSolver if problem=='q3' else Q4SchedulingSolver
    return cls(session,problem,settings if settings is not None else baseline_settings(problem)).run()
