"""用外包多边形向量化评价Q2不确定性，不调用模拟器。"""
import math
import numpy as np

def outer_prior(delta=1.005, arc_segments=16):
    # 用相邻切线交点外包半径1500米的首测扇区。
    d=math.radians(delta)
    angles=np.linspace(-d,d,arc_segments+1)
    points=[(0.,0.),(1500*math.cos(d),-1500*math.sin(d))]
    for a,b in zip(angles[:-1],angles[1:]):
        r=1500/math.cos((b-a)/2)
        points.append((r*math.cos((a+b)/2),r*math.sin((a+b)/2)))
    points.append((1500*math.cos(d),1500*math.sin(d)))
    return np.asarray(points)

def clip_batch(vertices,counts,normals,cs):
    n,k,_=vertices.shape
    idx=np.arange(k)[None,:]
    nxt=(idx+1)%np.maximum(counts[:,None],1)
    following=vertices[np.arange(n)[:,None],nxt]
    fp=np.einsum('nki,ni->nk',vertices,normals)-cs[:,None]
    fq=np.einsum('nki,ni->nk',following,normals)-cs[:,None]
    valid=idx<counts[:,None]
    keep=(fp<=0)&valid
    cut=((fp<=0)!=(fq<=0))&valid
    denom=fp-fq
    ratio=np.divide(fp,denom,out=np.zeros_like(fp),where=denom!=0)
    crossing=vertices+ratio[:,:,None]*(following-vertices)
    stream=np.stack([vertices,crossing],axis=2).reshape(n,2*k,2)
    flags=np.stack([keep,cut],axis=2).reshape(n,2*k)
    rank=np.cumsum(flags,axis=1)-1
    newcounts=flags.sum(axis=1)
    output=np.zeros((n,k+1,2))
    ni,ki=np.where(flags)
    output[ni,rank[ni,ki]]=stream[ni,ki]
    return output,newcounts

def posterior_batch(point,readings,delta=1.005,prior=None):
    prior=outer_prior(delta) if prior is None else np.asarray(prior)
    n=len(readings)
    vertices=np.broadcast_to(prior,(n,len(prior),2)).copy()
    counts=np.full(n,len(prior),dtype=int)
    for sign in (-1,1):
        angle=np.radians(readings+sign*delta)
        normal=sign*np.stack([-np.sin(angle),np.cos(angle)],axis=1)
        c=normal@np.asarray(point)+1e-7
        vertices,counts=clip_batch(vertices,counts,normal,c)
    # 枚举全部保留顶点对，以最大距离作为直径。
    best=np.zeros(n)
    pairs=np.zeros((n,2,2))
    k=vertices.shape[1]
    for i in range(k):
        for j in range(i):
            d=np.linalg.norm(vertices[:,i]-vertices[:,j],axis=1)
            valid=(i<counts)&(j<counts)&(d>best)
            best[valid]=d[valid]
            pairs[valid,0]=vertices[valid,i]
            pairs[valid,1]=vertices[valid,j]
    return best,pairs

def bound(point,step=.01,delta=1.005,arc_segments=16):
    prior=outer_prior(delta,arc_segments)
    angles=np.unwrap(np.arctan2(prior[:,1]-point[1],prior[:,0]-point[0]))
    lo,hi=np.degrees([min(angles),max(angles)])
    n=max(2,math.ceil((hi-lo+2*delta)/step))
    edges=np.linspace(lo-delta,hi+delta,n+1)
    half=(edges[1]-edges[0])/2
    readings=(edges[:-1]+edges[1:])/2
    value=-1
    witness=None
    for start in range(0,n,1000):
        b=readings[start:start+1000]
        ds,pairs=posterior_batch(point,b,delta+half,prior)
        i=int(np.argmax(ds))
        if ds[i]>value:
            value=float(ds[i]); witness={'reading_bin_center_deg':float(b[i]),
                'outer_pair_m':pairs[i].tolist()}
    return {'upper_m':value+1e-5,'angle_step_deg':2*half,'bins':n,
            'arc_segments':arc_segments,'outer_arc_excess_m':1500*(1/math.cos(math.radians(delta)/arc_segments)-1),
            'witness_bin':witness,'numerics':'outward 1e-7 m halfplanes, 1e-5 m reported guard; floating-point geometry'}

def sector_witness(point,delta=1.005):
    # 在两条角边界上构造可行点对，其中A是真实圆弧端点。
    d=math.radians(delta)
    best={'lower_m':0}
    for sign in (-1,1):
        A=np.array([1500*math.cos(d),sign*1500*math.sin(d)])
        beta=math.atan2(A[1]-point[1],A[0]-point[0])
        ray=np.array([math.cos(-sign*d),math.sin(-sign*d)])
        for turn in (-1,1):
            angle=beta+turn*2*d
            v=np.array([math.cos(angle),math.sin(angle)])
            try:r,t=np.linalg.solve(np.column_stack([ray,-v]),np.asarray(point))
            except np.linalg.LinAlgError:continue
            B=r*ray
            if 5<r<=1500 and t>5 and math.dist(A,point)>5:
                dist=float(np.linalg.norm(A-B))
                if dist>best['lower_m']:
                    best={'lower_m':dist,'points_m':[A.tolist(),B.tolist()],
                          'first_reading_deg':0.,'second_reading_deg':math.degrees(beta+turn*d),
                          'reception_radius_m':1500.}
    return best
