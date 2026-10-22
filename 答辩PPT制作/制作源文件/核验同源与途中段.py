"""Inspect existing single-run records only; do not execute any solver."""
import json, math
from pathlib import Path
BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'演示运行'
def read(name,filename):return json.loads((OUT/name/filename).read_text(encoding='utf-8'))
q3=read('run_20261005_174649_576453fe5969','trace.json')
q4=read('run_20261005_174658_cf0598e842c8','trace.json')
solution=read('run_20261005_174658_cf0598e842c8','solution.json')
def select(frame):
    track=next((t for t in frame['tracks'] if t['channel']==frame['channel']),None)
    return dict(action_number=frame['index']+1,frame_index=frame['index'],channel=frame['channel'],
       action=frame['action'],result=frame['result'],position=frame['position'],time_s=frame['time_s'],
       radius_m=track['circle']['radius_m'] if track and track.get('circle') else None,
       events=frame.get('model_events',[]),explanation=frame['explanation'])
chain=[select(q3['frames'][i-1]) for i in (42,43,44,45)]
assert all(r['channel']==8 for r in chain)
assert [r['result'] for r in chain]==['direction','no_target_in_range','direction','success']
frames=[select(q4['frames'][i-1]) for i in (287,288,289,290)]
segments=[]
for i in (288,289):
    frame=q4['frames'][i-1]
    event=next(e for e in solution['events'] if e.get('method')=='enroute_measure_choice'
               and e['channel']==frame['channel'] and math.dist(e['position'],frame['position'])<1e-9)
    start,event_point,end=event['start'],event['position'],event['planned_endpoint']
    interpolation=[start[k]+event['interpolation_fraction']*(end[k]-start[k]) for k in (0,1)]
    extra_length=math.dist(start,event_point)+math.dist(event_point,end)-math.dist(start,end)
    assert math.dist(interpolation,event_point)<1e-8 and abs(extra_length)<1e-8
    assert event['planned_next']==['scan',19]
    segments.append(dict(action_number=i,original_event=event,
       actual_previous_position=q4['frames'][i-2]['position'],actual_position=frame['position'],
       original_planned_endpoint=end,interpolation_residual_m=math.dist(interpolation,event_point),
       segment_extra_distance_m=extra_length,meaning='途中插入检测；原计划为scan 19，非该巡检端点首任务补测'))
result=dict(q3_same_source_failure_chain=chain,
    q3_scope='第45动作成功时半径24.887m仍高于19.99m，属于可失败试探，不是保证清除证据；46/47为另一频道1。',
    q4_segment_frames=frames,q4_verified_insertions=segments,
    q4_scope='对所记录计划线段为零几何绕行，不保证总费用下降，也不推断后续最优路线。',
    execution='read_only_existing_records_no_new_solver_run')
(OUT/'同源失败后续与途中段核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
