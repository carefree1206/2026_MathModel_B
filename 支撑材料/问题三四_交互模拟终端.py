# -*- coding: utf-8 -*-
"""统一可视化终端：只在本机提供页面，每次求解使用独立工作进程。"""
import argparse
import datetime
import gzip
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 32 * 1024 * 1024
ID_PATTERN = re.compile(r'^(?:run|import)_[0-9]{8}_[0-9]{6}_[a-f0-9]{12}$')
FINAL_STATES = {'completed', 'failed', 'stopped'}
ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('JSON不能包含非有限数值')))


def write_json(path, value):
    """临时文件原子替换，轮询和停止时不会读到半份 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(4) + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    separators=(',', ':')), encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(str(temporary), str(path))
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.01)


def text_field(value, name, maximum=160, allow_empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not value.strip() and not allow_empty):
        raise ValueError(name + '必须是长度合适的文字')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(name + '包含不允许的控制字符')
    return value.strip()


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name + '必须是范围内的整数')
    return value


def local_url(value):
    """只允许显式回环 HTTP 地址；不解析任意主机、不接受重定向路径。"""
    value = text_field(value, '模拟器地址', 180)
    if any(c.isspace() for c in value):
        raise ValueError('模拟器地址不能包含空格或换行')
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError('模拟器地址或端口无效')
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or port is None or not 1 <= port <= 65535 or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('请输入带端口的本机 HTTP 地址，例如 http://127.0.0.1:2026')
    return value.rstrip('/')


class Catalog:
    def __init__(self, root):
        self.root = Path(root)
        with gzip.open(self.root / '数据/offline_cases.json.gz', 'rt', encoding='utf-8') as stream:
            jobs = json.load(stream)
        self.jobs = [j for j in jobs['jobs'] if
                     (j['problem'] == 'q3' and j['variant'] == 'm020') or
                     (j['problem'] == 'q4' and j['variant'] == 'selected')]

    def case(self, identity, problem):
        for job in self.jobs:
            if job['case']['case_id'] == identity and job['problem'] == problem:
                return job
        raise ValueError('找不到该题号的冻结主线场景')

    def public(self):
        return {'cases': [{'id': j['case']['case_id'], 'problem': j['problem'],
                           'variant': j['variant'], 'label': j['problem'].upper() + ' ' + j['case']['case_id']}
                          for j in self.jobs]}


def validate_run(value, catalog):
    if not isinstance(value, dict):
        raise ValueError('运行参数必须是JSON对象')
    mode = value.get('mode')
    if mode not in ('simulate', 'official'):
        raise ValueError('请选择离线模拟或官方接口')
    problem = value.get('problem')
    if problem not in ('q3', 'q4'):
        raise ValueError('题号必须为q3或q4')
    if mode == 'simulate':
        case_id = value.get('case_id')
        if case_id:
            catalog.case(text_field(case_id, '冻结场景编号'), problem)
            return {'mode': mode, 'problem': problem, 'case_id': case_id,
                    'label': problem.upper() + ' 冻结场景 ' + case_id}
        seed = integer(value.get('seed', 20260912), '随机种子', 0, 2147483647)
        kind = value.get('kind', 'random')
        if kind not in ('random', 'boundary', 'cluster'):
            raise ValueError('离线场景类型无效')
        labels = {'random': '随机', 'boundary': '圆周边界', 'cluster': '聚集'}
        return {'mode': mode, 'problem': problem, 'seed': seed, 'kind': kind,
                'label': problem.upper() + ' ' + labels[kind] + ' / ' + str(seed)}
    if value.get('manual_started') is not True:
        raise ValueError('请先在模拟器手动启动场景，再明确勾选接口已就绪')
    test_mode = value.get('test_mode')
    if test_mode not in ('practice', 'formal'):
        raise ValueError('请明确选择官方演练或正式测试')
    case_code = text_field(value.get('case_code'), '案例编码', 80)
    return {'mode': mode, 'problem': problem, 'url': local_url(value.get('url')),
            'robot_id': text_field(value.get('robot_id'), '当前参赛队号', 128),
            'manual_started': True, 'test_mode': test_mode, 'case_code': case_code,
            'label': problem.upper() + (' 正式测试 ' if test_mode == 'formal' else ' 官方演练 ') + case_code}


def new_id():
    return 'run_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(6)


class BusyError(Exception):
    pass


def acquire_output_lock(path, message):
    """保留返回句柄即持续持有系统锁；进程退出后由操作系统自动释放。"""
    path = Path(path)
    handle = path.open('a+b')
    try:
        # 不读取已被其他进程锁住的字节；Windows会拒绝这种读取。
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ValueError(message)
    return handle


class RunManager:
    def __init__(self, root, output):
        self.root, self.output = Path(root).resolve(), Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        # 相同结果目录只允许一个服务进程管理，避免重复双击产生两只求解器。
        self.instance_lock = acquire_output_lock(self.output / '.gui.lock',
            '该结果目录已有终端运行，请回到已打开的终端页面')
        try:
            # 父服务可能被强杀，但原worker还在等待HTTP；此时不改写旧轨迹。
            probe = acquire_output_lock(self.output / '.gui.worker.lock',
                '原求解进程仍在等待本次请求结束，请稍后重新打开终端；未启动新求解')
            probe.close()
            self.catalog = Catalog(self.root)
        except BaseException:
            self.instance_lock.close()
            raise
        self.lock = threading.RLock()
        self.process = None
        self.active = None
        self.log_handle = None
        # 重新打开界面不重新运行旧任务；曾中断的running记录明确改为stopped。
        for path in self.output.glob('*/trace.json'):
            if not ID_PATTERN.fullmatch(path.parent.name):
                continue
            try:
                trace = read_json(path)
                if trace.get('status') in ('queued', 'running'):
                    trace.update(status='stopped', error='上次终端会话已结束，未自动恢复或重开场景')
                    write_json(path, trace)
                self._metadata(trace)
            except (ValueError, OSError, KeyError):
                continue

    def folder(self, identity):
        if not isinstance(identity, str) or not ID_PATTERN.fullmatch(identity):
            raise ValueError('运行编号无效')
        path = (self.output / identity).resolve()
        if path.parent != self.output:
            raise ValueError('运行路径越界')
        return path

    def _metadata(self, trace):
        keys = ('id', 'problem', 'label', 'status', 'mode', 'created_at')
        write_json(self.folder(trace['id']) / 'meta.json', {k: trace.get(k) for k in keys})

    def get(self, identity):
        path = self.folder(identity) / 'trace.json'
        if not path.is_file():
            raise FileNotFoundError('找不到运行记录')
        return read_json(path)

    def start(self, value):
        request = validate_run(value, self.catalog)
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise BusyError('已有任务正在运行，请先等待完成或停止当前任务')
            try:
                probe = acquire_output_lock(self.output / '.gui.worker.lock',
                    '已有求解进程仍在运行，请等待其结束后再运行')
                probe.close()
            except ValueError as exc:
                raise BusyError(str(exc))
            identity = new_id()
            folder = self.folder(identity)
            folder.mkdir(exist_ok=False)
            trace = {'schema': 'modeling-gui-trace-v1', 'id': identity, 'label': request['label'],
                     'problem': request['problem'], 'mode': request['mode'], 'status': 'queued',
                     'created_at': datetime.datetime.now().astimezone().isoformat(),
                     'error': None, 'elapsed_s': 0, 'frames': [], 'truth': None, 'summary': {},
                     'output_directory': str(folder)}
            write_json(folder / 'trace.json', trace)
            self._metadata(trace)
            # 私有任务参数和原始actions不通过任何HTTP路径提供，身份不进入trace。
            request.update(id=identity, out_dir=str(folder), created_at=trace['created_at'], parent_pipe=True)
            write_json(folder / 'job.json', request)
            handle = (folder / 'worker.log').open('w', encoding='utf-8')
            try:
                process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8',
                    str(Path(__file__).with_name('问题三四_模拟与单局回放进程.py')), '--root', str(self.root),
                    '--request', str(folder / 'job.json')], cwd=str(self.root),
                    stdin=subprocess.PIPE, stdout=handle, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError as exc:
                handle.close()
                trace.update(status='failed', error='无法启动求解进程：' + type(exc).__name__)
                write_json(folder / 'trace.json', trace)
                write_json(folder / 'error.json', {'error': trace['error']})
                self._metadata(trace)
                raise ValueError(trace['error'])
            self.process, self.active, self.log_handle = process, identity, handle
            threading.Thread(target=self._watch, args=(identity, process, handle), daemon=True).start()
            return identity

    def _watch(self, identity, process, handle):
        code = process.wait()
        with self.lock:
            if process.stdin is not None:
                process.stdin.close()
            handle.close()
            trace = self.get(identity)
            if trace.get('status') not in FINAL_STATES:
                trace.update(status='failed', error='工作进程提前退出，退出码 ' + str(code))
                write_json(self.folder(identity) / 'trace.json', trace)
                write_json(self.folder(identity) / 'error.json', {'error': trace['error']})
            self._metadata(trace)
            if self.process is process:
                self.active, self.process, self.log_handle = None, None, None

    def stop(self, requested=None):
        with self.lock:
            if not isinstance(requested, str) or not ID_PATTERN.fullmatch(requested):
                raise ValueError('停止操作必须指定当前运行编号')
            if self.process is None or self.process.poll() is not None:
                raise ValueError('当前没有正在运行的任务')
            identity, process = self.active, self.process
            if requested is not None and requested != identity:
                raise ValueError('停止编号与当前任务不一致')
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            trace = self.get(identity)
            trace.update(status='stopped', error='已停止本地求解进程；场景可能未完成。未发送退出、重开或上传请求。')
            write_json(self.folder(identity) / 'trace.json', trace)
            write_json(self.folder(identity) / 'error.json', {'error': trace['error'], 'status': 'stopped'})
            self._metadata(trace)
            self.active = None
            return identity

class Server(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'ModelingLocalGUI/1.0'

    def log_message(self, fmt, *args):
        # 不把身份、请求体、会话token写到HTTP日志。
        return

    def respond(self, status, value, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def origin_ok(self):
        if self.headers.get('Host') != self.server.expected_host:
            return False
        origin = self.headers.get('Origin')
        return ((origin is None or origin == self.server.origin) and
                self.headers.get('Sec-Fetch-Site') not in ('cross-site',))

    def do_GET(self):
        if not self.origin_ok():
            self.respond(403, {'error': '仅允许从本机终端页面读取'})
            return
        path = urllib.parse.urlsplit(self.path).path
        manager = self.server.manager
        try:
            if path in ('/', '/问题三四_模拟终端界面.html'):
                template = self.server.asset_root / '问题三四_模拟终端界面.html'
                content = template.read_text(encoding='utf-8').replace('__GUI_TOKEN__', self.server.token)
                self.respond(200, content.encode('utf-8'), 'text/html; charset=utf-8')
            elif path == '/favicon.ico':
                self.respond(204, b'', 'image/x-icon')
            elif path == '/api/catalog':
                value = manager.catalog.public()
                value.update(active=manager.active, python=sys.version.split()[0])
                self.respond(200, value)
            elif path.startswith('/api/run/'):
                self.respond(200, manager.get(path[len('/api/run/'):]))
            else:
                self.respond(404, {'error': '没有该页面或接口'})
        except (ValueError, KeyError) as exc:
            self.respond(400, {'error': str(exc)})
        except FileNotFoundError:
            self.respond(404, {'error': '缺少页面、数据或运行记录，请确认支撑材料已完整解压'})
        except OSError:
            self.respond(500, {'error': '本地文件暂时无法读取'})

    def do_POST(self):
        if not self.origin_ok() or not hmac.compare_digest(self.headers.get('X-GUI-Token', '').encode('utf-8'), self.server.token.encode('utf-8')):
            self.respond(403, {'error': '请求来源或会话凭证无效，请从终端主页操作'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY or self.headers.get('Transfer-Encoding'):
                self.respond(413, {'error': 'JSON大小必须在32MB以内'})
                return
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                self.respond(415, {'error': '请发送application/json'})
                return
            self.connection.settimeout(10)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('请求体不完整')
            value = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('JSON不能包含非有限数值')))
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/run':
                identity = self.server.manager.start(value)
            elif path == '/api/stop':
                if not isinstance(value, dict):
                    raise ValueError('停止请求必须是对象')
                identity = self.server.manager.stop(value.get('id'))
            else:
                self.respond(404, {'error': '没有该操作接口'})
                return
            self.respond(200, {'id': identity})
        except BusyError as exc:
            self.respond(409, {'error': str(exc)})
        except (ValueError, UnicodeError, KeyError, TypeError, RecursionError) as exc:
            self.respond(400, {'error': '参数无效：' + str(exc)[:220]})
        except OSError:
            self.respond(500, {'error': '本地任务无法完成，请检查结果目录是否可写'})

    def do_OPTIONS(self):
        self.respond(403, {'error': '不接受跨域请求'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', '--data-root', dest='root', type=Path, default=ROOT,
                        help='完整支撑材料根目录，默认本文件目录')
    parser.add_argument('--results-dir', '--output-root', dest='output', type=Path,
                        help='日志目录，默认支撑根目录/运行结果/模拟器')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('端口必须为0至65535')
    manager = RunManager(args.root, args.output or args.root / '运行结果/模拟器')
    try:
        server = Server(('127.0.0.1', args.port), Handler)
    except OSError:
        if args.port == 0:
            raise
        server = Server(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    server.manager, server.token = manager, secrets.token_urlsafe(32)
    server.expected_host = '127.0.0.1:' + str(port)
    server.origin = 'http://' + server.expected_host
    server.asset_root = ROOT
    print(json.dumps({'url': server.origin, 'token': server.token, 'port': port, 'pid': os.getpid()}), flush=True)
    print('本地可视化终端已启动；关闭浏览器不会停止求解，停止请使用页面按钮。', flush=True)
    if not args.no_browser:
        import webbrowser
        webbrowser.open(server.origin)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        print('终端服务关闭；正在运行的子进程由本地停止操作终止，不发送官方退出请求。', flush=True)
    finally:
        if manager.process is not None and manager.process.poll() is None:
            manager.stop(manager.active)
        server.server_close()


if __name__ == '__main__':
    main()
