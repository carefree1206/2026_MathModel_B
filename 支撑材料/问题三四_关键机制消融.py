"""每问预先固定28个配对场景，分别关闭两个单项机制。"""
from pathlib import Path
import argparse,gzip,zipfile
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import platform
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE
SUPPORT = HERE
sys.path.insert(0, str(SUPPORT))
from 问题三四_正式算法与参数入口 import load, read, save, verify_files

LABELS = {'q3':['complete','no_posterior_optical','no_cost_pair'],
          'q4':['complete','no_transit','no_known_gate']}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(job):
    case, label, output = job
    rt = load(case['problem'])
    cfg = dict(rt['settings'], _ablation_label=label)
    if label == 'no_posterior_optical': cfg['posterior_optical'] = False
    elif label == 'no_transit': cfg['intercept_cap'] = 0
    elif label == 'no_known_gate': cfg['scan_gain_m'] = None
    sys.path.insert(0, str(HERE))
    from 问题三四_场景求解与核验 import safe_run_one
    variant = dict(name=label, module='问题三四_消融策略', settings=cfg)
    result = safe_run_one((case,variant,output,False))
    result['input_sha256'] = hashlib.sha256(json.dumps(case,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result['selected_algorithm'] = rt['version']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if platform.python_version() != '3.9.13': raise RuntimeError('Frozen numerical evaluation requires Python 3.9.13')
    out = args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    source = SUPPORT / '数据/fresh_confirmation_cases.json'
    full = read(source)
    cases = [c for c in full['cases'] if int(c['case_id'].rsplit('-',1)[-1]) < 4]
    assert len(cases) == 56
    for q in LABELS:
        assert all(sum(c['problem']==q and len(c['sources'])==n for c in cases)==4 for n in range(10,17))
    hashes = {p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),HERE/'问题三四_消融策略.py',SUPPORT/'问题三四_正式算法与参数入口.py',source]}
    source_check = verify_files()
    with zipfile.ZipFile(out/'source_snapshot.zip','x',zipfile.ZIP_DEFLATED) as z:
        for name in hashes:z.write(ROOT/name,name)
    protocol = dict(question='Which selected mechanisms change complete execution time on a predeclared subset?',
        scope='Synthetic offline mechanism comparison on reps 00..03 of the already frozen fresh confirmation panel; not a new independent performance panel.',
        official=False,network_requests=0,tuning=False,python=sys.version,command=sys.argv,
        case_ids=[c['case_id'] for c in cases],case_count=56,runs=168,
        labels=LABELS,input_sha256=sha(source),source_sha256=hashes,source_check=source_check,
        ablations={
            'no_posterior_optical':'Q3: only posterior_optical=False; Cost5 probe ranking and all posterior history retained.',
            'no_cost_pair':'Q3: override only choose_pair to original(track, **kwargs), the pre-ranking geometric pair; the original nearest_pair wrapper and posterior optical choice remain. Do not delegate to PosteriorMixin, which still costs candidates.',
            'no_transit':'Q4: only intercept_cap=0; stationary information, known scan gate, route suffix and all geometry retained.',
            'no_known_gate':'Q4: only scan_gain_m=None; scan_count_stop=True and every other selected setting retained.'},
        metric='Per-case complete virtual time / actual successful clears, then arithmetic case mean. All bad cases retained; mean invalid if any run fails.',
        checks='Every run recomputes actual timing and physics, full range audit, Q3 negative geometry, complete clearing and termination. Complete-policy action/time equality against fresh confirmation is also checked.',
        repeated_runs='Complete-policy runs are deliberate reproduction of existing frozen cases; they are not additional independent cases.')
    save(out/'protocol.json',protocol)
    save(out/'cases.json',cases)
    jobs=[(c,label,str(out/'runs')) for c in cases for label in LABELS[c['problem']]]
    rows=[]
    start=time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool,(out/'rows.partial.jsonl').open('x',encoding='utf8') as f:
        for row in pool.map(worker,jobs):
            rows.append(row)
            f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
            if len(rows)%14==0 or not row['passed']: print(f'ablation {len(rows)}/{len(jobs)}, passed={row["passed"]}',flush=True)
    save(out/'rows.json',rows)
    existing=json.load(gzip.open(SUPPORT/'数据/benchmark.json.gz','rt',encoding='utf-8'))['rows']
    existing=[r for r in existing if r['panel']=='fresh_confirmation']
    expected={(r['problem'],r['case_id'],r['variant']):r for r in existing}
    discrepancies=[]
    for r in rows:
        if r['variant']=='complete':
            e=expected[r['problem'],r['case_id'],'m020' if r['problem']=='q3' else 'm021']
            if not(r['passed'] and e['passed'] and r['actions']==e['actions'] and abs(r['virtual_s']-e['virtual_s'])<1e-7 and r['costs']==e['costs']):
                discrepancies.append(dict(case_id=r['case_id'],actual=r,expected=e))
    unchanged=all(sha(ROOT/p)==h for p,h in hashes.items())
    verify_files()
    summary=[]
    for q,labels in LABELS.items():
        base={r['case_id']:r for r in rows if r['problem']==q and r['variant']=='complete'}
        for label in labels:
            part=[r for r in rows if r['problem']==q and r['variant']==label]
            valid=unchanged and len(part)==28 and all(r['passed'] and r['per_source_s'] is not None for r in part)
            mean=sum(r['per_source_s'] for r in part)/len(part) if valid else None
            delta=mean-sum(r['per_source_s'] for r in base.values())/28 if valid and all(r['passed'] for r in base.values()) else None
            summary.append(dict(problem=q,label=label,n=len(part),mean=mean,delta=delta,
                source_count=sum(r['source_count'] for r in part),cleared_count=sum(r['cleared_count'] for r in part),
                passed=valid,rows=part,
                slower_than_complete=sum(r['per_source_s']>base[r['case_id']]['per_source_s']+1e-8 for r in part) if valid else None,
                worst_relative_change_percent=max(100*(r['per_source_s']/base[r['case_id']]['per_source_s']-1) for r in part) if valid else None))
    save(out/'summary.json',summary)
    integrity=dict(passed=unchanged and not discrepancies and all(r['passed'] for r in rows),
                   runs=len(rows),source_unchanged=unchanged,complete_policy_agreement_rows=56,
                   discrepancies=discrepancies,wall_s=time.monotonic()-start,network_requests=0)
    save(out/'integrity.json',integrity)
    print(json.dumps([{k:v for k,v in s.items() if k!='rows'} for s in summary],ensure_ascii=False,indent=2))
    return 0 if integrity['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
