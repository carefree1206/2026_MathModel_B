"""同场比较与预登记确认；不连接官方模拟器、不改变采用配置。"""
from pathlib import Path
import argparse,gzip,hashlib,json,math,platform,random,sys,time
from concurrent.futures import ProcessPoolExecutor
from 问题三四_正式算法与参数入口 import ROOT, MODEL, read, save, load, verify_files

def freeze_confirmation(path):
    """先固定全部输入，再启动算法。各属性使用独立随机流。"""
    path=Path(path)
    if path.exists():raise FileExistsError('不覆盖既有确认输入：'+str(path))
    cases=[]
    for problem in ('q3','q4'):
        for n in range(10,17):
            for rep in range(12):
                seed=202609120000+(0 if problem=='q3' else 10000)+n*100+rep
                streams={name:random.Random(seed+offset) for name,offset in
                         [('geometry',1000000),('channels',2000000),('type',3000000),('orientation',4000000),('radius',5000000)]}
                channels=streams['channels'].sample(range(1,21),n)
                directional=set(streams['type'].sample(range(n),streams['type'].randint(1,n-1))) if problem=='q4' else set()
                sources=[]
                for k,ch in enumerate(channels):
                    angle=2*math.pi*streams['geometry'].random();r=1800*math.sqrt(streams['geometry'].random())
                    sources.append(dict(id='source-'+str(k),channel=ch,x_m=r*math.cos(angle),y_m=r*math.sin(angle),
                        reception_radius_m=streams['radius'].uniform(1000,1500),
                        orientation_deg=streams['orientation'].uniform(0,360) if k in directional else None))
                cases.append(dict(schema_version=1,case_kind='full',case_id=f'v14-confirm-{problem}-n{n:02d}-{rep:02d}',
                    problem=problem,seed=seed,sources=sources,error_model=dict(type='hash',seed=seed+6000000),
                    provenance='New synthetic confirmation; frozen before execution; assumptions are not official distribution'))
    save(path,dict(panel='fresh_confirmation',seed_rule='202609120000 + problem_offset + n*100 + repetition; independent attribute streams',
        constraints='10..16 sources, 12 per stratum and problem; Q4 always includes both source types',
        policy_locked_before_execution=True,parameter_tuning_permitted=False,cases=cases))
    return path

def worker(job):
    case,variant,out,panel=job
    load(case['problem'])
    from 问题三四_场景求解与核验 import safe_run_one
    selected=read(MODEL/'数据/参数/问题三四_信息调度选型.json')['selected'][case['problem']]
    spec=dict(name=variant)
    if variant=='m021':spec.update(module=selected['module'],settings=selected['settings'])
    row=safe_run_one((case,spec,out,False));row['panel']=panel
    return row

def percentile(values,p):
    values=sorted(values);index=(len(values)-1)*p;lo=int(index);hi=math.ceil(index)
    return values[lo]+(values[hi]-values[lo])*(index-lo)

def summarize(rows):
    summary=[]
    for problem in ('q3','q4'):
        baseline={r['case_id']:r for r in rows if r['problem']==problem and r['variant']=='m019'}
        for variant in ('m019','m020','m021'):
            part=[r for r in rows if r['problem']==problem and r['variant']==variant]
            if not part:continue
            valid=all(r['passed'] and r['per_source_s'] is not None for r in part)
            vals=[r['per_source_s'] for r in part] if valid else []
            paired=[r for r in part if r['passed'] and baseline.get(r['case_id'],{}).get('passed')]
            changes=[100*(r['per_source_s']/baseline[r['case_id']]['per_source_s']-1) for r in paired]
            summary.append(dict(problem=problem,variant=variant,cases=len(part),passed=valid,
                cleared=sum(r['cleared_count'] for r in part),sources=sum(r['source_count'] for r in part),
                mean=sum(vals)/len(vals) if vals else None,median=percentile(vals,.5) if vals else None,
                p90=percentile(vals,.9) if vals else None,tail10=sum(sorted(vals)[-math.ceil(.1*len(vals)):])/math.ceil(.1*len(vals)) if vals else None,
                max=max(vals) if vals else None,slower_vs_m019=sum(c>1e-8 for c in changes),
                worst_relative_change_percent=max(changes) if changes else None,
                mean_wall_s=sum(r['wall_s'] for r in part)/len(part),paired_comparable=len(paired)))
    return summary

def run(panel,out,workers=6,limit=None,input_path=None):
    if platform.python_version()!='3.9.13':raise RuntimeError('确认与逐动作对照使用 Python 3.9.13')
    if workers<1 or (limit is not None and limit<1):raise ValueError('workers 和 limit 必须为正整数')
    verify_files();out=Path(out);out.mkdir(parents=True,exist_ok=False)
    if panel=='fresh_confirmation':
        path=Path(input_path) if input_path else ROOT/'数据/fresh_confirmation_cases.json'
        if not path.exists():freeze_confirmation(path)
        cases=read(path)['cases']
    else:
        path=ROOT/'数据/offline_cases.json.gz'
        with gzip.open(path,'rt',encoding='utf-8') as f:jobs=json.load(f)['jobs']
        cases=[j['case'] for j in jobs if j['variant']=='m019']
    if limit is not None:cases=[c for q in ('q3','q4') for c in [x for x in cases if x['problem']==q][:limit]]
    if not cases or not all(any(c['problem']==q for c in cases) for q in ('q3','q4')):
        raise ValueError('面板必须包含两问的非空输入，空集合不能作为通过结果')
    save(out/'protocol.json',dict(panel=panel,input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        input_filename=path.name,case_ids=[c['case_id'] for c in cases],policies=read(ROOT/'数据/参数/问题三四_正式算法选型.json'),
        code=verify_files(),quantile_method='linear interpolation at (n-1)*p; tail10 uses ceil(0.1*n) highest cases',
        official=False,network_requests=0,argv=sys.argv,python=sys.version,tuning=False))
    jobs=[(case,v,str(out/'runs'),panel) for case in cases for v in ('m019','m020','m021')]
    rows=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool,(out/'rows.partial.jsonl').open('x',encoding='utf-8') as f:
        for row in pool.map(worker,jobs):
            rows.append(row);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
            if len(rows)%28==0 or not row['passed']:print(f'{panel}: {len(rows)}/{len(jobs)} passed={row["passed"]}',flush=True)
    unchanged=verify_files();save(out/'rows.json',rows);summary=summarize(rows);save(out/'summary.json',summary)
    if panel=='existing_panel':
        expected={(j['problem'],j['case']['case_id'],'m021' if j['variant']=='selected' else j['variant']):j for j in json.load(gzip.open(path,'rt',encoding='utf-8'))['jobs']}
        errors=[]
        for r in rows:
            e=expected[(r['problem'],r['case_id'],r['variant'])]
            if r['virtual_s'] is None or abs(r['virtual_s']-e['expected_time_s'])>1e-7 or r['actions']!=e['expected_actions']:
                errors.append(dict(case_id=r['case_id'],variant=r['variant'],actual_time_s=r['virtual_s'],expected_time_s=e['expected_time_s']))
        save(out/'export_agreement.json',dict(passed=not errors,rows=len(rows),errors=errors))
    else:errors=[]
    result=dict(passed=not errors and all(r['passed'] for r in rows),runs=len(rows),wall_s=time.monotonic()-start,source_check=unchanged,network_requests=0)
    save(out/'integrity.json',result);print(json.dumps(summary,ensure_ascii=False,indent=2));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--panel',choices=['existing_panel','fresh_confirmation'],default='existing_panel')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=6);p.add_argument('--limit',type=int)
    p.add_argument('--input',type=Path);a=p.parse_args();return 0 if run(a.panel,a.output,a.workers,a.limit,a.input)['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
