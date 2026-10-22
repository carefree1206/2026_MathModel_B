"""复核27点与21点的连续覆盖证书和存档开放路径。"""
from pathlib import Path
import argparse,json,math,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from 问题三四_正式算法与参数入口 import load, read, save

def run(out):
    load('q4')
    from 问题三四_连续覆盖构造 import verify_certificate
    rows=[]
    for item in read(ROOT/'数据/layout_comparison.json')['layouts']:
        cert=read(ROOT/'数据/layouts'/(item['name']+'_certificate.json'))
        points=[tuple(p) for p in item['points']];route=[tuple(p) for p in item['route']]
        assert len(set(points))==len(points)==item['summary']['stations']
        assert sorted(points)==sorted(route)
        assert cert['points_mm']==[[int(round(x*1000)),int(round(y*1000))] for x,y in points]
        assert verify_certificate(cert)
        path=[(0.,0.)]+route
        distance=sum(math.dist(a,b) for a,b in zip(path,path[1:]))
        assert abs(distance-item['summary']['route_length_m'])<1e-6
        rows.append(dict(name=item['name'],stations=len(points),route_length_m=distance,continuous_certificate=True))
    result=dict(passed=True,scope='固定布局与存档开放路径；非最短路或整场性能保证',rows=rows,network_requests=0)
    save(out,result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'results/layout_check.json')
    print(json.dumps(run(parser.parse_args().output),ensure_ascii=False,indent=2))
