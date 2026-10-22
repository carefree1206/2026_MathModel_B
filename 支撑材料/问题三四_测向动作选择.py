"""在已经到达的停车位置，对有价值的已知频道补测。"""
import math
from 问题三四_几何求解基线 import Solver
from 问题一_定位区域与包围圆 import distance, point_region_distance, unit


class SenseSolver(Solver):
    def useful(self,t):
        p=self.s.position
        if t.cleared or t.inconsistent or not t.poly or not t.circle:return False
        if t.circle[1]<self.cfg.get('sense_radius',80.):return False
        if min(distance(p,q) for q in self.measured[t.channel])<60:return False
        if point_region_distance(p,t.poly)>1500.00001:return False
        if distance(p,t.circle[0])<20:return True
        first,bearing=t.first;u=unit(bearing)
        v=((t.circle[0][0]-p[0])/distance(p,t.circle[0]),(t.circle[0][1]-p[1])/distance(p,t.circle[0]))
        return abs(u[0]*v[1]-u[1]*v[0])>=self.cfg.get('sense_sine',.1)

    def resolve(self,t):
        if self.cfg.get('pre_sense',False) and self.useful(t):
            self.observe(t.channel,self.s.position)
            # 原地补测一次后，交回主循环重新排序。
            # 有用性检查拒绝重复测点，因此不会在原地卡住循环。
            return
        super().resolve(t)
        if self.cfg.get('post_sense',False):
            for ch,other in sorted(self.tracks.items(),key=lambda kv:(kv[0]!=self.s.channel,kv[0])):
                if self.useful(other):self.observe(ch,self.s.position)


def solve(session,problem,settings=None):
    return SenseSolver(session,problem,settings).run()
