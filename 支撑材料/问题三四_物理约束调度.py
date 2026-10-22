"""将M020名义信息评分的天线半角修正为90°。
早期排名近似曾取60°，该值未改变真实测量或覆盖证书；修正候选独立保存以支持同场比较。"""
import math
from 问题三四_信息调度基线 import SchedulingMixin, angle_delta
from 问题三四_几何求解基线 import Solver
from 问题三_阴性观测收缩 import NegativeSolver
from 问题三四_模型加载 import baseline_settings
from 问题一_定位区域与包围圆 import distance, clip, enclosing_circle, bearing_planes

class CorrectedMixin(SchedulingMixin):
    def predicted_gain(self,t,p):
        if self.problem=='q3':return super().predicted_gain(t,p)
        if t.cleared or t.inconsistent or not t.circle or not t.poly:return 0.
        center,radius=t.circle
        if radius<40:return 0.
        if self.measured[t.channel] and min(distance(p,q) for q in self.measured[t.channel])<60:return 0.
        length=distance(p,center)
        if not 25.<length<1450.:return 0.
        angle=math.degrees(math.atan2(center[1]-p[1],center[0]-p[0]))%360.
        narrowed=list(t.poly)
        for plane in bearing_planes(p,angle,1.005,max_range=1500.):narrowed=clip(narrowed,plane)
        if not narrowed:return 0.
        gain=max(0.,radius-enclosing_circle(narrowed)[1])
        views=[math.degrees(math.atan2(o['position'][1]-center[1],o['position'][0]-center[0])) for o in t.observations]
        view=math.degrees(math.atan2(p[1]-center[1],p[0]-center[0]))
        allowed=[a for a in range(0,360,5) if all(abs(angle_delta(a,v))<=90 for v in views)]
        directional=sum(abs(angle_delta(a,view))<=90 for a in allowed)/len(allowed) if allowed else 0.
        return gain*(.5+.5*directional)

class Q3CorrectedSolver(CorrectedMixin,NegativeSolver):pass
class Q4CorrectedSolver(CorrectedMixin,Solver):pass

def solve(session,problem,settings=None):
    return (Q3CorrectedSolver if problem=='q3' else Q4CorrectedSolver)(session,problem,
        settings if settings is not None else baseline_settings(problem)).run()
