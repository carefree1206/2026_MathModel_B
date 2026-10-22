"""生成M021的独立实验场景；构造假设不代表官方分布。"""
import math,random
def make_case(problem,index,stage='development',kind='uniform'):
    offsets={'development':91000000,'validation':92000000,'test':93000000,'stress':94000000}
    seed=offsets[stage]+index+(100000 if problem=='q4' else 0)
    rng=random.Random(seed);n=10+index%7;sources=[]
    directional=set(rng.sample(range(n),rng.randint(1,n-1))) if problem=='q4' else set()
    if kind=='all_directional' and problem=='q4':directional=set(range(n))
    center_angle=rng.random()*2*math.pi
    center=(1300*math.cos(center_angle),1300*math.sin(center_angle))
    for j,ch in enumerate(rng.sample(range(1,21),n)):
        angle=rng.random()*2*math.pi;radius=1800*math.sqrt(rng.random())
        x,y=radius*math.cos(angle),radius*math.sin(angle)
        if kind=='boundary':
            radius=rng.uniform(1750,1800);x,y=radius*math.cos(angle),radius*math.sin(angle)
        if kind=='cluster':
            x,y=center[0]+rng.gauss(0,60),center[1]+rng.gauss(0,60)
            length=math.hypot(x,y)
            if length>1800:x,y=x*1799/length,y*1799/length
        receive=1000. if kind in ('minimum_radius','boundary') else rng.uniform(1000,1500)
        if kind=='maximum_radius':receive=1500.
        orientation=rng.uniform(0,360) if j in directional else None
        if kind=='outward' and j in directional:orientation=math.degrees(math.atan2(y,x))%360
        sources.append(dict(id='m021-source-%d'%j,channel=ch,x_m=x,y_m=y,reception_radius_m=receive,orientation_deg=orientation))
    error=dict(type='hash',seed=seed+900000000)
    if kind in ('error_plus','error_minus'):error=dict(type='constant',value_deg=1. if kind=='error_plus' else -1.)
    return dict(schema_version=1,case_kind='full',case_id='m021-%s-%s-%s-%06d'%(stage,problem,kind,index),
        problem=problem,seed=seed,sources=sources,error_model=error,
        provenance='M021 independent synthetic '+stage+'; distribution assumptions are not official')
