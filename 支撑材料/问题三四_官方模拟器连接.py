# -*- coding: utf-8 -*-
"""将逐问固定算法接入用户已手动启动的官方测试。"""
import argparse
import datetime
import hashlib
import importlib
import json
import os
import platform
import sys
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE
MODEL = HERE



def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n', encoding='utf-8')


def load_policy(problem):
    from 问题三四_正式算法与参数入口 import load
    bundle=load(problem)
    bundle['source_files']=read(HERE/'数据/程序校验.json')['sha256']
    return bundle


def audit_completion(records, solution, problem, clock_model):
    """只用实际反馈核验费用、清除和不存在证据；不读取官方隐藏真值。"""
    from 问题三四_动作费用核算 import recompute
    from 问题三四_动作轨迹独立核验 import continuous_cover
    # 丢失响应的记录没有 HTTP 状态；计费核验会检查相同请求是否最终得到确认。
    timing = recompute(records, clock_model=clock_model, require_closed=True, require_http=False)
    errors = ['响应缺少 HTTP 状态' for r in records
              if 'response' in r and type(r.get('http_status')) is not int]
    seen, logical = set(), []
    for r in records:
        if r.get('http_status') == 200 and r.get('accepted') is True and r['request_id'] not in seen:
            seen.add(r['request_id'])
            logical.append(r)
    observed, cleared = set(), set()
    negatives = {ch: [] for ch in range(1, 21)}
    for r in logical:
        req, res = r['request'], r['response']
        if r['endpoint'] == '/measure':
            ch = req['channel']
            if res['measure_result'] in ('direction', 'near'):
                observed.add(ch)
            elif res['measure_result'] == 'no_signal':
                negatives[ch].append((req['position']['x'], req['position']['y']))
        elif r['endpoint'] == '/clear' and res.get('clear_result') == 'success':
            ch = req['channel']
            if ch in cleared or ch not in observed:
                errors.append('清除记录重复，或清除前没有观测到该源')
            cleared.add(ch)
    if not logical or logical[-1]['endpoint'] != '/exit' or logical[-1]['response'].get('exit_reason') != 'user_exit':
        errors.append('没有确认正常退出')
    absent = set(range(1, 21)) - observed
    if not solution or solution.get('termination') != 'coverage_complete' or solution.get('geometry_inconsistencies'):
        errors.append('策略未完成，或几何约束存在矛盾')
    if solution and (set(solution.get('cleared_channels', [])) != cleared
                     or set(solution.get('absent_channels', [])) != absent):
        errors.append('求解结果中的频道集合与实际反馈不符')
    if observed != cleared or not 10 <= len(cleared) <= 16:
        errors.append('已发现源尚未清完，或清除数量不符合题设')
    covers = {}
    if len(cleared) == 16:
        basis = '已观测并成功清除16个不同频道，达到源数上限'
    else:
        basis = '以实际无信号反馈核验未发现频道的连续覆盖'
        for ch in sorted(absent):
            covers[str(ch)] = continuous_cover(negatives[ch], problem)
            if not covers[str(ch)]['passed']:
                errors.append('频道不存在证据未通过：' + str(ch))
    negative = None
    if problem == 'q3' and solution:
        from 问题三_阴性观测几何核验 import audit_trace
        negative = audit_trace(records, solution)
        if not negative['passed']:
            errors.append('Q3阴性观测几何核验未通过')
    return dict(passed=timing['passed'] and not errors, errors=errors, timing=timing,
                cleared_count=len(cleared), cleared_channels=sorted(cleared),
                absence_basis=basis, absence_checks=covers, negative_geometry=negative,
                truth_available=False,
                scope='本地反馈一致性核验；全清比例须再与官方界面总源数核对，原始jlog另行导出。')


def snapshot(out, bundle, argv):
    """按项目相对路径归档，让本局源码解压后仍可独立预检。"""
    files = {MODEL / name for name in bundle['source_files']}
    files.update(HERE/name for name in ('复现说明.md','环境依赖.txt','数据/程序校验.json'))
    hashes = {p.relative_to(WORKSPACE).as_posix(): sha(p) for p in sorted(files)}
    with zipfile.ZipFile(out / 'source_snapshot.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(hashes):
            archive.write(WORKSPACE / name, name)
    write(out / 'runtime_config.json', bundle['config'])
    write(out / 'strategy_settings.json', bundle['settings'])
    import numpy
    import scipy
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                numpy=numpy.__version__, scipy=scipy.__version__, argv=argv,
                source_sha256=hashes, source_snapshot_sha256=sha(out / 'source_snapshot.zip'))


def execute(bundle, transport, robot_id, out, case_code, *, test_mode='practice',
            mode='official', argv=None, progress=True, clock_model='microsecond'):
    """一次调用只跑一局；注入内存响应可检查接口，全程无需连接官方程序。"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    run_id = bundle['algorithm'] + '-' + uuid.uuid4().hex[:12]
    manifest = dict(run_id=run_id, algorithm=bundle['algorithm'], version=bundle['version'],
                    problem=bundle['problem'], module=bundle['module'], mode=mode,
                    test_mode=test_mode, case_code=case_code, status='preparing',
                    environment=snapshot(out, bundle, argv or []))
    write(out / 'manifest.json', manifest)
    solution, error, solver, started = None, None, None, None
    with (out / 'actions.jsonl').open('x', encoding='utf-8') as log:
        session = bundle['Session'](transport, robot_id, run_id, bundle['config'], log)
        try:
            # 初始路线与覆盖证书在进入测试前计算，减少占用本局接口时间。
            solver = bundle['klass'](bundle['ObservedSession'](session), bundle['problem'], bundle['settings'])
            manifest['status'] = 'running'
            write(out / 'manifest.json', manifest)
            if progress:
                print('运行版本：' + bundle['version'] + '\n结果目录：' + str(out), flush=True)
            started = time.monotonic()
            session.enter()
            solution = solver.run()
            session.exit()
        except bundle['ExecutionLimit'] as exc:
            error = type(exc).__name__ + ': ' + str(exc)
            # 仅在确定下一动作尚未发送时主动退出；接收状态未知时不追加新动作。
            before_send = str(exc) in ('Real-time exit reserve reached', 'Virtual-time limit would be reached')
            if before_send and session.entered and not session.closed and session.remaining() > 0:
                try:
                    session.exit()
                except (Exception, KeyboardInterrupt) as exit_error:
                    error += '; 退出未确认：' + type(exit_error).__name__ + ': ' + str(exit_error)
        except KeyboardInterrupt:
            error = '用户中断；最后请求的接收状态可能未知，请勿在同局重新运行。'
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        runtime = time.monotonic() - started if started is not None else 0.0
    if solution is not None:
        write(out / 'solution.json', solution)
    else:
        write(out / 'partial_solution.json', dict(events=getattr(solver, 'events', []), completed=False))
    try:
        audit = audit_completion(session.records, solution, bundle['problem'], clock_model)
    except Exception as exc:
        audit = dict(passed=False, error=type(exc).__name__ + ': ' + str(exc), truth_available=False)
    write(out / 'audit.json', audit)
    count = session.costs['successes']
    success = error is None and audit['passed']
    summary = dict(algorithm=bundle['algorithm'], version=bundle['version'], problem=bundle['problem'],
                   module=bundle['module'], mode=mode, test_mode=test_mode, case_code=case_code,
                   status='completed' if success else 'failed', self_check='passed' if success else 'failed',
                   normal_exit=session.closed, error=error,
                   termination=solution.get('termination') if solution else 'aborted',
                   virtual_time_s=session.virtual_time, program_runtime_s=runtime,
                   cleared_count=count, average_virtual_time_per_cleared_s=session.virtual_time / count if count else None,
                   cost_breakdown=session.costs, official_total_sources=None, official_clearance_ratio=None,
                   official_result_verified=False, official_log='请从模拟器导出本局原始 .jlog，并保存结果截图。')
    write(out / 'summary.json', summary)
    manifest.update(status=summary['status'], self_check=summary['self_check'])
    write(out / 'manifest.json', manifest)
    if progress:
        print('本地核验：' + ('通过' if success else '未通过') + '；清除数：' + str(count), flush=True)
        if count:
            print('完整虚拟耗时 / 清除数：%.6f 秒/源' % summary['average_virtual_time_per_cleared_s'], flush=True)
        if error:
            print('运行异常：' + error, flush=True)
        print('结果目录：' + str(out), flush=True)
        print(summary['official_log'], flush=True)
    return dict(output=str(out), **summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--problem', choices=['q3', 'q4'], required=True, help='须与模拟器题号一致')
    parser.add_argument('--check', action='store_true', help='离线核对源码、参数、环境和初始构造，不发请求')
    parser.add_argument('--manual-started', action='store_true', help='确认已手动开局并等待接口就绪')
    parser.add_argument('--case-code', help='模拟器当前局的案例编码，仅用于本地归档')
    parser.add_argument('--test-mode', choices=['practice', 'formal'], default='practice', help='归档类别，默认演练；不操作模拟器界面')
    parser.add_argument('--url', default='http://127.0.0.1:2026', help='模拟器显示的本机 HTTP 地址')
    parser.add_argument('--output', help='项目内尚不存在的输出目录；默认按版本和时间新建')
    args = parser.parse_args(argv)
    try:
        if platform.python_version() != '3.9.13':
            raise ValueError('请使用已验证的 Python 3.9.13；环境说明见复现说明.md')
        if not args.check:
            if not args.manual_started or not args.case_code or not args.case_code.strip():
                raise ValueError('请先手动开局，再提供 --manual-started 和 --case-code；尚未连接模拟器')
            robot = os.environ.get('B_ROBOT_ID', '')
            if not 1 <= len(robot.encode('utf-8')) <= 64 or any(unicodedata.category(c).startswith('C') for c in robot):
                raise ValueError('请将 B_ROBOT_ID 设置为当前登录参赛队号；不需要密码')
        bundle = load_policy(args.problem)
        if args.check:
            session = bundle['Session'](None, 'offline', 'preflight', bundle['config'])
            bundle['klass'](bundle['ObservedSession'](session), args.problem, bundle['settings'])
            print(json.dumps(dict(status='passed', version=bundle['version'], module=bundle['module'],
                                  problem=args.problem, python=platform.python_version(), network_requests=0,
                                  frozen_files=len(bundle['source_files'])), ensure_ascii=False))
            return 0
        from 问题三四_正式算法与参数入口 import local_url
        import urllib.request
        transport = bundle['HttpTransport'](local_url(args.url))
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):return None
        transport.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        folder = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_') + bundle['algorithm'] + '_' + args.problem + '_' + uuid.uuid4().hex[:6]
        out = (WORKSPACE / (args.output or ('运行结果/官方/' + folder))).resolve()
        if WORKSPACE.resolve() not in out.parents or out.exists():
            raise ValueError('输出目录须位于项目内且尚不存在，历史记录不会覆盖')
        result = execute(bundle, transport, robot, out, args.case_code.strip(), test_mode=args.test_mode,
                         argv=sys.argv if argv is None else argv)
        return 0 if result['status'] == 'completed' else 1
    except (OSError, ValueError, KeyError, ImportError) as exc:
        parser.exit(2, '接入失败：' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
