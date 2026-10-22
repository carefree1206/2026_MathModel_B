# -*- coding: utf-8 -*-
"""每场独立执行冻结策略，将真实动作和当时的策略状态保存为可视化帧。"""
import argparse
import copy
import gzip
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import urllib.request

from 问题三四_交互模拟终端 import Catalog, acquire_output_lock, read_json, validate_run, write_json


class ParentStopped(RuntimeError):
    """父终端已关闭，当前请求完成后不再发送下一个动作。"""
    pass


def exit_on_local_limit(session, exc, parent_closed):
    """只有确定尚未发送下一动作且仍在期限内，才保存当前成绩并退出。"""
    from 问题三四_动作接口协议 import ExecutionLimit
    before_send = isinstance(exc, ExecutionLimit) and str(exc) in (
        'Real-time exit reserve reached', 'Virtual-time limit would be reached')
    if (before_send and not parent_closed.is_set() and session.entered
            and not session.closed and session.remaining() > 0):
        session.exit()
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    job = read_json(args.request)
    out = Path(job['out_dir']).resolve()
    if out != args.request.resolve().parent:
        raise ValueError('工作目录必须与后端生成的任务文件同目录')
    trace = read_json(out / 'trace.json')
    started, last_saved = time.monotonic(), [0.]
    secret = job.get('robot_id', '')
    session = None
    worker_lock = None
    parent_closed = threading.Event()
    limit_stopped = False

    def watch_parent():
        # 父服务持有管道写端。关闭窗口或强杀父进程都会令本端读到EOF。
        try:
            # 底层读取不占用Python缓冲锁，正常求解完成后解释器可直接退出。
            while os.read(sys.stdin.fileno(), 1024):
                pass
        finally:
            parent_closed.set()

    def save(force=False):
        now = time.monotonic()
        if force or now - last_saved[0] >= .12:
            trace['elapsed_s'] = now - started
            write_json(out / 'trace.json', trace)
            last_saved[0] = now

    def public_error(exc):
        message = str(exc)
        if secret:
            message = message.replace(secret, '[身份已隐藏]')
        return '运行未完成（' + type(exc).__name__ + '）：' + message[:350]

    try:
        worker_lock = acquire_output_lock(out.parent / '.gui.worker.lock',
            '已有求解工作进程占用此结果目录，未发送任何新请求')
        if job.get('parent_pipe') is True:
            threading.Thread(target=watch_parent, daemon=True).start()
        # 即使手动运行worker，也不能绕过“用户已手动开局”与本机URL校验。
        catalog = Catalog(root)
        settings_request = validate_run(job, catalog)
        problem, mode = settings_request['problem'], settings_request['mode']
        from 问题三四_正式算法与参数入口 import load
        bundle=load(problem)
        if mode=='official' and sys.version_info[:3]!=(3,9,13):raise RuntimeError('官方入口请使用已核验的 Python 3.9.13')
        from 问题三四_几何求解基线 import ObservedSession
        from 问题三四_动作接口协议 import Session, HttpTransport, ExecutionLimit
        from 问题三四_离线物理模拟 import LocalSimulator, generate_case
        from 问题三四_动作费用核算 import recompute
        from 问题三四_动作轨迹独立核验 import audit_records

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            # 本机模拟器也不允许通过HTTP重定向把请求转发到其他主机。
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        config = bundle['config']
        settings = bundle['settings']
        case, expected_job = None, None
        robot_id = 'offline'
        if mode == 'simulate':
            if settings_request.get('case_id'):
                expected_job = catalog.case(settings_request['case_id'], problem)
                case = expected_job['case']
                settings = expected_job['settings']

            else:
                case = generate_case(settings_request['seed'],
                                     mode='omni' if problem == 'q3' else 'mixed', kind=settings_request['kind'])
            transport = LocalSimulator(case)
            # 仅GUI审计叠层持有真值；ObservedSession不会暴露此字段或transport。
            trace['truth'] = [{'position': [s['x_m'], s['y_m']], 'channel': s['channel'],
                               'kind': 'omni' if s['orientation_deg'] is None else 'directional',
                               'radius_m': s['reception_radius_m'], 'direction_deg': s['orientation_deg']}
                              for s in case['sources']]
        else:
            robot_id = settings_request['robot_id']
            transport = HttpTransport(settings_request['url'])
            transport.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            trace['truth'] = None

        class RecordingSession(Session):
            def __init__(self, *values, **kwargs):
                super().__init__(*values, **kwargs)
                self.agent = None
                self.event_cursor = 0

            def explain(self, frame, old_tracks, events):
                """解释仅取本次动作后实际产生的日志和区域，不猜测未执行分支。"""
                action, result, channel = frame['action'], frame['result'], frame['channel']
                track = self.agent.tracks.get(channel)
                methods = sorted(set(e.get('method', '') for e in events if e.get('method')))
                frame['model_events'] = methods
                if action == 'enter':
                    return '已进入场景；从原点、测向机频道1开始。后续逐频道实际检测，隐藏源位置不交给策略。'
                if action == 'exit':
                    return '已发送结束指令；当前已清除' + str(frame['cleared']) + '个已发现源。任务是否完成以运行摘要和审计结论为准。'
                if action == 'clear':
                    actual = [e for e in events if e.get('channel') == channel and
                              type(e.get('success')) is bool and 'position' in e]
                    event = actual[-1] if actual else {}
                    labels = {'near': '近距响应后的光学清除', 'center_probe': '局部中心方案试清',
                              'adaptive_clear_cell': '完整矩形网格清除',
                              'finite_fallback': '首测条带后备清除', 'shared_probe': '当前位置共享试清'}
                    method = event.get('method')
                    label = labels.get(method, '光学尝试')
                    message = '频道' + str(channel) + '执行' + label + '：'
                    if result == 'success':
                        message += '已成功清除；该位置只证明源在20米内，不是精确源坐标。'
                    else:
                        message += '未发现目标，本次3秒光学费用已计入，目标仍保留。'
                    if event.get('guaranteed') is True:
                        message += '该动作在执行前具有区域或近距覆盖依据。'
                    elif event:
                        message += '该动作是允许失败的试探，不能因成功就倒推整个区域已被覆盖。'
                    return message
                count = len(self.agent.measured.get(channel, []))
                message = '频道' + str(channel) + '第' + str(count) + '次实际检测：'
                if result == 'near':
                    return message + '得到5米内近距响应，下一动作可启动光学清除。本帧仅确认近距，尚未提前标记清除成功。'
                if result == 'direction':
                    message += '已取得示向并更新角楔约束；有效观测共' + str(len(track.observations)) + '次。'
                else:
                    message += '无信号。'
                    if not track.observations:
                        message += '尚未发现该频道源，继续积累真实检测位置作为覆盖证据。'
                    elif problem == 'q4':
                        message += '可能超距或背向，不能套用全向1000米排除圆。'
                negatives = [e for e in events if e.get('channel') == channel and e.get('method') == 'q3_negative_reception']
                if negatives:
                    if any(e.get('radius_comparison_planes') for e in negatives):
                        message += '已使用同源半径固定的正负距离半平面。'
                    if any(e.get('excluded_radius_m') is not None for e in negatives):
                        message += '已执行999.9米阴性圆盘排除及保守凸外包更新。'
                if any(e.get('channel') == channel and e.get('method') == 'two_sided_negative_halfplane' for e in events):
                    message += '两侧均取得实际阴性，且全域距离与射线夹持证书成立，已保留对应近侧闭半平面。'
                if track.inconsistent:
                    message += '当前记录存在几何不一致，不能赋予保证清除结论。'
                elif track.circle is not None:
                    radius = track.circle[1]
                    old = next((t.get('circle') for t in old_tracks if t['channel'] == channel), None)
                    if old is not None and abs(old['radius_m'] - radius) >= .001:
                        message += '包围圆半径由%.3f米变为%.3f米。' % (old['radius_m'], radius)
                    else:
                        message += '当前包围圆半径约%.3f米。' % radius
                    message += '满足19.99米工作阈值。' if radius <= 19.99 else '尚未满足19.99米一次保证清除阈值。'
                return message

            def finish_previous(self):
                """下一次真实动作前采集上一动作的完成态，正确分开near及内嵌clear。"""
                if not trace['frames'] or not trace['frames'][-1].get('state_pending'):
                    return
                frame = trace['frames'][-1]
                agent = self.agent
                if agent is None:
                    return
                old_tracks = frame.get('tracks', [])
                event_end = len(agent.events)
                events = agent.events[self.event_cursor:event_end]
                self.event_cursor = event_end
                states = []
                for channel, track in sorted(agent.tracks.items()):
                    if not track.observations and not track.poly and not track.cleared:
                        continue
                    circle = None if track.circle is None else {
                        'center': list(track.circle[0]), 'radius_m': track.circle[1]}
                    states.append({'channel': channel, 'poly': [list(p) for p in (track.poly or [])],
                                   'circle': circle, 'cleared': bool(track.cleared),
                                   'inconsistent': bool(track.inconsistent),
                                   'observations': copy.deepcopy(track.observations)})
                frame['tracks'] = states
                frame['discovered'] = sum(bool(t.observations) for t in agent.tracks.values())
                frame['cleared'] = sum(bool(t.cleared) for t in agent.tracks.values())
                frame['planned_sites'] = [list(p) for _, p in agent.todo]
                # scanned可能先登记再发送；这里严格采用实际已完成的measure历史。
                frame['measured_sites'] = [list(p) for p in sorted(set(
                    tuple(p) for history in agent.measured.values() for p in history))]
                frame['explanation'] = self.explain(frame, old_tracks, events)
                frame['state_pending'] = False

            def act(self, endpoint, position=None, channel=None):
                self.finish_previous()
                if parent_closed.is_set():
                    raise ParentStopped('终端服务已关闭，已保留此前有效动作；未发送后续动作或退出请求')
                response = super().act(endpoint, position, channel)
                # Session.write早于协议核验和计费；只有act成功返回才能形成新帧。
                action = endpoint.lstrip('/')
                result = ('entered' if action == 'enter' else 'exited' if action == 'exit' else
                          response.get('measure_result') if action == 'measure' else response.get('clear_result'))
                explanations = {
                    'entered': '已进入场景，从原点及频道1开始；策略只读取实际观测。',
                    'direction': '取得带误差示向，下一帧刷新前将由策略更新该频道的保守定位区域。',
                    'near': '收到5米内近距响应，随后进行光学清除；此帧不能提前记为清除成功。',
                    'no_signal': '此处无信号。全向时可使用固定半径信息；定向时不能直接排除近距区域。',
                    'success': '光学清除成功；清除点距真实源不超过20米，不等于精确源坐标。',
                    'no_target_in_range': '光学尝试未发现目标，仍计入3秒费用，策略继续定位或后备清除。',
                    'exited': '已发送结束指令；以最终完成证据和审计结果确认本次状态。'}
                previous = trace['frames'][-1] if trace['frames'] else {}
                frame = {'index': len(trace['frames']), 'action': action, 'position': list(self.position),
                         'channel': channel if channel is not None else self.channel,
                         'radio_channel': self.channel,
                         'time_s': self.virtual_time, 'result': result,
                         'bearing_deg': response.get('svd_deg'),
                         'costs': {k: self.costs[k] for k in ('move_s', 'measure_s', 'switch_s', 'optical_s', 'laser_s')},
                         'discovered': previous.get('discovered', 0), 'cleared': previous.get('cleared', 0),
                         'tracks': copy.deepcopy(previous.get('tracks', [])),
                         'planned_sites': copy.deepcopy(previous.get('planned_sites', [])),
                         'measured_sites': copy.deepcopy(previous.get('measured_sites', [])),
                         'explanation': explanations[result], 'state_pending': True}
                trace['frames'].append(frame)
                save()
                return response

        from 问题三四_官方模拟器连接 import snapshot
        from 问题三四_正式算法与参数入口 import MODEL, read
        bundle['source_files']=read(root/'数据/程序校验.json')['sha256']
        environment=snapshot(out,bundle,sys.argv)
        write_json(out/'manifest.json',dict(version=bundle['version'],problem=problem,mode=mode,environment=environment))
        write_json(out/'runtime_config.json',config)
        write_json(out/'strategy_settings.json',settings)
        trace.update(status='running', error=None)
        save(True)
        with (out / 'actions.jsonl').open('w', encoding='utf-8') as log:
            session = RecordingSession(transport, robot_id, job['id'], config, log=log)
            # 与官方命令行一致：初始构造完成后进入本局。
            agent = bundle['klass'](ObservedSession(session), problem, settings)
            session.agent = agent
            session.enter()
            try:
                solution = agent.run()
            except ExecutionLimit as exc:
                # 仍处于日志文件的上下文中，允许的期限退出也须记入原始动作。
                limit_stopped = exit_on_local_limit(session, exc, parent_closed)
                raise
            session.exit()
            session.finish_previous()
            if solution.get('termination') != 'coverage_complete' or solution.get('geometry_inconsistencies'):
                raise RuntimeError('策略未形成无异常的完整退出证据；已保存实际动作并退出')
            summary = {'virtual_time_s': session.virtual_time, 'cleared': len(solution['cleared_channels']),
                       'cleared_channels': solution['cleared_channels'], 'absent_channels': solution['absent_channels'],
                       'termination': solution['termination'], 'actions': len(trace['frames']),
                       'normal_exit': True, 'completed': True,
                       'costs': copy.deepcopy(session.costs),
                       'version': bundle['version']}
            if mode == 'simulate':
                check = audit_records(
                    session.records, case, solution, problem=problem)
                if not check['passed']:
                    raise RuntimeError('离线物理或连续退出审计未通过')
                if problem == 'q3':
                    from 问题三_阴性观测几何核验 import audit_trace
                    if not audit_trace(session.records, solution)['passed']:
                        raise RuntimeError('全向阴性几何独立核验未通过')
                actual = transport.evaluate()
                if actual['cleared_sources'] != actual['total_sources']:
                    raise RuntimeError('合成场景仍有未清除源')
                summary.update(source_count=actual['total_sources'], clearance_ratio=actual['clearance_ratio'], audit_passed=True)
                if expected_job is not None:
                    delta = abs(session.virtual_time - expected_job['expected_time_s'])
                    if delta > 1e-5 or len(session.records) != expected_job['expected_actions']:
                        raise RuntimeError('冻结场景时间或动作数与论文记录不一致')
                    summary['time_difference_s'] = delta
            else:
                summary.update(case_code=settings_request['case_code'], test_mode=settings_request['test_mode'],
                               source_count=None, audit_passed=None)
                from 问题三四_官方模拟器连接 import audit_completion
                official_check=audit_completion(session.records,solution,problem,'microsecond')
                write_json(out/'audit.json',official_check)
                if not official_check['passed']:raise RuntimeError('官方反馈完成证据核验未通过')
                summary['audit_passed']=True
            timing = recompute(session.records, clock_model='float' if mode == 'simulate' else 'microsecond',
                               require_closed=True, require_http=True)
            if not timing['passed']:
                raise RuntimeError('逐动作计费核验未通过')
            summary['timing_passed'] = True
            summary['per_source_s'] = session.virtual_time / summary['cleared'] if summary['cleared'] else None
            write_json(out/'solution.json',solution)
            write_json(out/'summary.json',summary)
            trace.update(status='completed', summary=summary)
            save(True)
        print('完成：' + job['id'], flush=True)
    except BaseException as exc:
        # 前置期限分支已在日志上下文内处理；其他错误、停止和不确定通信不发送新请求。
        if session is not None:
            session.finish_previous()
        message = public_error(exc)
        status = 'stopped' if isinstance(exc, ParentStopped) else 'failed'
        trace.update(status=status, error=message)
        if session is not None:
            trace['summary'] = {'virtual_time_s': session.virtual_time, 'cleared': session.costs['successes'],
                                'actions': len(trace['frames']), 'costs': copy.deepcopy(session.costs),
                                'normal_exit': bool(session.closed), 'completed': False,
                                'termination': 'limit_stopped' if limit_stopped else 'incomplete'}
        save(True)
        detail = traceback.format_exc()
        if secret:
            detail = detail.replace(secret, '[身份已隐藏]')
        write_json(out / 'error.json', {'error': message, 'detail': detail, 'status': status})
        print(message, flush=True)
        return 1
    finally:
        if worker_lock is not None:
            worker_lock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
