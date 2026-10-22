"""M020按实际动作费用和天线模型排名，并限制后验试清次数。"""
from 问题三四_物理约束调度 import CorrectedMixin
from 问题三四_完整费用选点 import Cost5Q3, Cost5Q4


class CandidateQ3(CorrectedMixin,Cost5Q3):pass
class CandidateQ4(CorrectedMixin,Cost5Q4):pass


def solve(session,problem,settings=None):
    return (CandidateQ3 if problem=='q3' else CandidateQ4)(session,problem,settings).run()
