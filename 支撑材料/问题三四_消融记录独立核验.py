"""读取完整归档，检查单项变更范围及对应机制确实关闭。"""
from pathlib import Path
from collections import Counter,defaultdict
import gzip
import hashlib
import json
import math,argparse,zipfile,tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE
OUT=HERE/'数据/ablation'


def read(p): return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def without_real_timestamp(value):
    # 模拟器在每次响应中返回动作执行的现实时间戳。
    # 该时间戳不参与确定性的物理或误差反馈生成。
    if isinstance(value,dict):
        return {k:without_real_timestamp(v) for k,v in value.items() if k!='real_timestamp_ms'}
    if isinstance(value,list):return [without_real_timestamp(v) for v in value]
    return value


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,default=OUT);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    OUT=args.input.resolve();args.output.mkdir(parents=True,exist_ok=True)
    temp=tempfile.TemporaryDirectory(prefix='ablation_verify_');runroot=Path(temp.name)
    if (OUT/'runs.zip').exists():
        with zipfile.ZipFile(OUT/'runs.zip') as z:z.extractall(runroot)
    else:runroot=OUT/'runs'
    protocol=read(OUT/'protocol.json');rows=read(OUT/'rows.json')
    references=json.load(gzip.open(HERE/'数据/ablation/complete_reference.json.gz','rt',encoding='utf-8'))
    assert len(rows)==168 and len({(r['case_id'],r['variant']) for r in rows})==168
    inputs={c['case_id']:c for c in read(OUT/'cases.json')}
    assert set(inputs)==set(protocol['case_ids']) and len(inputs)==56
    if (OUT/'source_snapshot.zip').exists():
        with zipfile.ZipFile(OUT/'source_snapshot.zip') as z:
            assert all(hashlib.sha256(z.read(p)).hexdigest()==h for p,h in protocol['source_sha256'].items())
    else:
        # 旧执行源码在改名前已逐字节核对；交付副本单独核对，保留原实验身份。
        evidence=read(OUT/'原执行源码核对.json')
        assert evidence['original_source_sha256']==protocol['source_sha256']
        assert evidence['original_archive_verified_before_renaming']
        for item in evidence['chinese_programs']:
            assert sha(HERE/item['path'])==item['sha256']
    assert read(OUT/'integrity.json')['source_unchanged'] is True
    methods=defaultdict(Counter)
    actual_actions=0
    for row in rows:
        folder=runroot/row['case_id']/row['variant']
        case=read(folder/'case.json');result=read(folder/'result.json');solution=read(folder/'solution.json')
        assert case==inputs[row['case_id']]
        assert row['passed'] and result['passed'] and solution['termination']=='coverage_complete'
        assert result['cleared_count']==len(case['sources'])==row['source_count']==row['cleared_count']
        assert result['timing']['passed'] and result['independent']['passed']
        if row['problem']=='q3': assert result['negative_geometry']['passed']
        assert result['full_range_geometry']['passed']
        assert not solution['geometry_inconsistencies']
        c=result['costs']
        physical=c['move_m']/5 +5*c['measures']+c['switch_s']+3*c['clears']+2*c['successes']
        assert abs(physical-result['virtual_s'])<1e-7
        cfg=dict(result['settings']);label=cfg.pop('_ablation_label')
        assert label==row['variant']
        base=dict(read(runroot/row['case_id']/'complete'/'result.json')['settings'])
        base.pop('_ablation_label')
        if label=='no_posterior_optical':base['posterior_optical']=False
        elif label=='no_transit':base['intercept_cap']=0
        elif label=='no_known_gate':base['scan_gain_m']=None
        assert cfg==base
        count=Counter(e['method'] for e in solution['events'])
        methods[row['problem'],label].update(count)
        if label=='no_posterior_optical':assert not count['m020_posterior_optical_choice']
        if label=='no_cost_pair':assert not count['m020_cost5_pair_ranking']
        if label=='no_transit':assert not count['enroute_measure_choice']
        if label=='no_known_gate':assert not count['optional_known_scan_skipped'] and cfg['scan_count_stop'] is True
        # 完整策略须逐项匹配先前执行，包括所有
        # 请求与响应，只有用于区分算法的标签允许改变。
        with gzip.open(folder/'actions.jsonl.gz','rt',encoding='utf8') as f:actions=[json.loads(s) for s in f]
        assert len(actions)==row['actions']
        actual_actions+=len(actions)
        if label=='complete':
            variant='m020' if row['problem']=='q3' else 'm021'
            reference=references[row['case_id']]
            assert without_real_timestamp(solution)==without_real_timestamp(reference['solution'])
            previous=reference['actions']
            # 所有已接受请求、响应、虚拟费用和几何结果须
            # 保持一致；仅模拟器现实时间戳允许不同。
            assert without_real_timestamp(previous)==without_real_timestamp(actions)
    assert methods['q3','complete']['m020_cost5_pair_ranking']>0
    assert methods['q3','complete']['m020_posterior_optical_choice']>0
    assert methods['q3','no_cost_pair']['v14_geometric_pair_without_cost_ranking']>0
    assert methods['q3','no_cost_pair']['m020_posterior_optical_choice']>0
    assert methods['q3','no_posterior_optical']['m020_cost5_pair_ranking']>0
    assert methods['q4','complete']['enroute_measure_choice']>0
    assert methods['q4','complete']['optional_known_scan_skipped']>0
    assert methods['q4','no_transit']['optional_known_scan_skipped']>0
    assert methods['q4','no_known_gate']['enroute_measure_choice']>0
    relevant=['m020_cost5_pair_ranking','m020_posterior_optical_choice',
              'v14_geometric_pair_without_cost_ranking','enroute_measure_choice',
              'optional_known_scan_skipped','stationary_information_choice']
    result=dict(passed=True,runs=len(rows),source_instances=sum(r['source_count'] for r in rows),
                actual_actions=actual_actions,independent_worlds=len(inputs),complete_solution_and_actions_equal_rows=56,
                comparison_ignores_only='real_timestamp_ms (execution date/time)',
                archived_source_identity_verified_before_renaming=True,
                source_hashes_unchanged_during_execution=True,
                scope='Archived configuration differences, disabled/retained mechanisms, input identity, source clearing, solution equality and fee sum; original per-run auditors also independently check physical responses and geometry.',
                event_counts=[dict(problem=q,label=label,**{k:cnt[k] for k in relevant}) for (q,label),cnt in methods.items()])
    (args.output/'mechanism_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
