"""只根据合法动作历史使用Q3全向阴性接收证据。"""
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from 问题三四_几何求解基线 import Solver
from 问题三四_测向动作选择 import SenseSolver
from 问题一_定位区域与包围圆 import convex_hull, clip, enclosing_circle, distance


def outward_hull(polygon,padding=1e-6):
    return convex_hull([(p[0]+dx,p[1]+dy) for p in polygon
                       for dx in (-padding,padding) for dy in (-padding,padding)])


def outside_disk_hull(polygon, center, radius=999.9):
    """构造多边形扣除开圆盘后的保守凸包。
    剩余紧集上线性函数的极值可在原多边形边界取得：内部圆弧点仍可沿远离圆心方向微移。因此只需保留外侧顶点和圆与边的交点。排除半径另留0.1米余量。"""
    radius_sq = radius*radius
    points = [tuple(p) for p in polygon
              if (p[0]-center[0])**2+(p[1]-center[1])**2 >= radius_sq]
    if len(points) == len(polygon):
        return list(polygon)
    for p, q in zip(polygon, polygon[1:]+polygon[:1]):
        dx, dy = q[0]-p[0], q[1]-p[1]
        sx, sy = p[0]-center[0], p[1]-center[1]
        aa = dx*dx+dy*dy
        if aa == 0:
            continue
        bb, cc = 2*(sx*dx+sy*dy), sx*sx+sy*sy-radius_sq
        discriminant = bb*bb-4*aa*cc
        # 接近相切的数值状态不能作为舍弃支撑点的理由。
        tolerance = 1e-12*max(1., bb*bb, abs(4*aa*cc))
        if discriminant < -tolerance:
            continue
        root = math.sqrt(max(0.,discriminant))
        for fraction in ((-bb-root)/(2*aa),(-bb+root)/(2*aa)):
            if -1e-10 <= fraction <= 1+1e-10:
                fraction = min(1.,max(0.,fraction))
                points.append((p[0]+fraction*dx,p[1]+fraction*dy))
    return convex_hull(points)


class NegativeSolver(SenseSolver):
    def __init__(self, session, problem, settings=None):
        if problem != 'q3':
            raise ValueError('Omni negative-distance evidence is Q3-only')
        super().__init__(session,problem,settings)
        self.negative_points={ch:[] for ch in self.tracks}
        self.cfg.setdefault('negative_disk', True)
        self.cfg.setdefault('radius_consistency', True)
        self.cfg.setdefault('service_clear', False)
        self.cfg.setdefault('replace_scan', False)
        if self.cfg['replace_scan']:
            self.cfg['adaptive_cover']=True

    def observe(self,ch,p):
        response=super().observe(ch,p)
        if response['measure_result']=='no_signal':
            self.negative_points[ch].append(dict(position=tuple(p),measure_index=len(self.measured[ch])))
        track=self.tracks[ch]
        if track.cleared or not track.poly or track.inconsistent:
            return response
        for negative_record in self.negative_points[ch]:
            negative=negative_record['position']
            before=list(track.poly)
            planes=[]
            if self.cfg['radius_consistency']:
                for positive in track.observations:
                    positive=positive['position']
                    # 平移坐标后展开平方距离比较，
                    # 避免直接相减两个较大的平方范数。
                    dx,dy=negative[0]-positive[0],negative[1]-positive[1]
                    plane=(2*dx,2*dy,
                           2*dx*positive[0]+2*dy*positive[1]+dx*dx+dy*dy)
                    track.poly=clip(track.poly,plane)
                    planes.append(plane)
                if track.poly:
                    track.poly=outward_hull(track.poly)
            mid=list(track.poly)
            if self.cfg['negative_disk'] and track.poly:
                track.poly=outside_disk_hull(track.poly,negative)
                if track.poly:
                    track.poly=outward_hull(track.poly)
            if not track.poly:
                track.inconsistent=True
                track.circle=None
                self.events.append(dict(method='q3_negative_region_empty',channel=ch,
                    negative_position=negative,prior_poly=before,poly=[]))
                return response
            if track.poly != before:
                track.circle=enclosing_circle(track.poly)
                self.events.append(dict(method='q3_negative_reception',channel=ch,
                    negative_position=negative,excluded_radius_m=999.9 if self.cfg['negative_disk'] else None,
                    negative_measure_index=negative_record['measure_index'],
                    positives_used=[o['position'] for o in track.observations],
                    outward_padding_m=1e-6 if self.cfg['negative_disk'] else 0.,
                    mid_outward_padding_m=1e-6 if self.cfg['radius_consistency'] else 0.,
                    radius_comparison_planes=planes,prior_poly=before,
                    poly_after_radius_comparison=mid,poly=track.poly))
        return response

    def attempt(self,track,p,method):
        if (self.cfg.get('service_clear',False) and method=='center_probe'
                and track.poly and not track.inconsistent):
            radius=max(distance(p,q) for q in track.poly)
            budget=max(0.,19.99-radius)
            length=distance(self.s.position,p)
            if length>0 and budget>0:
                t=min(1.,budget/length)
                p=(p[0]+t*(self.s.position[0]-p[0]),p[1]+t*(self.s.position[1]-p[1]))
        return super().attempt(track,p,method)

    def resolve(self,track):
        if self.cfg.get('nearest_pair',False):
            import 问题三四_安全定位候选 as localization
            original=localization.safe_pair_candidates
            def nearest(*args,**kwargs):
                pair=original(*args,**kwargs)
                if pair and distance(self.s.position,pair['points'][1])<distance(self.s.position,pair['points'][0])-1e-9:
                    pair=dict(pair,points=list(reversed(pair['points'])),
                              max_source_distance_m=list(reversed(pair['max_source_distance_m'])))
                return pair
            localization.safe_pair_candidates=nearest
            try:super().resolve(track)
            finally:localization.safe_pair_candidates=original
        else:
            super().resolve(track)
        if (not track.cleared or not self.cfg['replace_scan'] or not self.todo or
                not any(not t.observations for t in self.tracks.values())):
            return
        from 问题三四_连续覆盖构造 import certify
        point=tuple(self.s.position)
        if any(distance(point,q)<1e-7 for q in self.scanned):
            return
        profitable=False
        for identity,site in sorted(self.todo,key=lambda row:distance(point,row[1])):
            proposed=self.scanned+[point]+[q for i,q in self.todo if i!=identity]
            result=certify(proposed,problem='q3',minimum_box_m=1.,max_nodes=12000,fail_fast=True)
            if result['passed']:
                profitable=True
                break
        if not profitable:
            return
        # 在此实际检测每个未知频道；已知频道
        # 无需这次仅用于发现的动作。只有实际检测才能登记覆盖，
        # 仅到达清除终点不算完成检测覆盖。
        self.scanned.append(point)
        unknown=[ch for ch,t in self.tracks.items() if not t.observations]
        for ch in sorted(unknown,key=lambda ch:(ch!=self.s.channel,ch)):
            self.observe(ch,point)
        self.events.append(dict(method='q3_conditional_actual_scan',point=point,
                                channels_measured=unknown))
        if sum(bool(t.observations) for t in self.tracks.values())==16:
            self.count_stop=True
            self.todo=[]
        else:
            self.prune()


def solve(session,problem,settings=None):
    return NegativeSolver(session,problem,settings).run()
