"""独立重算动作费用，沿用已核验计时规则。
不导入策略、几何、传输或模拟器。拒绝动作不计费；未确认尝试须以完全相同请求得到确认。官方时钟按整数微秒处理，单次移动量化误差按一个时钟单位界定，不调大整体容差。"""
import json
import math
from decimal import Decimal
from pathlib import Path


def read_records(path):
    path = Path(path)
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    return json.loads(path.read_text(encoding='utf-8-sig'))


def signature(record):
    return json.dumps([record.get('endpoint'), record.get('request', {})], sort_keys=True, separators=(',', ':'))


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def recompute(records, clock_model='float', require_closed=False, require_http=False):
    if clock_model not in ('float', 'microsecond'):
        raise ValueError('Unknown clock model')
    position, channel = (0., 0.), 1
    entered, closed = False, False
    committed, pending = {}, {}
    anomalies, gaps = [], []
    costs = dict(movement_s=0., channel_switch_s=0., measure_s=0., optical_location_s=0., laser_clear_s=0.)
    counts = dict(logical_accepted_actions=0, rejected_records=0, ignored_idempotent_retries=0,
                  unconfirmed_attempts=0, resolved_unconfirmed_ids=0, positive_moves=0)
    ideal, last_observed, nearest_us = 0., None, 0
    max_step_residual, max_total_residual, floating_budget = 0., 0., 0.
    quantum = 1e-6 if clock_model == 'microsecond' else 0.
    per_action = []

    def problem(index, kind, **details):
        anomalies.append(dict(record=index, kind=kind, **details))

    for index, record in enumerate(records, 1):
        rid = record.get('request_id')
        endpoint, request, response = record.get('endpoint'), record.get('request', {}), record.get('response', {})
        if not isinstance(rid, str) or not rid:
            problem(index, 'missing_request_id')
            continue
        if not isinstance(request, dict) or not isinstance(response, dict):
            problem(index, 'invalid_record_object')
            continue
        if 'request_id' in request and request['request_id'] != rid:
            problem(index, 'request_id_log_mismatch')
        sig = signature(record)
        accepted, http = response.get('accepted'), record.get('http_status')
        if require_http and http is None:
            gaps.append(dict(record=index, kind='missing_http_status'))
        if accepted is False:
            counts['rejected_records'] += 1
            # 拒绝请求不引发移动、换频或占用编号；先前丢失的
            # 响应不能由另一个不同请求被拒绝而视作已解决。
            continue
        if accepted is not True or (http is not None and http != 200):
            counts['unconfirmed_attempts'] += 1
            if accepted is True:
                problem(index, 'accepted_with_non200_http')
            if rid in committed:
                if sig != committed[rid]['signature']:
                    problem(index, 'committed_id_payload_conflict')
            elif rid in pending and pending[rid] != sig:
                problem(index, 'unconfirmed_id_payload_conflict')
            else:
                pending[rid] = sig
            continue
        if rid in committed:
            first = committed[rid]
            counts['ignored_idempotent_retries'] += 1
            if sig != first['signature']:
                problem(index, 'accepted_id_payload_conflict')
            if response != first['response']:
                problem(index, 'retry_response_changed')
            continue
        if rid in pending:
            if pending[rid] != sig:
                problem(index, 'unconfirmed_id_payload_conflict')
            del pending[rid]
            counts['resolved_unconfirmed_ids'] += 1
        if pending:
            problem(index, 'new_action_before_unconfirmed_resolution', pending_ids=sorted(pending))
        committed[rid] = dict(signature=sig, response=response)
        counts['logical_accepted_actions'] += 1
        movement, fixed = 0., 0.
        if endpoint == '/enter':
            if entered:
                problem(index, 'duplicate_enter')
            entered = True
        elif endpoint in ('/measure', '/clear'):
            if not entered or closed:
                problem(index, 'action_outside_active_session')
            try:
                new_position = (request['position']['x'], request['position']['y'])
                requested_channel = request['channel']
                if not all(finite_number(v) for v in new_position) or type(requested_channel) is not int or not 1 <= requested_channel <= 20:
                    raise ValueError('Invalid coordinates/channel')
            except (KeyError, TypeError, ValueError) as exc:
                problem(index, 'invalid_action_payload', detail=str(exc))
                continue
            movement = math.dist(position, new_position)/5.
            counts['positive_moves'] += movement > 0
            costs['movement_s'] += movement
            position = new_position
            if endpoint == '/measure':
                switch = int(channel != requested_channel)
                costs['channel_switch_s'] += switch
                costs['measure_s'] += 5
                channel, fixed = requested_channel, 5 + switch
            else:
                result = response.get('clear_result')
                if result not in ('success', 'no_target_in_range'):
                    problem(index, 'invalid_clear_result')
                success = result == 'success'
                costs['optical_location_s'] += 3
                costs['laser_clear_s'] += 2*success
                fixed = 3 + 2*success
        elif endpoint == '/exit':
            if not entered or closed:
                problem(index, 'exit_outside_active_session')
            closed = True
        else:
            problem(index, 'unknown_endpoint')
        increment = movement + fixed
        ideal += increment
        nearest_us += round(movement*1e6) + round(fixed*1e6)
        # 浮点运算余量与物理时钟量化单位分别处理。
        fp = 64*math.ulp(max(1., abs(ideal), abs(increment)))
        floating_budget += fp
        step_bound = quantum*int(movement > 0) + fp
        total_bound = quantum*counts['positive_moves'] + floating_budget
        observed = response.get('virtual_time_s')
        if not finite_number(observed) or observed < 0:
            gaps.append(dict(record=index, kind='invalid_or_missing_clock'))
            last_observed = None
            continue
        if clock_model == 'microsecond' and Decimal(str(observed))*1000000 != (Decimal(str(observed))*1000000).to_integral_value():
            problem(index, 'non_microsecond_clock')
        total_residual = observed - ideal
        max_total_residual = max(max_total_residual, abs(total_residual))
        if abs(total_residual) > total_bound:
            problem(index, 'cumulative_clock_mismatch', residual_s=total_residual, bound_s=total_bound)
        step_residual = None
        if last_observed is not None:
            observed_increment = float(Decimal(str(observed))-Decimal(str(last_observed)))
            step_residual = observed_increment - increment
            max_step_residual = max(max_step_residual, abs(step_residual))
            if abs(step_residual) > step_bound:
                problem(index, 'step_clock_mismatch', residual_s=step_residual, bound_s=step_bound)
        last_observed = observed
        per_action.append(dict(record=index, endpoint=endpoint, ideal_increment_s=increment,
            step_residual_s=step_residual, step_bound_s=step_bound, cumulative_residual_s=total_residual,
            cumulative_bound_s=total_bound))
    if not entered:
        gaps.append(dict(kind='missing_enter'))
    if require_closed and not closed:
        gaps.append(dict(kind='missing_exit'))
    if pending:
        gaps.append(dict(kind='unresolved_requests', ids=sorted(pending)))
    status = 'failed' if anomalies else 'insufficient_evidence' if gaps else 'passed'
    return dict(method='A_R1_adapted_independent_state_replay_v2', clock_model=clock_model,
        status=status, passed=status == 'passed', **counts, components=costs,
        recomputed_virtual_time_s=ideal, final_observed_time_s=last_observed,
        final_position=dict(x=position[0], y=position[1]), final_measure_channel=channel,
        final_cumulative_bound_s=quantum*counts['positive_moves']+floating_budget,
        max_step_residual_s=max_step_residual, max_cumulative_residual_s=max_total_residual,
        nearest_microsecond_candidate_s=nearest_us/1e6,
        nearest_candidate_residual_s=None if last_observed is None else nearest_us/1e6-last_observed,
        entered=entered, closed=closed, anomalies=anomalies, evidence_gaps=gaps, actions=per_action)
