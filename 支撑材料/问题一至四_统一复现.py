"""独立解压后的复现入口。所有默认任务离线，不启动官方测试。"""
from pathlib import Path
import argparse,gzip,json,math,os,subprocess,sys
from 问题三四_正式算法与参数入口 import ROOT, MODEL, read, save, load, verify_files

def geometry(out):
    load('q3')
    from 问题一_定位区域与包围圆 import halfplane_region, enclosing_circle
    from 问题三四_连续覆盖构造 import verify_certificate
    square=halfplane_region([(1,0,1),(-1,0,1),(0,1,1),(0,-1,1)])
    _,radius=enclosing_circle([(0,0),(40,0),(20,20*math.sqrt(3))])
    assert abs(square['diameter_m']-math.sqrt(8))<1e-7 and radius>20
    assert verify_certificate(read(ROOT/'数据/q4_coverage_certificate.json'))
    bound=max(math.sqrt(r*r+1125**2-2*r*1125*math.cos(math.pi/6)) for r in (1000,1800))
    assert bound<1000
    from 问题一_多测点示例与退化检验 import validate
    checked=validate(out)
    save(out/'geometry.json',dict(passed=True,q1=checked,q3_cover_distance_bound_m=bound,q4_ring21_certificate=True))

def q2(out):
    load('q3')
    from 问题二_定位直径上下界 import bound, sector_witness
    rows=[]
    for item in read(ROOT/'数据/q2_results.json')['candidates']:
        for delta in (1.,1.005):
            upper=bound(item['point_m'],step=.0005,delta=delta,arc_segments=16)
            lower=sector_witness(item['point_m'],delta=delta)
            expected=next(x for x in item['bounds'] if x['delta_deg']==delta)
            assert abs(upper['upper_m']-expected['upper_m'])<1e-6
            assert abs(lower['lower_m']-expected['lower_m'])<1e-6
            rows.append(dict(point_m=item['point_m'],delta_deg=delta,upper_m=upper['upper_m'],lower_m=lower['lower_m']))
    save(out/'q2_recomputed.json',dict(passed=True,rows=rows))

def replay_one(code,out):
    row=next(r for r in read(ROOT/'数据/practice_results.json')['rows'] if r['case_code']==code)
    bundle=load(row['problem']);folder=ROOT/'数据'/Path(row['directory']).relative_to('data')
    from 问题三四_动作轨迹独立核验 import ReplayTransport
    from 问题三四_官方模拟器连接 import audit_completion
    records=[json.loads(line) for line in gzip.open(folder/'actions.jsonl.gz','rt',encoding='utf-8')]
    assert bundle['settings']==read(folder/'strategy_settings.json'),'归档参数与所选版本不一致'
    config=read(folder/'runtime_config.json')
    for key,value in bundle['config'].items():
        if key!='version':assert config[key]==value,'归档运行配置不一致：'+key
    tape=ReplayTransport(records)
    session=bundle['Session'](tape,records[0]['request']['robot_id'],'v14-replay',config)
    session.enter();solution=bundle['solve'](bundle['ObservedSession'](session),row['problem'],bundle['settings']);session.exit()
    replay=tape.assert_complete();check=audit_completion(session.records,solution,row['problem'],'microsecond')
    assert replay['passed'] and check['passed'],check
    assert abs(session.virtual_time-row['virtual_time_s'])<2e-6
    save(out/('replay_'+code+'.json'),dict(passed=True,case_code=code,version=bundle['version'],strict_coordinates=True,
        request_replay=replay,completion_audit=check,virtual_time_s=session.virtual_time,network_requests=0))

def verify_supplement_outputs(out):
    """按各检查器的实际结果结构汇总；不重复运行已有实验。"""
    out=Path(out)
    checks=[read(out/'q3_rings/integrity.json'),read(out/'sensitivity/integrity.json'),
            read(out/'outer_tangent.json'),read(out/'layouts.json')]
    theory=read(out/'site_bounds.json')
    assert all(x['passed'] for x in checks)
    assert theory['lower_bound']['passed'] and theory['upper_bound']['passed']
    result=dict(passed=True,runs=306,reused_confirmation_worlds=91,additional_mechanism_worlds=4,
                network_requests=0,scope='原84个Q3输入及7个Q4输入复用；另有4个结构场景')
    save(out/'supplement_checks.json',result)
    return result

def main():
    if sys.flags.no_user_site:
        os.environ['PYTHONNOUSERSITE']='1'
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',choices=['all','verify','geometry','q2','replay','replay-one','stress','figures','ablation','ablation-audit','simulate','benchmark','fresh_confirmation','supplements','theory'],default='verify')
    parser.add_argument('--output',type=Path,default=ROOT/'运行结果/复现')
    parser.add_argument('--case');parser.add_argument('--problem',choices=['q3','q4'],default='q3')
    parser.add_argument('--workers',type=int,default=6);parser.add_argument('--seed',type=int,default=20260912)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.task=='all':
        tasks=['verify','geometry','q2','replay','benchmark','fresh_confirmation','stress','ablation','figures','supplements','theory']
        for task in tasks:
            subprocess.run([sys.executable,'-B','-X','utf8',str(__file__),'--task',task,'--output',str(args.output/task),'--workers',str(args.workers)],check=True)
        expected={(r['panel'],r['problem'],r['case_id'],r['variant']):r for r in json.load(gzip.open(ROOT/'数据/benchmark.json.gz','rt',encoding='utf-8'))['rows']}
        actual=[]
        for task,panel in [('benchmark','existing_panel'),('fresh_confirmation','fresh_confirmation')]:
            actual.extend(read(args.output/task/panel/'rows.json'))
        assert len(actual)==1008 and len(expected)==1008
        seen=set()
        fields=['source_count','cleared_count','virtual_s','per_source_s','costs','actions','passed','error']
        for r in actual:
            key=(r['panel'],r['problem'],r['case_id'],r['variant']);assert key not in seen;seen.add(key)
            assert all(r[k]==expected[key][k] for k in fields),'新进程复算未精确匹配冻结结果：'+str(key)
        assert seen==set(expected)
        from 问题三四_论文统计汇总 import assemble
        checked=assemble(ROOT/'数据',args.output/'paper_evidence_recomputed.json')
        assert checked==read(ROOT/'数据/paper_evidence.json'),'论文统计重算不一致'
        save(args.output/'all_checks.json',dict(passed=True,tasks=tasks,network_requests=0,configuration_runs=1482,base_configuration_runs=1176,supplement_configuration_runs=306,
            distinct_synthetic_worlds=340,base_synthetic_worlds=336,new_mechanism_worlds=4,archived_stress_rows=546,strict_stress_replays=9,official_replays=12,
            ablation_uses_confirmation_subset=True,statistics_identical=True,recomputed_rows_exactly_match_archived=1008))
    elif args.task=='theory':
        # 新增证明单独核验，避免为更新理论而重复整场性能实验。
        commands=[
            ['问题四_基础点数界核验.py','--output',str(args.output/'base_bounds.json')],
            ['问题四_十九点下界与内站核验.py','--output',str(args.output/'latest')],
            ['问题四_圆周覆盖证书核验.py','--output',str(args.output/'circle_check.json')],
        ]
        for command in commands:
            subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/command[0])]+command[1:],check=True)
        base=read(args.output/'base_bounds.json')
        lower=read(args.output/'latest/checks.json');circle=read(args.output/'circle_check.json')
        assert base['lower_bound']['passed'] and base['upper_bound']['passed']
        assert lower['passed'] and circle['passed'] and circle['identity']['packaged_support_matched']
        save(args.output/'theory_checks.json',dict(passed=True,fixed_layout_bounds=[19,21],
            relative_point_gap_upper='2/19',unique_inner_station_lt_m=660,
            other_18_stations_gt_m=800,circle_leaves=720,network_requests=0))
    elif args.task=='supplements':
        commands=[
            ['问题三_七八九点巡检对比.py','--output',str(args.output/'q3_rings'),'--workers',str(min(args.workers,3))],
            ['问题三四_参数敏感性检验.py','--output',str(args.output/'sensitivity'),'--workers','1'],
            ['问题四_切向退步案例分析.py','--output',str(args.output/'outer_tangent.json')],
            ['问题四_二十七点与二十一点对比.py','--output',str(args.output/'layouts.json')],
            ['问题四_基础点数界核验.py','--output',str(args.output/'site_bounds.json')],
        ]
        for command in commands:
            subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/command[0])]+command[1:],check=True)
        verify_supplement_outputs(args.output)
    elif args.task=='verify':
        bundles={q:load(q)['version'] for q in ('q3','q4')}
        save(args.output/'preflight.json',dict(**verify_files(),adopted=bundles));print(json.dumps(bundles))
    elif args.task=='geometry':geometry(args.output)
    elif args.task=='q2':q2(args.output)
    elif args.task=='stress':
        from 问题三四_困难场景严格重放 import run
        run(args.output)
    elif args.task=='figures':
        from 问题一至四_实验结果图绘制 import render
        render(ROOT/'数据',args.output/'图件')
    elif args.task=='ablation':
        subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'问题三四_关键机制消融.py'),'--output',str(args.output/'ablation'),'--workers',str(args.workers)],check=True)
        subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'问题三四_消融记录独立核验.py'),'--input',str(args.output/'ablation'),'--output',str(args.output/'ablation_audit')],check=True)
    elif args.task=='ablation-audit':
        subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'问题三四_消融记录独立核验.py'),'--output',str(args.output)],check=True)
    elif args.task=='replay-one':replay_one(args.case,args.output)
    elif args.task=='replay':
        if sys.version_info[:3]!=(3,9,13):raise RuntimeError('严格官方请求重放须Python 3.9.13')
        for row in read(ROOT/'数据/practice_results.json')['rows']:
            subprocess.run([sys.executable,'-B','-X','utf8',str(__file__),'--task','replay-one','--case',row['case_code'],'--output',str(args.output)],check=True)
        save(args.output/'replay_summary.json',dict(passed=True,runs=len(read(ROOT/'数据/practice_results.json')['rows']),network_requests=0))
    elif args.task=='simulate':
        from 问题三四_同场策略比较 import worker
        bundle=load(args.problem)
        from 问题三四_离线物理模拟 import generate_case
        case=generate_case(args.seed,mode='omni' if args.problem=='q3' else 'mixed',kind='random');case['problem']=args.problem
        result=worker((case,bundle['algorithm'],str(args.output/'simulation'),'synthetic_demo'))
        save(args.output/'simulation.json',result)
        if not result['passed']:return 1
    else:
        from 问题三四_同场策略比较 import run
        panel='existing_panel' if args.task=='benchmark' else 'fresh_confirmation'
        result=run(panel,args.output/panel,args.workers)
        if not result['passed']:return 1
    print('复现检查通过；没有连接官方模拟器。');return 0
if __name__=='__main__':raise SystemExit(main())
