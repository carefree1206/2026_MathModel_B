"""串行协议客户端，只有显式发送动作时才访问网络。"""
import http.client
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from 问题一_定位区域与包围圆 import distance


class ProtocolError(RuntimeError):
    pass


class ExecutionLimit(RuntimeError):
    pass


class HttpTransport:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Official adapter only supports an explicit local HTTP origin')
        self.url = url.rstrip('/')
        # 本机接口直连，不经过系统或用户代理。
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def send(self, endpoint, request, timeout=5):
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf-8')
        req = urllib.request.Request(self.url + endpoint, data=payload,
                                     headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode('utf-8', errors='replace')
            try:
                data = json.loads(raw)
            except ValueError:
                raise ProtocolError('HTTP %s returned non-JSON: %s' % (exc.code, raw[:200]))
            return exc.code, data


class Session:
    """向策略仅暴露实际观测和自身已知状态。"""
    def __init__(self, transport, robot_id, run_id, config, log=None):
        self._transport = transport
        self.robot_id, self.run_id, self.config = robot_id, run_id, config
        self.log = log
        self.position, self.channel, self.virtual_time = (0.0, 0.0), 1, 0.0
        self.seq, self.entered, self.closed = 0, False, False
        self.deadline = None
        self.max_virtual = 360000
        self.records = []
        self.costs = dict(move_m=0.0, move_s=0.0, measure_s=0, switch_s=0,
                          optical_s=0, laser_s=0, measures=0, clears=0, successes=0)

    def remaining(self):
        return max(0.0, self.deadline-time.monotonic()) if self.deadline is not None else math.inf

    def write(self, row):
        self.records.append(row)
        if self.log:
            self.log.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
            self.log.flush()

    def act(self, endpoint, position=None, channel=None):
        if self.closed or (endpoint != '/enter' and not self.entered):
            raise ProtocolError('Invalid local session lifecycle')
        if self.entered and endpoint == '/enter':
            raise ProtocolError('Session already entered; no automatic new test')
        if endpoint != '/exit' and self.remaining() <= self.config['exit_reserve_s']:
            raise ExecutionLimit('Real-time exit reserve reached')
        if position is not None:
            if any(not math.isfinite(v) or abs(v) > 2000000 for v in position):
                raise ValueError('Invalid coordinates')
            if type(channel) is not int or not 1 <= channel <= 20:
                raise ValueError('Invalid channel')
            if self.virtual_time + distance(self.position, position)/5 + 6 >= self.max_virtual:
                raise ExecutionLimit('Virtual-time limit would be reached')
        self.seq += 1
        req = {'arena_id': 'default', 'robot_id': self.robot_id,
               'request_id': '%s-%s' % (self.run_id, self.seq)}
        if position is not None:
            req.update(position={'x': float(position[0]), 'y': float(position[1])}, channel=channel)
        logical_start = time.monotonic()
        for attempt in range(self.config['transport_retries'] + 1):
            if self.remaining() <= 0:
                raise ExecutionLimit('Session real deadline reached')
            row = {'run_id': self.run_id, 'seq': self.seq, 'attempt': attempt + 1,
                   'request_id': req['request_id'], 'endpoint': endpoint, 'request': req}
            try:
                status, response = self._transport.send(endpoint, req,
                    timeout=min(self.config['transport_timeout_s'], self.remaining()))
            except KeyboardInterrupt:
                row.update(transport_error='Interrupted; action acceptance is unknown')
                self.write(row)
                raise
            except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
                row.update(transport_error=type(exc).__name__ + ': ' + str(exc))
                self.write(row)
                if attempt == self.config['transport_retries']:
                    raise ProtocolError('Unresolved transport error; no new action was sent') from exc
                # 重试保留完全相同的内容和请求编号，兼容响应丢失但动作已执行。
                continue
            row.update(http_status=status, response=response,
                       accepted=response.get('accepted') if isinstance(response, dict) else None)
            self.write(row)
            if status != 200 or not isinstance(response, dict) or response.get('accepted') is not True:
                raise ProtocolError('Request rejected (HTTP %s); previous state retained' % status)
            clock = response.get('virtual_time_s')
            if isinstance(clock, bool) or not isinstance(clock, (int, float)) or not math.isfinite(clock) or clock < self.virtual_time - 1e-5:
                raise ProtocolError('Invalid or regressing virtual time')
            expected = self.virtual_time
            if endpoint == '/enter':
                remaining = response.get('remaining_real_duration_s')
                if not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or not 0 <= remaining <= 1200:
                    raise ProtocolError('Invalid remaining_real_duration_s')
                self.deadline = logical_start + remaining
                self.max_virtual = response.get('max_virtual_duration_s', 360000)
                self.entered = True
            elif endpoint == '/exit':
                self.closed = True
            else:
                move = distance(self.position, position)
                expected += move / 5
                if endpoint == '/measure':
                    result = response.get('measure_result')
                    if result not in ('direction', 'near', 'no_signal'):
                        raise ProtocolError('Unknown measure_result')
                    if result == 'direction':
                        angle = response.get('svd_deg')
                        if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle) or not 0 <= angle < 360:
                            raise ProtocolError('Invalid direction reading')
                    switch = int(channel != self.channel)
                    expected += 5 + switch
                    self.costs['measure_s'] += 5
                    self.costs['switch_s'] += switch
                    self.costs['measures'] += 1
                    self.channel = channel
                else:
                    result = response.get('clear_result')
                    if result not in ('success', 'no_target_in_range'):
                        raise ProtocolError('Unknown clear_result')
                    success = int(result == 'success')
                    expected += 3 + 2*success
                    self.costs['optical_s'] += 3
                    self.costs['laser_s'] += 2*success
                    self.costs['clears'] += 1
                    self.costs['successes'] += success
                self.position = tuple(position)
                self.costs['move_m'] += move
                self.costs['move_s'] += move/5
            self.virtual_time = clock
            if abs(expected-clock) > 0.05:
                raise ProtocolError('Clock mismatch: local %.6f, returned %.6f' % (expected, clock))
            return response

    def enter(self):
        return self.act('/enter')

    def measure(self, p, channel):
        return self.act('/measure', p, channel)

    def clear(self, p, channel):
        return self.act('/clear', p, channel)

    def exit(self):
        return self.act('/exit')
