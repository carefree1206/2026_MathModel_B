"""Frozen solver once per problem; reuse delivered recording class without edits."""
import argparse, ast, copy, datetime, hashlib, json, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / '支撑材料'
OUT = Path(__file__).resolve().parents[2] / 'results' / 'demo'
sys.path.insert(0, str(ROOT))
from 问题三四_正式算法与参数入口 import load, verify_files
from 问题三四_离线物理模拟 import LocalSimulator, generate_case
from 问题三四_动作接口协议 import Session
from 问题三四_几何求解基线 import ObservedSession
from 问题三四_动作轨迹独立核验 import audit_records
from 问题三四_动作费用核算 import recompute
from 问题三四_交互模拟终端 import new_id, write_json

parser = argparse.ArgumentParser()
parser.add_argument('--problem', choices=['q3','q4'], required=True)
args = parser.parse_args()
problem = args.problem
bundle = load(problem)
identity = new_id()
out = OUT / identity
out.mkdir(parents=True, exist_ok=False)
started = time.monotonic()
parent_closed = threading.Event()
case = generate_case(20260912, mode='omni' if problem == 'q3' else 'mixed', kind='random')
transport = LocalSimulator(case)
trace = dict(schema='modeling-gui-trace-v1', id=identity, label=problem.upper()+' 随机 / 20260912 · CLI真实单局回放',
             problem=problem, mode='simulate', status='running', created_at=datetime.datetime.now().astimezone().isoformat(),
             error=None, elapsed_s=0, frames=[], truth=None, summary={}, output_directory=str(out))

def save(force=False):
    trace['elapsed_s'] = time.monotonic() - started
    write_json(out/'trace.json', trace)

source = ROOT/'问题三四_模拟与单局回放进程.py'
tree = ast.parse(source.read_text(encoding='utf-8-sig'))
recording_class = next(n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name=='RecordingSession')
exec(compile(ast.Module(body=[recording_class],type_ignores=[]), str(source), 'exec'))
write_json(out/'runtime_config.json', bundle['config'])
write_json(out/'strategy_settings.json', bundle['settings'])
write_json(out/'input_case.json', case)
import numpy, scipy
write_json(out/'manifest.json', dict(problem=problem,algorithm=bundle['algorithm'],version=bundle['version'],
    seed=20260912,kind='random',source='synthetic_offline_not_official',network_requests=0,
    python=sys.version,executable=sys.executable,numpy=numpy.__version__,scipy=scipy.__version__,
    frozen_precheck=verify_files(),recording_class_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    note='GUI启动停滞于进入场景前；本次独立CLI原样复用交付RecordingSession及冻结求解核心。'))
print('prepared',problem,identity,flush=True)
save(True)
try:
    with (out/'actions.jsonl').open('x',encoding='utf-8') as log:
        session = RecordingSession(transport,'offline',identity,bundle['config'],log=log)
        agent = bundle['klass'](ObservedSession(session), problem, bundle['settings'])
        session.agent = agent
        print('constructed',problem,flush=True)
        session.enter()
        solution = agent.run()
        session.exit()
        session.finish_previous()
    check = audit_records(session.records,case,solution,problem=problem)
    timing = recompute(session.records,clock_model='float',require_closed=True,require_http=True)
    write_json(out/'audit.json',check)
    write_json(out/'timing.json',timing)
    actual = transport.evaluate()
    negative = None
    if problem=='q3':
        from 问题三_阴性观测几何核验 import audit_trace
        negative=audit_trace(session.records,solution)
        write_json(out/'negative_geometry.json',negative)
    completed=(solution.get('termination')=='coverage_complete' and not solution.get('geometry_inconsistencies')
               and check['passed'] and timing['passed'] and actual['cleared_sources']==actual['total_sources']
               and (negative is None or negative['passed']))
    summary=dict(virtual_time_s=session.virtual_time,cleared=actual['cleared_sources'],source_count=actual['total_sources'],
       clearance_ratio=actual['clearance_ratio'],per_source_s=session.virtual_time/actual['cleared_sources'],
       actions=len(trace['frames']),normal_exit=session.closed,completed=completed,costs=session.costs,
       termination=solution['termination'],audit_passed=check['passed'],timing_passed=timing['passed'],
       version=bundle['version'],cleared_channels=solution['cleared_channels'],absent_channels=solution['absent_channels'])
    write_json(out/'solution.json',solution)
    write_json(out/'summary.json',summary)
    trace.update(status='completed' if completed else 'failed',summary=summary)
    save(True)
    print(json.dumps(dict(output=str(out),summary=summary),ensure_ascii=False),flush=True)
    if not completed:raise RuntimeError('Independent audit failed')
except BaseException as exc:
    trace.update(status='failed',error=type(exc).__name__+': '+str(exc))
    save(True)
    raise
