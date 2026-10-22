"""逐动作复算一个跨版本边界压力案例；不重跑历史程序，不连接模拟器。"""
from pathlib import Path
import argparse,gzip,hashlib,json,math

HERE=Path(__file__).resolve().parent/'数据/问题三四稳健性'
def read(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def audit(value):
    rows=value['records'];position=(0.,0.);channel=1;total=0.;distance=0.
    costs=dict(move_s=0.,measure_s=0.,switch_s=0.,optical_s=0.,laser_s=0.)
    ledger=[];discoveries={};clears=[];failed=[]
    for i,row in enumerate(rows,1):
        step={key:0. for key in costs};length=math.dist(position,row['p'])
        step['move_s']=length/5;distance+=length
        if row['action']=='measure':
            step['measure_s']=5.;step['switch_s']=float(channel!=row['ch']);channel=row['ch']
            if row['result']!='no_signal' and row['ch'] not in discoveries:
                discoveries[row['ch']]=dict(action=i,position=row['p'],time_s=row['time'],travel_m=distance,bearing=row['bearing'])
        else:
            step['optical_s']=3.;step['laser_s']=2.*(row['result']=='success')
            entry=dict(channel=row['ch'],action=i,position=row['p'],time_s=row['time'],travel_m=distance)
            (clears if row['result']=='success' else failed).append(entry)
        total+=sum(step.values())
        assert abs(total-row['time'])<1e-6,(i,total,row['time'])
        for k,v in step.items():costs[k]+=v
        ledger.append(dict(action=i,request=row,from_position=position,step=step,distance_m=length,cumulative_travel_m=distance))
        position=row['p']
    for k,v in costs.items():assert abs(v-value['cost'][k])<1e-6
    scan=[]
    for order,p in enumerate(value['solution']['coverage_evidence']['actual_scan_sites'],1):
        found=next(x for x in ledger if x['request']['action']=='measure' and math.dist(x['request']['p'],p)<1e-8)
        scan.append(dict(order=order,position=p,first_action=found['action'],time_s=found['request']['time'],travel_m=found['cumulative_travel_m']))
    intervals=[]
    for left,right in zip(scan,scan[1:]):
        straight=math.dist(left['position'],right['position'])
        actual=right['travel_m']-left['travel_m']
        intervals.append(dict(from_scan=left['order'],to_scan=right['order'],from_position=left['position'],to_position=right['position'],
            from_action=left['first_action'],to_action=right['first_action'],straight_m=straight,actual_m=actual,extra_m=actual-straight,
            cleared_channels=[r['channel'] for r in clears if left['first_action']<=r['action']<right['first_action']]))
    fixed_length=sum(r['straight_m'] for r in intervals)
    return dict(total_s=total,costs=costs,travel_m=distance,fixed_scan_polyline_m=fixed_length,extra_over_scan_polyline_m=distance-fixed_length,
        discoveries=discoveries,clears=clears,failed_clears=failed,scan_order=scan,scan_intervals=intervals,ledger=ledger)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'outer_tangent_analysis.json')
    args=parser.parse_args()
    old=read(HERE/'outer_tangent_v12.json.gz');new=read(HERE/'outer_tangent_v14_p2.json.gz')
    assert old['sources']==new['sources']
    a=audit(old);b=audit(new)
    key=lambda r:(r['action'],r['p'],r['ch'],r['result'],r['bearing'] if r['action']=='measure' else None)
    first=next(i for i,(x,y) in enumerate(zip(old['records'],new['records']),1) if key(x)!=key(y))
    source_changes=[]
    for ch in sorted(a['discoveries']):
        ac=next(c for c in a['clears'] if c['channel']==ch);bc=next(c for c in b['clears'] if c['channel']==ch)
        source_changes.append(dict(channel=ch,old_discovery=a['discoveries'][ch],new_discovery=b['discoveries'][ch],
            discovery_delay_s=b['discoveries'][ch]['time_s']-a['discoveries'][ch]['time_s'],old_clear=ac,new_clear=bc,
            clear_delay_s=bc['time_s']-ac['time_s']))
    result=dict(scope='跨版本结构压力案例，V12与V14_P2在同一独立物理反馈实现中的历史账本；不属于M019同组比较，不估计官方分布。',
        passed=True,source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'outer_tangent_v12.json.gz',HERE/'outer_tangent_v14_p2.json.gz']},
        old={k:v for k,v in a.items() if k!='ledger'},new={k:v for k,v in b.items() if k!='ledger'},
        delta_total_s=b['total_s']-a['total_s'],relative_change_percent=100*(b['total_s']/a['total_s']-1),
        delta_travel_m=b['travel_m']-a['travel_m'],delta_costs={k:b['costs'][k]-a['costs'][k] for k in a['costs']},
        first_action_divergence=first,divergence_window={'old':a['ledger'][max(0,first-3):first+3],'new':b['ledger'][max(0,first-3):first+3]},
        source_changes=source_changes)
    save(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('old','new','divergence_window','source_changes')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
