import csv,hashlib,json
from pathlib import Path
BASE=Path(__file__).resolve().parent.parent
plans={'q3':('run_20261005_174649_576453fe5969',[3,23,42,43,44,45,46,47,131]),
       'q4':('run_20261005_174658_cf0598e842c8',[263,287,288,289,290,301,323])}
rows=[];summaries={}
for q,(identity,anchors) in plans.items():
    trace=json.loads((BASE/'演示运行'/identity/'trace.json').read_text(encoding='utf-8'))
    summaries[q]=dict(run_id=identity,**trace['summary'])
    for index in anchors:
        frame=trace['frames'][index-1]
        track=next((t for t in frame['tracks'] if t['channel']==frame['channel']),None)
        rows.append(dict(problem=q,action_number=index,frame_index=index-1,channel=frame['channel'],
            action=frame['action'],result=frame['result'],virtual_time_s=frame['time_s'],
            radius_m=track['circle']['radius_m'] if track and track.get('circle') else '',
            model_events=';'.join(frame.get('model_events',[])),explanation=frame['explanation']))
with (BASE/'演示运行'/'动作锚点.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
(BASE/'演示运行'/'两局演示摘要.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
screens=BASE/'制作源文件'/'演示截图'
manifest={p.name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in screens.glob('*.jpg')}
(screens/'截图清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summaries,ensure_ascii=False,indent=2))
