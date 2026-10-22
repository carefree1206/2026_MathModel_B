"""离线同场配对实验，保存原始证据、源码快照及独立核验。"""
import argparse
import gzip
import importlib
import json
import platform
import sys
import time
import traceback
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from 问题三四_模型加载 import ROOT, FROZEN, read, write, digest, baseline_settings, baseline_config, solve_baseline, solve_m020, m020_settings, Session, LocalSimulator, ObservedSession, recompute, audit_records, audit_trace, ReplayTransport
from 问题三四_边界场景构造 import make_case
from 问题三四_全范围几何核验 import audit as audit_full_range


def solver_for(variant):
    return solve_baseline if variant.get('module',variant['name'])=='m019' else solve_m020 if variant.get('module',variant['name'])=='m020' else importlib.import_module(variant['module']).solve


def run_one(job):
    case,variant,output,replay_requested=job
    problem=case['problem'];settings=dict(baseline_settings(problem) if variant.get('module',variant['name'])=='m019' else m020_settings(problem),**variant.get('settings',{}))
    target=Path(output)/case['case_id']/variant['name'] if output else None
    if target:target.mkdir(parents=True,exist_ok=False)
    solver=solver_for(variant);cfg=baseline_config(problem)
    sim=LocalSimulator(case);session=Session(sim,'offline','m021',cfg)
    error=None;solution=None;begin=time.monotonic()
    try:
        session.enter();solution=solver(ObservedSession(session),problem,settings);session.exit()
    except Exception:
        error=traceback.format_exc()
        if session.entered and not session.closed:
            try:session.exit()
            except Exception:pass
    elapsed=time.monotonic()-begin
    # 先保存原始证据，再运行可选核验；核验异常不能丢失本局记录。
    if target:
        write(target/'case.json',case);write(target/'solution.json',solution)
        with gzip.open(target/'actions.jsonl.gz','wt',encoding='utf-8') as f:
            for row in session.records:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def guarded_audit(function,*positional,**kwargs):
        try:return function(*positional,**kwargs)
        except Exception:return dict(passed=False,error=traceback.format_exc(),status='auditor_exception')
    timing=guarded_audit(recompute,session.records,require_closed=True,require_http=True)
    independent=guarded_audit(audit_records,session.records,case,solution,problem=problem)
    negative=guarded_audit(audit_trace,session.records,solution) if problem=='q3' and solution else None
    shadow=None
    if solution and any(e['method']=='q4_negative_shadow' for e in solution['events']):
        from 问题四_阴影区域包含核验 import audit as audit_shadow
        shadow=guarded_audit(audit_shadow,session.records,solution)
    full_range=guarded_audit(audit_full_range,session.records,solution) if solution else None
    truth=sim.evaluate()
    passed=not error and truth['clearance_ratio']==1 and timing['passed'] and independent['passed'] and (not negative or negative['passed']) and (not shadow or shadow['passed']) and (not full_range or full_range['passed']) and solution.get('termination')=='coverage_complete'
    result=dict(case_id=case['case_id'],problem=problem,variant=variant['name'],module=variant.get('module',variant['name']),settings=settings,
        passed=bool(passed),error=error,source_count=len(case['sources']),cleared_count=truth['cleared_sources'],
        per_source_s=session.virtual_time/truth['cleared_sources'] if truth['cleared_sources'] else None,
        virtual_s=session.virtual_time,costs=session.costs,truth=truth,wall_s=elapsed,actions=len(session.records),
        timing={k:v for k,v in timing.items() if k!='actions'},independent=independent,negative_geometry=negative,shadow_geometry=shadow,full_range_geometry=full_range)
    if target:
        write(target/'result.json',result)
        if replay_requested and passed:
            try:
                tape=ReplayTransport(target/'actions.jsonl.gz');again=Session(tape,'offline','m021-replay',cfg)
                again.enter();solution2=solver(ObservedSession(again),problem,settings);again.exit()
                replay=tape.assert_complete()
                result['replay']=dict(passed=replay['passed'] and json.loads(json.dumps(solution))==json.loads(json.dumps(solution2)) and again.virtual_time==session.virtual_time and again.costs==session.costs,
                    solution_exact=json.loads(json.dumps(solution))==json.loads(json.dumps(solution2)),time_exact=again.virtual_time==session.virtual_time,costs_exact=again.costs==session.costs,**{k:v for k,v in replay.items() if k!='passed'})
            except Exception:
                result['replay']=dict(passed=False,error=traceback.format_exc(),status='replay_exception')
            result['passed']=result['passed'] and result['replay']['passed']
        write(target/'result.json',result)
    return {k:result.get(k) for k in ('case_id','problem','variant','passed','source_count','cleared_count','per_source_s','virtual_s','costs','wall_s','actions','error')}


def safe_run_one(job):
    try:return run_one(job)
    except Exception:
        case,variant,output,_=job
        row=dict(case_id=case['case_id'],problem=case['problem'],variant=variant['name'],passed=False,
                 source_count=len(case['sources']),cleared_count=0,per_source_s=None,virtual_s=None,
                 costs=None,wall_s=0.,actions=None,error=traceback.format_exc(),status='worker_exception',
                 count_scope='zero verified clearances; partial physical execution may exist')
        if output:
            target=Path(output)/case['case_id']/variant['name']
            target.mkdir(parents=True,exist_ok=True)
            write(target/'worker_failure.json',row)
        return row


def comparable(row,base):
    reference=base.get(row['case_id'])
    return bool(reference and row.get('passed') and reference.get('passed') and
                isinstance(row.get('per_source_s'),(float,int)) and
                isinstance(reference.get('per_source_s'),(float,int)) and reference['per_source_s']>0)


def inventory(variants):
    from 问题三四_正式算法与参数入口 import verify_files
    verify_files()
    hashes=read(ROOT/'数据/程序校验.json')['sha256']
    for variant in variants:
        solver_for(variant)
    return dict(hashes)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True,help='JSON mapping q3/q4 to variant arrays')
    p.add_argument('--problem',choices=['q3','q4','both'],default='both')
    p.add_argument('--stage',choices=['development','validation','test','stress'],default='development')
    p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=14)
    p.add_argument('--kinds',default='uniform');p.add_argument('--output',required=True)
    p.add_argument('--workers',type=int,default=6);p.add_argument('--replay',action='store_true')
    args=p.parse_args()
    if platform.python_version()!='3.9.13':p.error('Frozen evaluation uses Python 3.9.13')
    config=read(ROOT/args.config);qs=['q3','q4'] if args.problem=='both' else [args.problem]
    variants=[v for q in qs for v in config[q]]
    hashes=inventory(variants)
    config_path=(ROOT/args.config).resolve()
    if ROOT not in config_path.parents:p.error('Config must remain in isolated M021 workspace')
    hashes[config_path.relative_to(ROOT).as_posix()]=digest(config_path)
    out=(ROOT/args.output).resolve()
    if ROOT not in out.parents:p.error('Output must remain in isolated M021 workspace')
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(stage=args.stage,source='synthetic_offline_not_official',metric='arithmetic mean of per-case complete virtual time / successful clears; all cases retained',
        gates=dict(q3_s=215,q4_s=440,all_clear=True),config=config,command=sys.argv,python=sys.version,
        start=args.start,count_per_kind=args.count,kinds=args.kinds.split(','),code_sha256=hashes,
        replay_requested=args.replay)
    write(out/'protocol.json',protocol)
    with zipfile.ZipFile(out/'source_snapshot.zip','x',zipfile.ZIP_DEFLATED) as z:
        for relative in hashes:z.write(ROOT/relative,relative)
    jobs=[]
    for q in qs:
        for kind in args.kinds.split(','):
            for i in range(args.start,args.start+args.count):
                case=make_case(q,i,args.stage,kind)
                for variant in config[q]:jobs.append((case,variant,str(out),args.replay))
    rows=[];begin=time.monotonic()
    with (out/'rows.partial.jsonl').open('x',encoding='utf-8') as partial:
        try:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                for row in pool.map(safe_run_one,jobs):
                    rows.append(row)
                    partial.write(json.dumps(row,ensure_ascii=False)+'\n');partial.flush()
                    if not row['passed']:print('FAIL',json.dumps(row,ensure_ascii=False),flush=True)
                    elif len(rows)%28==0:print('progress',len(rows),'/',len(jobs),flush=True)
        except Exception:
            error=traceback.format_exc()
            write(out/'process_pool_failure.json',dict(passed=False,error=error,completed_rows=len(rows),planned_rows=len(jobs)))
            for case,variant,output,replay in jobs[len(rows):]:
                row=dict(case_id=case['case_id'],problem=case['problem'],variant=variant['name'],passed=False,
                    source_count=len(case['sources']),cleared_count=0,per_source_s=None,virtual_s=None,
                    costs=None,wall_s=0.,actions=None,error=error,status='unverified_after_pool_failure',
                    count_scope='zero verified clearances; archived partial execution may exist')
                write(out/case['case_id']/variant['name']/'pool_failure.json',row)
                rows.append(row);partial.write(json.dumps(row,ensure_ascii=False)+'\n');partial.flush()
    unchanged=all(digest(ROOT/name)==value for name,value in hashes.items())
    summary=[]
    for q in qs:
        for kind in args.kinds.split(','):
            group=[r for r in rows if r['problem']==q and '-'+kind+'-' in r['case_id']]
            base={r['case_id']:r for r in group if r['variant']=='m019'}
            for variant in config[q]:
                selected=[r for r in group if r['variant']==variant['name']]
                vals=[r['per_source_s'] for r in selected]
                valid=all(r['passed'] for r in selected) and unchanged and all(v is not None for v in vals)
                average=sum(vals)/len(vals) if all(v is not None for v in vals) else None
                paired=[r for r in selected if comparable(r,base)]
                slower=[r for r in paired if r['per_source_s']>base[r['case_id']]['per_source_s']+1e-8]
                summary.append(dict(problem=q,kind=kind,variant=variant['name'],cases=len(selected),passed=valid,
                    failures=sum(not r['passed'] for r in selected),sources=sum(r['source_count'] for r in selected),cleared=sum(r['cleared_count'] for r in selected),
                    mean=average,max=max(vals) if all(v is not None for v in vals) else None,
                    mean_wall_s=sum(r['wall_s'] for r in selected)/len(selected),slower_than_m019=len(slower),
                    paired_comparable_cases=len(paired),paired_unavailable_cases=len(selected)-len(paired),
                    worst_relative_change_percent=max((100*(r['per_source_s']/base[r['case_id']]['per_source_s']-1) for r in paired),default=None),
                    target_met=bool(valid and average is not None and average<=(215 if q=='q3' else 440))))
    write(out/'rows.json',rows);write(out/'summary.json',summary)
    write(out/'integrity.json',dict(source_unchanged=unchanged,wall_s=time.monotonic()-begin,source_snapshot_sha256=digest(out/'source_snapshot.zip'),network_requests=0))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if unchanged and all(r['passed'] for r in rows) else 1


if __name__=='__main__':raise SystemExit(main())
