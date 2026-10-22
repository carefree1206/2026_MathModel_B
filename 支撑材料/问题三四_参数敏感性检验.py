"""固定小面板上的局部敏感性：只使用离线模拟器，不改变正式配置。"""
from pathlib import Path
import argparse, gzip, hashlib, json, platform, sys, time
from concurrent.futures import ProcessPoolExecutor

HERE=Path(__file__).resolve().parent/'数据/问题三四稳健性'

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def worker(job):
    case,value,support,out,parameter=job
    sys.path.insert(0,support)
    from 问题三四_正式算法与参数入口 import load
    rt=load(case['problem'])
    from 问题三四_场景求解与核验 import safe_run_one
    # 只复制并覆盖此次要检查的一个值，不写回正式配置。
    settings=dict(rt['settings']);settings[parameter['field']]=value
    variant=dict(name=f'{parameter["field"]}_{value}',module=rt['module'],settings=settings)
    row=safe_run_one((case,variant,out,False))
    row.update(panel=case['sensitivity_panel'],parameter=parameter['field'],value=value,
               default_value=parameter['default'],selected_algorithm=rt['version'])
    return row

def summarize(rows):
    summary=[]
    for problem in ('q3','q4'):
        for panel in ('confirmation_subset','mechanism_stress'):
            part=[r for r in rows if r['problem']==problem and r['panel']==panel]
            defaults={r['case_id']:r for r in part if r['value']==r['default_value']}
            for value in sorted({r['value'] for r in part}):
                group=[r for r in part if r['value']==value]
                good=all(r['passed'] for r in group) and all(r['passed'] for r in defaults.values())
                changes=[dict(case_id=r['case_id'],delta_total_s=r['virtual_s']-defaults[r['case_id']]['virtual_s'],
                    delta_per_source_s=r['per_source_s']-defaults[r['case_id']]['per_source_s'],
                    change_percent=100*(r['virtual_s']/defaults[r['case_id']]['virtual_s']-1)) for r in group] if good else []
                summary.append(dict(problem=problem,panel=panel,value=value,default=group[0]['default_value'],
                    cases=len(group),passed=good,cleared=sum(r['cleared_count'] for r in group),
                    sources=sum(r['source_count'] for r in group),
                    mean_total_s=sum(r['virtual_s'] for r in group)/len(group) if good else None,
                    mean_per_source_s=sum(r['per_source_s'] for r in group)/len(group) if good else None,
                    mean_delta_per_source_s=sum(c['delta_per_source_s'] for c in changes)/len(changes) if changes else None,
                    slower_cases=sum(c['change_percent']>1e-8 for c in changes),
                    worst_change=max(changes,key=lambda c:c['change_percent']) if changes else None,
                    mean_wall_s=sum(r['wall_s'] for r in group)/len(group),paired_changes=changes))
    return summary

def compare_expected(rows):
    """逐场核对归档结果；真实运行耗时与时间戳不属于算法输出。"""
    expected={(r['case_id'],r['variant']):r for r in read(HERE/'sensitivity_results.json')['rows']}
    differences=[]
    for row in rows:
        old=expected.get((row['case_id'],row['variant']))
        if old is None or not (row['passed']==old['passed'] and row['source_count']==old['source_count']
                and row['cleared_count']==old['cleared_count'] and row['actions']==old['actions']
                and abs(row['virtual_s']-old['virtual_s'])<1e-7 and row['costs']==old['costs']):
            differences.append(dict(case_id=row['case_id'],variant=row['variant']))
    return dict(passed=len(rows)==len(expected) and not differences,checked=len(rows),expected=len(expected),differences=differences)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--support',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'results/sensitivity')
    parser.add_argument('--workers',type=int,default=1)
    args=parser.parse_args()
    if platform.python_version()!='3.9.13':raise RuntimeError('请使用已验证的Python 3.9.13环境')
    if not 1<=args.workers<=3:raise ValueError('进程数需为1至3')
    support=args.support.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(support))
    from 问题三四_正式算法与参数入口 import verify_files
    protocol=read(HERE/'protocol.json');cases=read(HERE/'cases.json')
    if sha(HERE/'cases.json')!=protocol['cases_sha256']:raise ValueError('固定输入发生改变')
    hashes={str(p.relative_to(support)):sha(p) for p in [support/'问题三四_正式算法与参数入口.py',support/'数据/参数/问题三四_原交付程序清单.json',support/'数据/参数/问题三_算法参数.json',support/'数据/参数/问题四_算法参数.json']}
    save(out/'execution.json',dict(protocol=protocol,code_check=verify_files(),support_hashes=hashes,
        runner_sha256=sha(__file__),python=sys.version,argv=sys.argv))
    jobs=[(c,v,str(support),str(out/'runs'),protocol['parameters'][c['problem']]) for c in cases for v in protocol['parameters'][c['problem']]['values']]
    rows=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool,(out/'rows.partial.jsonl').open('x',encoding='utf-8') as f:
        for row in pool.map(worker,jobs):
            rows.append(row);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
            if len(rows)%3==0 or not row['passed']:print(f'{len(rows)}/{len(jobs)} passed={row["passed"]}',flush=True)
    save(out/'rows.json',rows);save(out/'summary.json',summarize(rows))
    # 默认值运行必须与确认组既有账本完全一致，以防实际调用版本错误。
    expected={(r['case_id'],r['variant']):r for r in json.load(gzip.open(support/'数据/benchmark.json.gz','rt',encoding='utf-8'))['rows'] if r['panel']=='fresh_confirmation'}
    differences=[]
    for r in rows:
        if r['panel']=='confirmation_subset' and r['value']==r['default_value']:
            e=expected[r['case_id'],'m020' if r['problem']=='q3' else 'm021']
            if not (r['passed'] and abs(r['virtual_s']-e['virtual_s'])<1e-7 and r['actions']==e['actions'] and r['costs']==e['costs']):differences.append(r['case_id'])
    unchanged=all(sha(support/name)==digest for name,digest in hashes.items())
    check=verify_files()
    agreement=compare_expected(rows)
    save(out/'expected_agreement.json',agreement)
    integrity=dict(passed=all(r['passed'] for r in rows) and unchanged and not differences and agreement['passed'],
        runs=len(rows),all_clear=all(r['source_count']==r['cleared_count'] for r in rows),
        default_confirmation_agreement=not differences,discrepancies=differences,unchanged=unchanged,
        code_check=check,expected_agreement=agreement,wall_s=time.monotonic()-start,network_requests=0)
    save(out/'integrity.json',integrity);print(json.dumps(integrity,ensure_ascii=False,indent=2))
    return 0 if integrity['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
