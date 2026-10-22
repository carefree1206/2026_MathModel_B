"""Q2利用首次接收信息选择全向源第二测站。
此独立选点不改变Q3/Q4在线策略，坐标以米计，输入须为正常示向而非近距响应。"""
import math
from 问题一_定位区域与包围圆 import unit

CHOICES = {'legacy': (750.0, 500.0), 'balanced': (710.0, 555.0),
           'accuracy': (840.0, 548.0)}


def reception_candidate_region(position=(0.0, 0.0), bearing=0.0, delta=1.005):
    """四个闭圆盘的交集，对首测局部环扇区信息给出精确条件。
    首距r大于5米且不超过1500米；首次接收给出R≥r，因此第二距离须不超过max(1000,r)。只需检查r=5、1000及两条角边界。取5米闭包不改变对r>5的统一保证；未叠加全局源圆域时，该域对具体首测位置充分，但未必最大。"""
    if not all(math.isfinite(v) for v in (*position, bearing, delta)):
        raise ValueError('Coordinates, bearing and delta must be finite')
    if not 0 < delta < 45:
        raise ValueError('This Q2 construction requires 0 < delta < 45 degrees')
    centers=[]
    for r in (5.0, 1000.0):
        for sign in (-1, 1):
            u=unit(bearing+sign*delta)
            centers.append((position[0]+r*u[0], position[1]+r*u[1]))
    return {'disk_centers': centers, 'disk_radius_m': 1000.0,
            'first_distance_closure_m': [5.0, 1500.0],
            'assumption': 'normal first bearing; omnidirectional; fixed unknown reception radius',
            'scope': 'exact local annular-sector domain, sufficient with global source-disk clipping'}


def select_second_point(position=(0.0, 0.0), bearing=0.0,
                        preference='accuracy', side=1, delta=1.005):
    """返回冻结的Q2候选及费用和接收信息。
    精度候选以额外行走换较小的最坏直径；均衡候选保留旧路程预算。两者均未证明全局最优，镜像侧的选择不使用真值。"""
    if preference not in CHOICES:
        raise ValueError('preference must be legacy, balanced or accuracy')
    if side not in (-1, 1):
        raise ValueError('side must be -1 or 1')
    region=reception_candidate_region(position,bearing,delta)
    a,b=CHOICES[preference]
    u,v=unit(bearing),unit(bearing+90)
    p=(position[0]+a*u[0]+side*b*v[0],position[1]+a*u[1]+side*b*v[1])
    slack=1000-max(math.dist(p,c) for c in region['disk_centers'])
    if slack < 1e-6:
        raise ValueError('Selected point has no safety margin at this error bound')
    return {'point_m': p, 'local_point_m': [a,side*b], 'preference':preference,
            'move_distance_m': math.hypot(a,b), 'move_time_s': math.hypot(a,b)/5,
            'disk_constraint_slack_m':slack,'guaranteed_omni_reception':True,
            'near_response_action':'clear immediately; a second bearing is unnecessary',
            'global_optimality_proven':False}
