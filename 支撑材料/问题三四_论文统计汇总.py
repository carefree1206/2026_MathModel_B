"""论文统计统一入口：从全部逐场记录重算，不在图文中手填成绩。"""
from pathlib import Path
import datetime,gzip,hashlib,json,math

def read(path):
    path=Path(path)
    raw=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    return json.loads(raw.decode('utf-8-sig'))

def quantile(v,p):
    v=sorted(v);x=(len(v)-1)*p;a=int(x);b=math.ceil(x)
    return v[a]+(v[b]-v[a])*(x-a)

def summarize(rows):
    assert rows and all(r['passed'] and r['cleared_count']==r['source_count'] for r in rows)
    baseline={r['case_id']:r for r in rows if r['variant']=='m019'}
    result={}
    for v in ['m019','m020','m021']:
        part=[r for r in rows if r['variant']==v]
        if not part:continue
        assert {r['case_id'] for r in part}==set(baseline)
        vals=[r['per_source_s'] for r in part]
        changes=[100*(r['per_source_s']/baseline[r['case_id']]['per_source_s']-1) for r in part]
        n=len(part);nt=math.ceil(.1*n)
        result[v]=dict(n=n,mean=sum(vals)/n,median=quantile(vals,.5),p90=quantile(vals,.9),
            tail10=sum(sorted(vals)[-nt:])/nt,max=max(vals),cleared=sum(r['cleared_count'] for r in part),
            sources=sum(r['source_count'] for r in part),slower=sum(c>1e-8 for c in changes),
            worst_relative_percent=max(changes),mean_wall_s=sum(r['wall_s'] for r in part)/n)
    return result

def assemble(data_dir,output=None):
    base=Path(data_dir)
    results=read(base/'benchmark.json.gz')['rows']
    stress=read(base/'stress_rows.json.gz')['rows']
    stress=[dict(r,kind='outward' if r['panel']=='stress_outward_v2' else r['case_id'].split('-')[3]) for r in stress]
    official=read(base/'practice_results.json')
    evidence=dict(statistics={},stress={},practice={},benchmark_rows=results,stress_rows=stress,ablation={},
        scope='All adopted policies fixed before new confirmation. No official distribution assumed.',
        sources={p:hashlib.sha256((base/p).read_bytes()).hexdigest() for p in ['benchmark.json.gz','stress_rows.json.gz','practice_results.json']})
    for old,new in [('existing_panel','development'),('fresh_confirmation','confirmation')]:
        evidence['statistics'][new]={q:summarize([r for r in results if r['panel']==old and r['problem']==q]) for q in ['q3','q4']}
    for q in ['q3','q4']:
        groups={r['kind'] for r in stress if r['problem']==q}
        evidence['stress'][q]={kind:summarize([r for r in stress if r['problem']==q and r['kind']==kind]) for kind in sorted(groups)}
        rows=[]
        for r in official['rows']:
            if r['problem']!=q:continue
            t=r['timing']
            wall=(datetime.datetime.fromisoformat(t['exited_at_utc'])-datetime.datetime.fromisoformat(t['entered_at_utc'])).total_seconds()
            rows.append(dict(case_code=r['case_code'],source_count=r['source_count'],cleared_count=r['cleared_count'],
                per_source_s=r['per_source_s'],virtual_time_s=r['virtual_time_s'],wall_s=wall,costs=r['cost_breakdown'],
                user_confirmed_full_clear=bool(official.get('user_confirmation',{}).get('all_twelve_runs_full_clear',False)),
                original_adapter_case_code=r['original_adapter_case_code'],original_log=r['original_log'],
                original_log_sha256=r['original_log_sha256'],version=r['version']))
        assert len(rows)==6
        # 用户确认单独传递；接口未公开的真实总数仍保持null。
        confirmed=official.get('user_confirmation',{})
        if confirmed.get('supplied_jlog_cases')==12 and confirmed.get('all_displayed_clearance_ratios')==1.0:
            for r in rows:r['user_confirmed_full_clear']=True
        evidence['practice'][q]=dict(rows=rows,cleared_count=sum(r['cleared_count'] for r in rows),
            mean=sum(r['per_source_s'] for r in rows)/6,pooled=sum(r['virtual_time_s'] for r in rows)/sum(r['cleared_count'] for r in rows),
            user_confirmation=confirmed,program_time_basis='accepted /enter to accepted /exit real_timestamp_ms')
    ab=base/'ablation_for_paper.json'
    if ab.exists():
        a=read(ab);evidence['ablation']=a['summary'];evidence['ablation_rows']=a['rows']
        evidence['sources'][ab.name]=hashlib.sha256(ab.read_bytes()).hexdigest()
    output=Path(output) if output else base/'paper_evidence.json'
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return evidence

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=Path(__file__).resolve().parent/'数据');p.add_argument('--output',type=Path)
    a=p.parse_args();assemble(a.data,a.output)
