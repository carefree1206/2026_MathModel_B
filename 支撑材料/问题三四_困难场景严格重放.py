"""严格重放保留的困难反例；完整历史压力面板不称为新确认。"""
import gzip,json
from 问题三四_正式算法与参数入口 import ROOT, read, save, load
def run(out):
    with gzip.open(ROOT/'数据/stress_cases.json.gz','rt',encoding='utf-8') as f:jobs=json.load(f)['jobs']
    lookup={(j['case']['case_id'],j['variant']):j for j in jobs}
    chosen=set();criteria=[]
    for problem,base,kind in [('q3','m020','cluster'),('q4','m019',None),('q4','m020',None)]:
        selected=[j for j in jobs if j['case']['problem']==problem and j['variant']=='m021' and (kind is None or '-'+kind+'-' in j['case']['case_id'])]
        worst=max(selected,key=lambda j:j['expected']['per_source_s']/lookup[(j['case']['case_id'],base)]['expected']['per_source_s'])
        chosen.add(worst['case']['case_id']);criteria.append(dict(problem=problem,reference=base,kind=kind,case_id=worst['case']['case_id']))
    results=[]
    for case_id in sorted(chosen):
        for variant in ('m019','m020','m021'):
            job=lookup[(case_id,variant)];case=job['case'];bundle=load(case['problem'],comparison=variant)
            from 问题三四_动作轨迹独立核验 import ReplayTransport, audit_records
            tape=ReplayTransport(job['records']);session=bundle['Session'](tape,'offline','stress-replay',bundle['config'])
            session.enter();solution=bundle['solve'](bundle['ObservedSession'](session),case['problem'],bundle['settings']);session.exit()
            check=tape.assert_complete();physical=audit_records(session.records,case,solution,problem=case['problem'])
            if not check['passed'] or not physical['passed']:raise RuntimeError('困难场景回放未通过：'+case_id)
            if abs(session.virtual_time-job['expected']['virtual_s'])>1e-8:raise RuntimeError('困难场景费用不一致')
            results.append(dict(case_id=case_id,variant=variant,passed=True,strict_action_replay=True,virtual_time_s=session.virtual_time))
    result=dict(passed=True,criteria=criteria,results=results,network_requests=0)
    save(out/'stress_replay.json',result);return result
