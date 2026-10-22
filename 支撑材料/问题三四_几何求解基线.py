"""依据实际观测联合搜索与清除，复用冻结几何运算。"""
import math
from functools import lru_cache
from 问题三四_基础参数读取 import baseline_config
from 问题三四_搜索定位清除框架 import Track, fallback_sites
from 问题一_定位区域与包围圆 import distance, unit, point_region_distance, clip, enclosing_circle
from 问题三四_巡检点与路线生成 import coverage_sites, improved_route


DEFAULT = dict(scan_spacing=500., lateral=120., probe_rounds=3,
               joint=True, extra_scan=True, adaptive_cover=False, cover='base',
               prune_min_box=16., pair_probe=False, prune_distance=2000., prospective=False,
               q3_ring_n=6,q3_ring_radius=1125., q4_ring_n=14,q4_ring_radius=1855.,q4_inner_n=7,q4_inner_radius=995.,q4_outer_phase=0.)

@lru_cache(maxsize=128)
def validate_fixed_sites(points,problem):
    from 问题三四_连续覆盖构造 import certify
    if problem not in ('q3','q4'):raise ValueError('Expected q3 or q4')
    result=certify(list(points),problem=problem,minimum_box_m=.25,max_nodes=100000,fail_fast=True)
    if not result['passed']:raise ValueError('Initial continuous discovery coverage is not certified')
    return True

class ObservedSession:
    """策略可见字段白名单；真值由运行器另行保存。"""
    __slots__ = ('__measure', '__clear', '__state')
    def __init__(self, session):
        self.__measure = session.measure
        self.__clear = session.clear
        self.__state = lambda: (session.position, session.channel, session.virtual_time)
    @property
    def position(self): return self.__state()[0]
    @property
    def channel(self): return self.__state()[1]
    @property
    def virtual_time(self): return self.__state()[2]
    def measure(self, point, channel): return self.__measure(point, channel)
    def clear(self, point, channel): return self.__clear(point, channel)

def shifted_route(nodes, start):
    # 不同频道的坐标可能相同，任务身份仍分别保存。
    coordinates = [(p[0]-start[0], p[1]-start[1]) for _,p in nodes]
    route = improved_route(coordinates)
    buckets = {}
    for key,p in nodes: buckets.setdefault((p[0]-start[0],p[1]-start[1]), []).append((key,p))
    result = []
    for p in route:
        if buckets[p]: result.append(buckets[p].pop(0))
    return result

class Solver:
    def __init__(self, session, problem, settings=None):
        self.s = session
        self.problem = problem
        self.cfg = dict(DEFAULT, **(settings or {}))
        self.cfg.setdefault('ready_radius',float('inf'))
        self.cfg.setdefault('centroid',False)
        self.cfg.setdefault('inner_first',False)
        self.cfg.setdefault('first_forward',None)
        self.cfg.setdefault('movable_sectors',False)
        self.cfg.setdefault('sector_pull',1.)
        self.cfg.setdefault('skip_impossible',False)
        self.cfg.setdefault('adaptive_pair',False)
        self.cfg.setdefault('adaptive_clear',False)
        self.tracks = {ch:Track(ch) for ch in range(1,21)}
        self.events = []
        self.scanned = []
        self.measured = {ch:[] for ch in self.tracks}
        self.fixed = coverage_sites(baseline_config(problem))
        if problem=='q3' and self.cfg['q3_ring_n']!=6:
            from 问题三四_连续覆盖构造 import ring_points, open_route
            self.fixed=open_route(ring_points([(self.cfg['q3_ring_n'],self.cfg['q3_ring_radius'],0)]))
        if self.cfg['cover'] == 'ring25' and problem=='q4':
            from 问题三四_连续覆盖构造 import ring_points, open_route
            self.fixed = open_route(ring_points([(8,995,0),(16,1840,0)]))
        if self.cfg['cover'] == 'ring22' and problem=='q4':
            from 问题三四_连续覆盖构造 import ring_points, open_route
            self.fixed = open_route(ring_points([(self.cfg['q4_inner_n'],self.cfg['q4_inner_radius'],0),(self.cfg['q4_ring_n'],self.cfg['q4_ring_radius'],self.cfg['q4_outer_phase'])]))
        self.sectors=None
        if problem=='q3' and self.cfg['movable_sectors']:
            from 问题三_全向扇形约束 import make_sectors
            self.sectors=make_sectors(n=self.cfg['q3_ring_n'],radius=self.cfg['q3_ring_radius'])
            self.fixed=[tuple(s['fallback']) for s in self.sectors]
        validate_fixed_sites(tuple([(0.,0.)]+[tuple(p) for p in self.fixed]),problem)
        self.todo = list(enumerate(self.fixed))
        self.count_stop = False
        self.coverage_complete = False

    def observe(self, ch, p):
        response = self.s.measure(p,ch)
        track = self.tracks[ch]
        track.observe(p,response,1.005)
        self.measured[ch].append(tuple(p))
        if track.poly and not track.inconsistent:
            # 外接32边形包含完整半径1800米源圆域。
            for k in range(32):
                a,b=unit(k*360/32)
                track.poly=clip(track.poly,(a,b,1800.))
            if not track.poly: track.inconsistent=True
            else: track.circle=enclosing_circle(track.poly)
        self.events.append(dict(method='observe',channel=ch,position=p,
            response=response['measure_result'],poly=track.poly))
        if response['measure_result']=='near': self.attempt(track,p,'near')
        return response

    def attempt(self, track, p, method):
        guaranteed=bool((track.near is not None and distance(p,track.near)<=14.99) or
            (track.poly and not track.inconsistent and max(distance(p,q) for q in track.poly)<=19.99))
        ok=self.s.clear(p,track.channel)['clear_result']=='success'
        track.cleared=ok
        if guaranteed and not ok:track.inconsistent=True
        self.events.append(dict(method=method,channel=track.channel,position=p,success=ok,guaranteed=guaranteed))
        if method=='near' and not ok:
            raise RuntimeError('Near-confirmed source failed optical clearance; inconsistent feedback')
        return ok

    def scan(self, p, force=False):
        if not force and self.scanned and min(distance(p,q) for q in self.scanned)<self.cfg['scan_spacing']:
            return
        self.scanned.append(tuple(p))
        for ch,t in sorted(self.tracks.items(), key=lambda kv:(kv[0]!=self.s.channel,kv[0])):
            if t.cleared: continue
            if self.cfg['skip_impossible'] and t.poly and not t.inconsistent and point_region_distance(p,t.poly)>1500.00001:continue
            # 未知频道逐次完成发现扫描；已知目标可从
            # 几何已改变且仍不确定时的新示向获益。
            if t.circle and t.circle[1]<19.99: continue
            if t.observations and min(distance(p,o['position']) for o in t.observations)<60: continue
            self.observe(ch,p)
        if sum(bool(t.observations) for t in self.tracks.values())==16:
            self.count_stop=True
            self.todo=[]
        elif self.sectors:
            from 问题三_全向扇形约束 import safe_sector, sector_certificate
            for i,q in list(self.todo):
                if safe_sector(p,self.sectors[i]):
                    self.todo=[(j,q) for j,q in self.todo if j!=i]
                    self.events.append(dict(method='sector_covered',certificate=sector_certificate(p,self.sectors[i])))
        elif self.cfg['adaptive_cover']:
            self.prune()

    def prune(self):
        from 问题三四_连续覆盖构造 import certify
        # 只有证书同时包含实际已检测位置和
        # 全部仍承诺访问的站点时才允许删去未来访问；重复删站保持
        # 此不变量，退出时只剩实际检测位置。
        ordered=sorted(self.todo,key=lambda row:distance(self.s.position,row[1]),reverse=True)
        for i,p in ordered:
            if min(distance(p,q) for q in self.scanned)>self.cfg['prune_distance']:continue
            others=[q for j,q in self.todo if j!=i]
            evidence=certify(self.scanned+others,problem=self.problem,
                minimum_box_m=1. if self.problem=='q3' else self.cfg['prune_min_box'],fail_fast=True)
            if evidence['passed']:
                self.todo=[(j,q) for j,q in self.todo if j!=i]
                self.events.append(dict(method='certified_site_deleted',site_index=i,position=p))

    def target_point(self,t):
        if t.near is not None:return t.near
        if not t.circle:return t.first[0]
        c,r=t.circle
        if self.cfg['centroid'] and t.poly and len(t.poly)>2:
            area=cx=cy=0.
            for a,b in zip(t.poly,t.poly[1:]+t.poly[:1]):
                cross=a[0]*b[1]-b[0]*a[1]
                area+=cross;cx+=(a[0]+b[0])*cross;cy+=(a[1]+b[1])*cross
            if abs(area)>1e-8:c=(cx/(3*area),cy/(3*area))
        if r<200 or len(t.observations)>=2:return c
        origin,angle=t.first
        if self.cfg['first_forward'] is not None:
            u=unit(angle)
            c=(origin[0]+self.cfg['first_forward']*u[0],origin[1]+self.cfg['first_forward']*u[1])
        ux,uy=unit(angle+90)
        amount=self.cfg['lateral']
        candidates=[(c[0]+sign*amount*ux,c[1]+sign*amount*uy) for sign in [-1,1]]
        return min(candidates,key=lambda p:distance(self.s.position,p))

    def resolve(self,t):
        if t.cleared:return
        if t.near is not None:
            self.attempt(t,t.near,'near');return
        p=self.target_point(t)
        if t.circle and (len(t.observations)==1 and t.circle[1]>=200):
            pair=None
            if self.cfg['pair_probe']:
                from 问题三四_安全定位候选 import safe_pair_candidates, negative_pair_plane
                forward=600.
                lateral=self.cfg['lateral']
                if self.cfg['adaptive_pair']:
                    u=unit(t.first[1]);o=t.first[0]
                    xs=[(q[0]-o[0])*u[0]+(q[1]-o[1])*u[1] for q in t.poly]
                    forward=(min(xs)+max(xs))/2
                    lateral=min(120.,max(30.,(max(xs)-min(xs))*.15))
                pair=safe_pair_candidates(t,forward=forward,lateral=lateral)
            if pair:
                responses=[]
                for q in pair['points']:
                    responses.append(self.observe(t.channel,q))
                    if responses[-1]['measure_result']!='no_signal':break
                plane=negative_pair_plane(pair,responses)
                if plane:
                    t.poly=clip(t.poly,plane)
                    if not t.poly:t.inconsistent=True
                    else:t.circle=enclosing_circle(t.poly)
                    self.events.append(dict(method='two_sided_negative_halfplane',channel=t.channel,
                        pair=pair,responses=responses,poly=t.poly))
            else:self.observe(t.channel,p)
            if self.cfg['extra_scan']:self.scan(self.s.position)
        for j in range(self.cfg['probe_rounds']):
            if t.cleared:return
            p=t.circle[0] if t.circle and not t.inconsistent else self.target_point(t)
            if self.attempt(t,p,'center_probe'):
                break
            self.observe(t.channel,p)
            if t.cleared:return
            if self.cfg['adaptive_pair'] and t.circle and t.circle[1]>25 and not t.inconsistent:
                from 问题三四_安全定位候选 import safe_pair_candidates, negative_pair_plane
                u=unit(t.first[1]);o=t.first[0]
                xs=[(q[0]-o[0])*u[0]+(q[1]-o[1])*u[1] for q in t.poly]
                pair=safe_pair_candidates(t,forward=max(.001,(min(xs)+max(xs))/2),
                    lateral=min(120.,max(30.,(max(xs)-min(xs))*.15)))
                if pair:
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
                    continue
            if t.circle and distance(t.circle[0],p)<5 and t.circle[1]>20:
                # 测点可能不可接收，或与已有示向形成较差交会角。
                origin,angle=t.first
                ux,uy=unit(angle+90)
                offset=min(self.cfg['lateral'],max(30,t.circle[1]*.5))
                side=1 if j%2==0 else -1
                self.observe(t.channel,(p[0]+side*offset*ux,p[1]+side*offset*uy))
        if not t.cleared:
            if self.cfg['adaptive_clear']:
                from 问题三四_光学清除覆盖 import clear_cover
                cover=clear_cover(t,start=self.s.position)
                if cover:
                    self.events.append(dict(method='adaptive_clear_cover',channel=t.channel,certificate=cover['certificate'],poly=t.poly))
                    for p in cover['points']:
                        if self.attempt(t,p,'adaptive_clear_cell'):break
                    if not t.cleared:
                        t.inconsistent=True
                        self.events.append(dict(method='adaptive_clear_cover_exhausted',channel=t.channel,success=False))
        if not t.cleared:
            points=fallback_sites(*t.first)
            if t.poly and not t.inconsistent:
                filtered=[p for p in points if point_region_distance(p,t.poly)<=20.00001]
            else:filtered=points
            done=set()
            for group in [filtered,points]:
                if distance(self.s.position,group[-1])<distance(self.s.position,group[0]) if group else False:
                    group=list(reversed(group))
                for p in group:
                    if p in done:continue
                    done.add(p)
                    if self.attempt(t,p,'finite_fallback'):break
                if t.cleared:break
        if not t.cleared:raise RuntimeError('Certified fallback exhausted')
        # 同位置光学试清无需移动，也不要求定向无线电接收。
        for other in self.tracks.values():
            if other.cleared or not other.poly:continue
            if point_region_distance(self.s.position,other.poly)<=19.99:
                self.attempt(other,self.s.position,'shared_probe')
        if self.cfg['extra_scan']:self.scan(self.s.position)

    def run(self):
        self.scan((0.,0.),True)
        self.todo=[(i,p) for i,p in self.todo if distance(p,(0.,0.))>1e-7]
        while self.todo or any(t.observations and not t.cleared for t in self.tracks.values()):
            pending=[t for t in self.tracks.values() if t.observations and not t.cleared]
            all_pending=list(pending)
            if self.todo:
                pending=[t for t in pending if t.near is not None or (t.circle and t.circle[1]<=self.cfg['ready_radius'])]
            active_todo=self.todo
            if self.sectors and all_pending:
                from 问题三_全向扇形约束 import project_sector
                proposed=[]
                predicted=[self.target_point(t) for t in all_pending]
                for i,p in active_todo:
                    desired=min(predicted,key=lambda q:distance(q,p))
                    pull=self.cfg['sector_pull']
                    desired=(p[0]+pull*(desired[0]-p[0]),p[1]+pull*(desired[1]-p[1]))
                    proposed.append((i,project_sector(desired,self.sectors[i])))
                active_todo=proposed
            if self.problem=='q4' and self.cfg['inner_first']:
                inner=[(i,p) for i,p in active_todo if math.hypot(*p)<1100]
                if inner:active_todo=inner
            prospective_scan=False
            if self.cfg['prospective'] and pending and self.todo:
                from 问题三四_连续覆盖构造 import certify
                predicted=[self.target_point(t) for t in pending]
                active_todo=list(self.todo)
                for i,p in sorted(self.todo,key=lambda row:distance(self.s.position,row[1]),reverse=True):
                    if min(distance(p,q) for q in predicted)>self.cfg['prune_distance']:continue
                    if certify(self.scanned+predicted+[q for j,q in active_todo if j!=i],
                        problem=self.problem,minimum_box_m=1 if self.problem=='q3' else self.cfg['prune_min_box'],fail_fast=True)['passed']:
                        active_todo=[(j,q) for j,q in active_todo if j!=i]
                        prospective_scan=True
                # 计划测站只帮助选择路线，不能据此确认
                # 频道不存在；原未访问站仍保存在待办集合中。
            nodes=[(('scan',i),p) for i,p in active_todo]
            if self.cfg['joint'] or not nodes:
                nodes += [(('target',t.channel),self.target_point(t)) for t in pending]
            key,p=shifted_route(nodes,self.s.position)[0]
            if key[0]=='scan':
                self.todo=[(i,q) for i,q in self.todo if i!=key[1]]
                self.scan(p,True)
            else:
                if prospective_scan:
                    self.scan(p,True)
                self.resolve(self.tracks[key[1]])
        self.coverage_complete=not self.todo
        cleared=sorted(ch for ch,t in self.tracks.items() if t.cleared)
        absent=sorted(ch for ch,t in self.tracks.items() if not t.observations)
        complete=len(cleared)+len(absent)==20 and 10<=len(cleared)<=16 and not any(t.inconsistent for t in self.tracks.values())
        return dict(termination='coverage_complete' if complete else 'incomplete',cleared_channels=cleared,absent_channels=absent,
            coverage_evidence=dict(kind='source_count_upper_bound' if self.count_stop else ('continuous_actual_sites' if self.cfg['adaptive_cover'] or self.sectors else 'fixed_sites'),
                problem=self.problem,design=self.cfg['cover'],sites=self.fixed,
                actual_scan_sites=self.scanned,
                measurements_per_channel=self.measured),
            geometry_inconsistencies=[ch for ch,t in self.tracks.items() if t.inconsistent],
            events=self.events,tracks=[t.snapshot() for t in self.tracks.values() if t.observations])

def solve(session, problem, settings=None):
    return Solver(session,problem,settings).run()
