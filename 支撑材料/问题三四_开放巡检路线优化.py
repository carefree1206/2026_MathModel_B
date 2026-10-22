"""确定性开放路径优化；规模较小的固定点集使用Held–Karp精确求解。"""
import math

def matrix(points,start):
    all_points=list(points)+[start]
    return [[math.dist(p,q) for q in all_points] for p in all_points]
def cost(order,d):
    return sum(d[a][b] for a,b in zip([len(d)-1]+list(order[:-1]),order))
def two_opt(order,d):
    order=list(order);n=len(order);origin=len(d)-1
    while True:
        best=-1e-8;pair=None
        for i in range(n-1):
            a=origin if i==0 else order[i-1];b=order[i]
            for j in range(i+1,n):
                c=order[j];delta=d[a][c]-d[a][b]
                if j+1<n:delta+=d[b][order[j+1]]-d[c][order[j+1]]
                if delta<best:best,pair=delta,(i,j)
        if pair is None:return order
        i,j=pair;order[i:j+1]=reversed(order[i:j+1])
def exact(points,start):
    n=len(points);d=matrix(points,start)
    if not n:return [],0.
    dp={(1<<i,i):(d[n][i],None) for i in range(n)}
    for mask in range(1,1<<n):
        for last in range(n):
            if (mask,last) not in dp:continue
            value,_=dp[mask,last]
            for nxt in range(n):
                if mask>>nxt&1:continue
                key=(mask|1<<nxt,nxt);candidate=value+d[last][nxt]
                if key not in dp or candidate<dp[key][0]-1e-10:dp[key]=(candidate,last)
    full=(1<<n)-1;last=min(range(n),key=lambda i:dp[full,i][0]);best=dp[full,last][0]
    order=[];mask=full
    while last is not None:
        order.append(last);previous=dp[mask,last][1];mask^=1<<last;last=previous
    return list(reversed(order)),best
def optimize(points,start,initial,exact_limit=10,relocate=True):
    n=len(points);d=matrix(points,start)
    if n<=exact_limit:
        order,value=exact(points,start)
        return order,dict(method='held_karp_fixed_points_float',nodes=n,length_m=value,
                          guarantee='Fixed predicted coordinates only; not online total-cost optimality')
    candidates=[two_opt(initial,d),two_opt(list(reversed(initial)),d)]
    for first in range(n):
        remaining=set(range(n));remaining.remove(first);order=[first]
        while remaining:
            nxt=min(remaining,key=lambda j:(d[order[-1]][j],j));remaining.remove(nxt);order.append(nxt)
        candidates.append(two_opt(order,d))
    best=min(candidates,key=lambda order:(cost(order,d),order));value=cost(best,d)
    if relocate:
        while True:
            change=None;new_value=value
            for width in (1,2,3):
                for i in range(n-width+1):
                    block=best[i:i+width];rest=best[:i]+best[i+width:]
                    for j in range(len(rest)+1):
                        if j==i:continue
                        trial=rest[:j]+block+rest[j:];v=cost(trial,d)
                        if v<new_value-1e-7:new_value,change=v,trial
            if change is None:break
            best=two_opt(change,d);value=cost(best,d)
    return best,dict(method='all_first_nearest_two_opt_relocation',nodes=n,length_m=value,
                     guarantee='Improves retained route on these predicted points; no global optimality claim')
