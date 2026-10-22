"""独立核验完整接收范围证书，只读取动作与事件。
不导入求解器或几何模块，通过枚举多边形边的交点重建区域。"""
import math
from fractions import Fraction as Q

def rational(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('Nonfinite coordinate')
    return Q(v)
def point(p):
    if len(p)!=2:raise ValueError('Expected 2D point')
    return tuple(rational(v) for v in p)
def decode(v):
    if not isinstance(v,list) or len(v)!=2 or type(v[0]) is not int or type(v[1]) is not int or v[1]<=0:raise ValueError('Invalid fraction')
    return Q(*v)
def decoded_point(p):return tuple(decode(v) for v in p)
def cross(a,b):return a[0]*b[1]-a[1]*b[0]
def subtract(a,b):return tuple(x-y for x,y in zip(a,b))
def dist2(a,b):return sum((x-y)**2 for x,y in zip(a,b))

def intersection_vertices(poly,plane):
    a,b,c=plane
    sign=lambda p:a*p[0]+b*p[1]-c
    vertices={p for p in poly if sign(p)<=0}
    for i in range(len(poly)):
        p,q=poly[i-1],poly[i];sp,sq=sign(p),sign(q)
        if sp*sq<0:
            # 用端点的有符号距离计算两条直线的交点。
            den=abs(sp)+abs(sq)
            vertices.add(tuple((abs(sq)*p[k]+abs(sp)*q[k])/den for k in (0,1)))
    return vertices

def convex(poly):
    if not poly:return False
    signs=set()
    for p,q in zip(poly,poly[1:]+poly[:1]):
        for r in poly:
            s=cross(subtract(q,p),subtract(r,p))
            if s:signs.add(1 if s>0 else -1)
    return len(signs)<=1

def verify_certificate(certificate):
    errors=[]
    try:
        if certificate['schema']!='q3-first-positive-range-v1':errors.append('schema')
        poly=list(map(point,certificate['source_polygon']));o=point(certificate['origin']);q=point(certificate['point'])
        if not convex(poly):errors.append('nonconvex_or_empty_source_polygon')
        margin=rational(certificate['margin_m'])
        if not 0<margin<1:errors.append('margin')
        plane=tuple(decode(v) for v in certificate['farther_plane'])
        expected=(2*(q[0]-o[0]),2*(q[1]-o[1]),q[0]**2+q[1]**2-o[0]**2-o[1]**2)
        if plane!=expected:errors.append('wrong_distance_comparison_halfplane')
        vertices=intersection_vertices(poly,expected)
        if vertices!={decoded_point(p) for p in certificate['farther_cap']}:errors.append('missing_or_extra_cap_vertices')
        maximum=max((dist2(q,p) for p in vertices),default=Q(0))
        if maximum!=decode(certificate['max_farther_distance_sq']):errors.append('wrong_maximum')
        if maximum>(1000-margin)**2:errors.append('range_guarantee_failed')
        return dict(passed=not errors,errors=errors,cap_vertices=len(vertices))
    except Exception as exc:return dict(passed=False,errors=errors+[type(exc).__name__+': '+str(exc)],cap_vertices=0)

def verify_rays(event):
    errors=[]
    try:
        c=event['ray_certificate'];g=event['pair_geometry']
        if c is None:return dict(passed=event['mode']=='old',errors=[] if event['mode']=='old' else ['missing_expanded_ray_certificate'],cap_vertices=0)
        if g['origin']!=event['first_positive']['position'] or g['bearing_deg']!=event['first_positive']['bearing_deg']:errors.append('ray_origin_or_bearing')
        o=point(g['origin']);a=math.radians(g['bearing_deg']);u=point((math.cos(a),math.sin(a)))
        expected=(-u[0],-u[1],-u[0]*o[0]-u[1]*o[1]-rational(g['forward_m']))
        if tuple(decode(x) for x in c['far_plane'])!=expected:errors.append('ray_far_plane')
        poly=list(map(point,event['source_polygon_before']));vertices=intersection_vertices(poly,expected)
        if vertices!={decoded_point(p) for p in c['far_cap']}:errors.append('ray_cap_vertices')
        probes=list(map(point,c['ordered_points']))
        if len(probes)!=2 or set(probes)!=set(map(point,g['points'])):errors.append('ray_points')
        elif cross(subtract(probes[0],o),subtract(probes[1],o))<=0:errors.append('ray_orientation')
        else:
            rays=[subtract(p,o) for p in probes]
            if any(cross(rays[0],subtract(x,o))<0 or cross(subtract(x,o),rays[1])<0 for x in vertices):errors.append('ray_not_bracketed')
        if point(event['position']) not in probes:errors.append('executed_point_not_in_pair')
        return dict(passed=not errors,errors=errors,cap_vertices=len(vertices))
    except Exception as exc:return dict(passed=False,errors=errors+[type(exc).__name__+': '+str(exc)],cap_vertices=0)

def audit(records,solution):
    errors=[];actions=[];seen=set()
    for row in records:
        if row.get('http_status')!=200 or not row.get('response',{}).get('accepted'):continue
        identity=row.get('request_id',row.get('request',{}).get('request_id'))
        if identity in seen:continue
        seen.add(identity)
        if row['endpoint'] not in ('/measure','/clear'):continue
        req=row['request'];p=(req['position']['x'],req['position']['y'])
        actions.append((row['endpoint'],req['channel'],p,row['response']))
    if not isinstance(solution,dict):return dict(passed=False,errors=['missing_solution'],range_probe_events=0)
    first={};prior={};measured={};positives={};used=set();index=0;pending=None
    event_count=cap_count=ray_count=positive_count=expanded_count=0
    def error(message,ei):errors.append(dict(event_index=ei,error=message))
    for ei,e in enumerate(solution.get('events',[])):
        ch=e.get('channel');method=e.get('method')
        if method=='q3_full_range_probe':
            event_count+=1
            if pending is not None:error('new_probe_before_previous_action',ei)
            if ch in used:error('more_than_one_probe_per_channel',ei)
            used.add(ch)
            if positives.get(ch,0)!=1:error('not_exactly_one_positive_before_probe',ei)
            if e.get('measure_index_before')!=measured.get(ch,0):error('measure_index',ei)
            if first.get(ch)!=e.get('first_positive'):error('first_positive_not_from_actual_response',ei)
            if prior.get(ch)!=tuple(map(point,e.get('source_polygon_before',[]))):error('polygon_not_actual_pre_action_polygon',ei)
            c=e.get('certificate',{})
            if (c.get('source_polygon')!=e.get('source_polygon_before') or c.get('origin')!=e.get('first_positive',{}).get('position') or c.get('point')!=e.get('position')):error('certificate_inputs_not_event_inputs',ei)
            checked=verify_certificate(c);cap_count+=checked['cap_vertices']
            for issue in checked['errors']:error(issue,ei)
            checked=verify_rays(e);ray_count+=checked['cap_vertices']
            for issue in checked['errors']:error(issue,ei)
            if e.get('mode')=='expanded':expanded_count+=1
            pending=(ch,tuple(e['position']))
        action_event=method=='observe' or (type(e.get('success')) is bool and 'position' in e)
        if action_event:
            if index>=len(actions):error('extra_action_event',ei);continue
            endpoint,actual_ch,p,response=actions[index];index+=1
            expected_endpoint='/measure' if method=='observe' else '/clear'
            if (endpoint,actual_ch,p)!=(expected_endpoint,ch,tuple(e['position'])):error('action_event_does_not_match_record',ei)
            if pending is not None:
                if (endpoint,actual_ch,p)!=('/measure',pending[0],pending[1]):error('certificate_not_immediately_followed_by_its_probe',ei)
                elif response.get('measure_result') not in ('direction','near'):error('guaranteed_probe_not_positive',ei)
                else:positive_count+=1
                pending=None
            if endpoint=='/measure':
                measured[ch]=measured.get(ch,0)+1
                if response.get('measure_result')!='no_signal':
                    positives[ch]=positives.get(ch,0)+1
                if response.get('measure_result')=='direction' and ch not in first:
                    first[ch]=dict(position=list(p),bearing_deg=response['svd_deg'])
        if e.get('poly') and ch is not None:prior[ch]=tuple(map(point,e['poly']))
    if pending is not None:errors.append(dict(error='unexecuted_probe_certificate'))
    if index!=len(actions):errors.append(dict(error='unmatched_physical_actions'))
    return dict(passed=not errors,errors=errors,range_probe_events=event_count,
        expanded_probe_events=expanded_count,exact_cap_vertex_checks=cap_count,
        exact_ray_vertex_checks=ray_count,observed_positive_probes=positive_count,
        action_records_checked=len(actions),scope='Range/ray certificates and physical-history links; no source truth used')
