"""合成场景的本地模拟器，不模拟官方隐藏场景数据。"""
import copy
import hashlib
import json
import math
import random
import time

from 问题一_定位区域与包围圆 import distance, unit


def generate_case(seed, mode='mixed', kind='random'):
    rng = random.Random(seed)
    n = 16 if kind in ('boundary', 'cluster') else rng.randint(10, 16)
    channels = rng.sample(range(1, 21), n)
    sources = []
    for i, channel in enumerate(channels):
        a = 2*math.pi*i/n if kind == 'boundary' else rng.random()*2*math.pi
        r = 1800 if kind == 'boundary' else 1800*math.sqrt(rng.random())
        x, y = r*math.cos(a), r*math.sin(a)
        if kind == 'cluster':
            x, y = 299 + rng.uniform(-15, 15), -301 + rng.uniform(-15, 15)
        directional = mode == 'directional' or (mode == 'mixed' and i % 2 == 0)
        orientation = (math.degrees(a) if kind == 'boundary' else rng.uniform(0, 360)) if directional else None
        sources.append({'id': 'source-%02d' % i, 'channel': channel, 'x_m': x, 'y_m': y,
                        'reception_radius_m': 1000 if kind == 'boundary' else rng.uniform(1000, 1500),
                        'orientation_deg': orientation})
    return {'schema_version': 1, 'case_id': '%s-%s-%s' % (mode, kind, seed),
            'case_kind': 'full', 'seed': seed, 'sources': sources,
            'error_model': {'type': 'constant', 'value_deg': 1.0} if kind == 'boundary'
                           else {'type': 'smooth' if kind == 'cluster' else 'hash', 'seed': seed},
            'provenance': 'Synthetic engineering test, not official simulator distribution'}


def validate_case(case):
    sources = case['sources']
    if case.get('case_kind') not in ('unit', 'full'):
        raise ValueError('case_kind must be unit or full')
    if case['case_kind'] == 'full' and not 10 <= len(sources) <= 16:
        raise ValueError('Full scenes must have 10..16 sources')
    channels = set()
    for s in sources:
        ch = s['channel']
        if type(ch) is not int or not 1 <= ch <= 20 or ch in channels:
            raise ValueError('Source channels must be unique integers in 1..20')
        channels.add(ch)
        if not all(math.isfinite(s[key]) for key in ('x_m', 'y_m', 'reception_radius_m')):
            raise ValueError('Nonfinite source fields')
        if math.hypot(s['x_m'], s['y_m']) > 1800 + 1e-8 or not 1000 <= s['reception_radius_m'] <= 1500:
            raise ValueError('Source outside stated bounds')
        if s['orientation_deg'] is not None and not (math.isfinite(s['orientation_deg']) and 0 <= s['orientation_deg'] < 360):
            raise ValueError('Invalid source orientation')
    error = case.get('error_model', {'type': 'constant', 'value_deg': 0})
    if error['type'] not in ('constant', 'hash', 'smooth'):
        raise ValueError('Unsupported error model; use protocol fixtures for explicit response tables')
    if error['type'] == 'constant' and (not math.isfinite(error['value_deg']) or abs(error['value_deg']) > 1):
        raise ValueError('Error must be bounded by one degree')


class LocalSimulator:
    def __init__(self, case):
        validate_case(case)
        self.case = copy.deepcopy(case)
        self.sources = {s['channel']: s for s in self.case['sources']}
        self.cleared = set()
        self.position, self.channel = (0.0, 0.0), 1
        self.virtual_time = 0.0
        self.active, self.ended = False, False
        self.cache = {}
        self.deadline = None

    def error(self, channel, point):
        spec = self.case.get('error_model', {'type': 'constant', 'value_deg': 0})
        if spec['type'] == 'constant':
            return float(spec['value_deg'])
        if spec['type'] == 'smooth':
            return math.sin(point[0]/83 + point[1]/137 + channel + spec.get('seed', 0))
        # 数值相同的坐标使用同一键，包括正零与负零。
        key = [spec.get('seed', 0), channel] + [float(v) if v != 0 else 0.0 for v in point]
        n = int.from_bytes(hashlib.sha256(json.dumps(key).encode()).digest()[:8], 'big')
        return 2*n/(2**64-1)-1

    def reply(self, accepted=True, **fields):
        return dict(accepted=accepted, real_timestamp_ms=int(time.time()*1000),
                    virtual_time_s=self.virtual_time if accepted else 0, **fields)

    def send(self, endpoint, request, timeout=None):
        if endpoint not in ('/enter', '/measure', '/clear', '/exit'):
            return 404, self.reply(False)
        common = {'arena_id', 'robot_id', 'request_id'}
        required = common | ({'position', 'channel'} if endpoint in ('/measure', '/clear') else set())
        if not required.issubset(request):
            return 400, self.reply(False)
        if set(request) != required or request['arena_id'] != 'default' or request['robot_id'] != 'offline':
            return 200, self.reply(False)
        rid = request['request_id']
        if not isinstance(rid, str) or not 1 <= len(rid.encode()) <= 128:
            return 400, self.reply(False)
        if endpoint in ('/measure', '/clear'):
            p = request['position']
            if not isinstance(p, dict) or set(p) != {'x', 'y'}:
                return 200, self.reply(False)
            if any(isinstance(p[k], bool) or not isinstance(p[k], (int, float)) or
                   not math.isfinite(p[k]) or abs(p[k]) > 2000000 for k in ('x', 'y')):
                return 400, self.reply(False)
            ch = request['channel']
            if isinstance(ch, bool) or not isinstance(ch, (int, float)) or not 1 <= ch <= 20 or int(ch) != ch:
                return 400, self.reply(False)
        fingerprint = json.dumps([endpoint, request], sort_keys=True, allow_nan=False)
        if rid in self.cache:
            old, status, response = self.cache[rid]
            return (status, copy.deepcopy(response)) if old == fingerprint else (409, self.reply(False))
        if self.ended:
            raise ConnectionError('Local simulated session is closed')
        if endpoint == '/enter':
            if self.active:
                return 200, self.reply(False)
            self.active = True
            self.deadline = time.monotonic() + 1200
            response = self.reply(max_virtual_duration_s=360000, max_real_duration_s=1200,
                                  remaining_real_duration_s=1200)
        else:
            if not self.active:
                return 200, self.reply(False)
            if time.monotonic() >= self.deadline or self.virtual_time >= 360000:
                self.ended = True
                raise ConnectionError('Local simulated time limit reached')
            if endpoint == '/exit':
                self.active, self.ended = False, True
                response = self.reply(exit_reason='user_exit')
            else:
                point = (request['position']['x'], request['position']['y'])
                channel = int(request['channel'])
                self.virtual_time += distance(self.position, point)/5
                self.position = point
                source = self.sources.get(channel) if channel not in self.cleared else None
                dist = distance(point, (source['x_m'], source['y_m'])) if source else math.inf
                if endpoint == '/clear':
                    success = dist <= 20
                    self.virtual_time += 5 if success else 3
                    if success:
                        self.cleared.add(channel)
                    response = self.reply(clear_result='success' if success else 'no_target_in_range')
                else:
                    self.virtual_time += 5 + int(self.channel != channel)
                    self.channel = channel
                    visible = bool(source) and dist <= source['reception_radius_m']
                    if visible and source['orientation_deg'] is not None:
                        u = unit(source['orientation_deg'])
                        visible = (point[0]-source['x_m'])*u[0] + (point[1]-source['y_m'])*u[1] >= -1e-10
                    if not visible:
                        response = self.reply(measure_result='no_signal')
                    elif dist <= 5:
                        response = self.reply(measure_result='near')
                    else:
                        angle = math.degrees(math.atan2(source['y_m']-point[1], source['x_m']-point[0]))
                        angle = round((angle + self.error(channel, point)) % 360, 2) % 360
                        response = self.reply(measure_result='direction', svd_deg=angle)
        self.cache[rid] = fingerprint, 200, copy.deepcopy(response)
        return 200, response

    def evaluate(self):
        # 仅供外部实验评价器使用，不传入决策策略。
        return {'total_sources': len(self.sources), 'cleared_sources': len(self.cleared),
                'clearance_ratio': len(self.cleared)/len(self.sources) if self.sources else 1.0,
                'uncleared_channels': sorted(set(self.sources)-self.cleared)}
