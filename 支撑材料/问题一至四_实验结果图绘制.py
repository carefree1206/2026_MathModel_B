"""依据同场记录和实际响应重建论文图形；所有示意图显式区分实测。"""
from pathlib import Path
import gzip,json,math

def render(data_dir,output,names=None):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle,Polygon,FancyBboxPatch
    from matplotlib import font_manager
    from 问题一至四_几何示意图绘制 import render as geometry, restore_final_figures, FIGURE_FILENAMES
    data_dir=Path(data_dir);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if names is None:
        geometry(data_dir,output)
    e=json.loads((data_dir/'paper_evidence.json').read_text(encoding='utf-8'))
    available={f.name for f in font_manager.fontManager.ttflist}
    font=next((x for x in ['Microsoft YaHei','SimHei','Noto Sans CJK SC'] if x in available),'DejaVu Sans')
    plt.rcParams.update({'font.family':font,'font.size':9,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False,
        'savefig.dpi':230,'figure.facecolor':'white','svg.fonttype':'none','axes.edgecolor':'#9BA4AE'})
    colors={'m019':'#929BA5','m020':'#257C83','m021':'#B16D41'}
    labels={'m019':'共同基线','m020':'局部费用','m021':'选择性信息'}
    # 颜色始终对应策略；多策略曲线另加线型，便于黑白打印时辨认。
    styles={'m019':':','m020':'-','m021':'--'}
    markers={'m019':'s','m020':'o','m021':'^'}
    # 费用增减与动作成败采用独立配色，避免被误认为另一策略。
    extra_color, saved_color = '#A35C71', '#607E9B'
    navy='#284E69';gray='#B2BDC6'
    def save(fig,name):
        if names is not None and name not in names:
            plt.close(fig)
            return
        name = FIGURE_FILENAMES[name]
        fig.savefig(output/(name+'.png'),bbox_inches='tight',facecolor='white')
        fig.savefig(output/(name+'.svg'),bbox_inches='tight',facecolor='white');plt.close(fig)
    def note(fig,text):fig.text(.5,-.02,text,ha='center',fontsize=7.6,color='#66717D')
    def part(q,panel='fresh_confirmation',v=None):
        return [r for r in e['benchmark_rows'] if r['problem']==q and r['panel']==panel and (v is None or r['variant']==v)]
    def paired(rows,v):
        b={r['case_id']:r for r in rows if r['variant']=='m019'}
        c={r['case_id']:r for r in rows if r['variant']==v};assert set(b)==set(c)
        ids=sorted(b);return ids,np.array([b[k]['per_source_s'] for k in ids]),np.array([c[k]['per_source_s'] for k in ids])
    costs=['move_s','measure_s','switch_s','optical_s','laser_s']
    costnames=['移动','测量','换频','光学','激光']
    costcolors=['#284E69','#4C8992','#AFBDC6','#C78E63','#E1C3A7']

    # 双侧候选和光学点只解释决策结构，不把画出的权重当作真实源。
    fig,axes=plt.subplots(1,2,figsize=(7.3,3.4),constrained_layout=True)
    poly=np.array([[430,-18],[1200,-38],[1350,26],[650,20]])
    axes[0].add_patch(Polygon(poly,fc='#E2EFF0',ec=navy))
    axes[0].scatter(0,0,c=navy,s=28);axes[0].annotate('首测点',(0,0),(40,130),arrowprops={'arrowstyle':'-','color':gray})
    for x in [610,880,1100]:
        axes[0].plot([x,x],[-180,180],color=gray,ls='--',lw=.8)
        axes[0].scatter([x,x],[-180,180],c=colors['m020'],s=24)
    axes[0].text(875,80,'几何检验后才评分',ha='center',fontsize=8)
    axes[0].set(xlabel='首测示向轴 / m',ylabel='侧向 / m',xlim=(-50,1450),ylim=(-300,300),aspect='equal')
    axes[0].set_title('安全双侧候选的费用比较',fontsize=10)
    pts=np.array([[-18,-6],[-11,5],[-7,-5],[3,2],[12,8],[20,-8],[27,4]])
    w=np.array([.03,.06,.10,.18,.28,.23,.12])
    axes[1].scatter(pts[:,0],pts[:,1],s=500*w+15,c=colors['m020'],alpha=.7)
    axes[1].add_patch(Circle((10,0),20,fill=False,ec=navy));axes[1].scatter(10,0,marker='+',c=navy,s=70)
    axes[1].text(10,24,'试清位置及20米光学圆',ha='center',fontsize=8)
    axes[1].set(xlabel='局部横坐标 / m',ylabel='局部纵坐标 / m',xlim=(-34,44),ylim=(-29,31),aspect='equal')
    axes[1].set_title('参考权重只用于试清位置排名',fontsize=10)
    note(fig,'机制示意；点大小表示示意权重。候选样本不替代连续可行域，失败仍须回退并完整计费。')
    save(fig,'fig18_q3_cost_candidates')

    fig,ax=plt.subplots(figsize=(7.3,2.7),constrained_layout=True)
    start=(0,0);stop=(1100,0);probe=(510,0);known=(750,500)
    ax.plot([0,1100],[0,0],color=navy,lw=2);ax.scatter([0,510,1100],[0,0,0],color=[navy,colors['m021'],navy],s=45)
    ax.add_patch(Polygon([[620,430],[900,440],[870,570],[620,560]],fc='#F3E7DA',ec=colors['m021']))
    ax.plot([probe[0],known[0]],[probe[1],known[1]],color=colors['m021'],ls='--')
    for xy,label,offset in [(start,'当前位置',(-40,-100)),(probe,'候选停车测点',(0,-100)),(stop,'当次名义目的地',(0,-100)),(known,'其他已知源的\n定位区域',(350,45))]:
        ax.text(xy[0]+offset[0],xy[1]+offset[1],label,ha='center',fontsize=9)
    ax.text(120,480,'预计半径收益 ≥ 120 m\n每频道至多 2 次\n无信号也消耗次数',fontsize=9,linespacing=1.7)
    ax.set(xlim=(-140,1320),ylim=(-160,720),aspect='equal',xlabel='局部横坐标 / m',ylabel='局部纵坐标 / m')
    note(fig,'机制示意；实际停车后才取得信息，至少支付5秒检测及可能的1秒换频，后续路线按真实反馈更新。')
    save(fig,'fig19_q4_transit_information')

    # 每轮只有一个动作执行节点；终止检查在状态更新之后、选动作之前。
    fig,ax=plt.subplots(figsize=(7.3,3.18))
    fig.subplots_adjust(left=.008,right=.992,bottom=.025,top=.985)
    ax.set(xlim=(0,12.5),ylim=(0,5.45));ax.axis('off')
    edge,arrow,fill,green='#2C5E79','#92A6B4','#F0F7FA','#568578'
    def box(x,y,w,h,text,color=edge,face=fill,fontsize=11):
        ax.add_patch(FancyBboxPatch((x-w/2,y-h/2),w,h,boxstyle='round,pad=.025,rounding_size=.075',ec=color,fc=face,lw=1.6))
        ax.text(x,y,text,ha='center',va='center',fontsize=fontsize,color='#2E4351',linespacing=1.55)
    def arrow_to(a,b,color=arrow):
        ax.annotate('',b,a,arrowprops={'arrowstyle':'-|>','color':color,'lw':1.5,'shrinkA':0,'shrinkB':0})
    box(1.65,4.22,2.72,1.16,'初始化及原点扫描\n建立逐频道检测历史')
    box(5.28,4.22,3.10,1.16,'更新保守位置集合\n与合法覆盖证据')
    # 菱形中的括号明确“且”与“或”的作用范围。
    diamond=[(9.60,5.30),(12.10,4.22),(9.60,3.14),(7.10,4.22)]
    ax.add_patch(Polygon(diamond,closed=True,ec=edge,fc=fill,lw=1.6))
    ax.text(9.60,4.22,'终止条件满足？\n已知源全部清除，且\n（已发现16源，或所有未知\n频道均完成覆盖确认）',ha='center',va='center',fontsize=9.6,color='#2E4351',linespacing=1.18)
    box(9.60,1.32,3.50,1.16,'评估合格候选\n并选择下一动作')
    box(5.28,1.32,3.55,1.16,'执行一次动作\n记录真实反馈与费用')
    box(1.65,1.32,2.72,1.16,'主动退出',color=green,face='#EDF5F1',fontsize=12)
    arrow_to((3.035,4.22),(3.705,4.22))
    arrow_to((6.855,4.22),(7.10,4.22))
    arrow_to((9.60,3.14),(9.60,1.925))
    ax.text(9.77,2.51,'否',ha='left',va='center',fontsize=10,color=arrow)
    arrow_to((7.825,1.32),(7.08,1.32))
    arrow_to((5.28,1.925),(5.28,3.615))
    ax.text(5.49,2.78,'返回更新状态',ha='left',va='center',fontsize=9.3,color=arrow)
    # 满足终止条件的分支从图框外侧到达退出节点，避开反馈循环。
    ax.plot([12.10,12.34,12.34,1.65],[4.22,4.22,.28,.28],color=green,lw=1.5)
    arrow_to((1.65,.28),(1.65,.715),green)
    ax.text(11.83,.50,'是：满足终止条件',ha='right',va='center',fontsize=8.7,color=green)
    save(fig,'fig05_strategy_flow')

    fig,axes=plt.subplots(1,2,figsize=(7.3,3.35),constrained_layout=True)
    for ax,panel,title in zip(axes,['existing_panel','fresh_confirmation'],['开发对照84场','独立确认84场']):
        rows=part('q3',panel)
        for v in ['m020','m021']:
            _,b,c=paired(rows,v);ax.scatter(b,c,s=13,alpha=.7,color=colors[v],marker=markers[v],label=labels[v])
        lo=min(r['per_source_s'] for r in rows)-8;hi=max(r['per_source_s'] for r in rows)+8
        ax.plot([lo,hi],[lo,hi],color=gray,lw=1);ax.set(xlim=(lo,hi),ylim=(lo,hi),xlabel='共同基线 / s/源',ylabel='比较策略 / s/源',title=title)
        ax.legend(frameon=False,fontsize=8)
    note(fig,'每点为同一世界的两策略配对；对角线下方为更快。Q3最终采用局部费用策略。')
    save(fig,'fig11_q3_paired')

    stress=[r for r in e['stress_rows'] if r['problem']=='q3']
    fig,axes=plt.subplots(1,2,figsize=(7.3,3.25),constrained_layout=True)
    for v in ['m020','m021']:
        ids,b,c=paired(stress,v);change=100*(c/b-1);axes[0].plot(np.sort(change),label=labels[v],color=colors[v],ls=styles[v])
    axes[0].axhline(0,color=gray,lw=1);axes[0].set(xlabel='各策略独立排序的压力场景',ylabel='相对共同基线变化 / %',title='压力组保留全部84场')
    axes[0].legend(frameon=False,fontsize=8)
    cluster=[r for r in stress if r['kind']=='cluster'];ids,b,c=paired(cluster,'m021');worst=ids[int(np.argmax(c/b))]
    wr=[next(r for r in cluster if r['case_id']==worst and r['variant']==v) for v in ['m019','m020','m021']]
    bottom=np.zeros(3)
    for k,n,col in zip(costs,costnames,costcolors):
        vals=[r['costs'][k]/r['cleared_count'] for r in wr];axes[1].bar(np.arange(3),vals,bottom=bottom,color=col,label=n);bottom+=vals
    axes[1].set(xticks=np.arange(3),xticklabels=['基线','局部费用','选择性'],ylabel='完整费用 / s/源',title='聚集组最大相对退步例')
    axes[1].legend(frameon=False,fontsize=7,ncol=3,loc='upper left')
    note(fig,'左图正值为退步、负值为改善；右图案例 '+worst+' 的各项完整费用，未使用局部预测费用。')
    save(fig,'fig12_q3_stress_tradeoff')

    fig,axes=plt.subplots(1,2,figsize=(7.3,3.55),constrained_layout=True)
    for q,v,style in [('q3','m020','-'),('q4','m021','--')]:
        for vv in ['m019',v]:
            vals=[np.mean([r['per_source_s'] for r in part(q,'fresh_confirmation',vv) if r['source_count']==n]) for n in range(10,17)]
            axes[0].plot(range(10,17),vals,style,marker=markers[vv],ms=3,color=colors[vv],label=q.upper()+' '+labels[vv])
    axes[0].set(xlabel='源数',ylabel='组均值 / s/源',xticks=range(10,17),title='新确认每层各12场');axes[0].legend(frameon=False,fontsize=7.2,handlelength=3.8)
    bottom=np.zeros(3)
    for k,n,col in zip(costs,costnames,costcolors):
        vals=[np.mean([r['costs'][k]/r['cleared_count'] for r in part('q4','existing_panel',v)]) for v in ['m019','m020','m021']]
        axes[1].bar(np.arange(3),vals,bottom=bottom,color=col,label=n);bottom+=vals
    axes[1].set(xticks=np.arange(3),xticklabels=['基线','局部费用','选择性'],ylabel='平均完整费用 / s/源',title='Q4开发对照费用来源')
    axes[1].set_title('Q4开发对照费用来源',pad=30)
    axes[1].legend(frameon=False,fontsize=6.8,ncol=5,loc='upper center',bbox_to_anchor=(.5,1.105),columnspacing=1.05,handletextpad=.45,handlelength=1.9)
    save(fig,'fig16_source_count_cost')

    fig,axes=plt.subplots(1,2,figsize=(7.3,3.3),constrained_layout=True)
    for panel,linestyle,label in [('existing_panel','-','开发84场'),('fresh_confirmation','--','确认84场')]:
        ids,b,c=paired(part('q4',panel),'m021');changes=100*(c/b-1)
        axes[0].plot(np.sort(changes),linestyle,color=colors['m021'],label=label)
    axes[0].axhline(0,color=gray,lw=1);axes[0].set(xlabel='各组独立排序的场景',ylabel='相对共同基线变化 / %',title='Q4逐场改善与退步');axes[0].legend(frameon=False,fontsize=8)
    rows=part('q4','existing_panel');ids,b,c=paired(rows,'m021');worst=ids[int(np.argmax(c/b))]
    rr={r['variant']:r for r in rows if r['case_id']==worst}
    delta=[(rr['m021']['costs'][k]-rr['m019']['costs'][k])/rr['m019']['cleared_count'] for k in costs]
    axes[1].bar(costnames,delta,color=[extra_color if x>=0 else saved_color for x in delta]);axes[1].axhline(0,color=gray,lw=1)
    axes[1].set(ylabel='采用策略减共同基线 / s/源',title='开发组最大相对退步费用差')
    save(fig,'fig17_q4_regression')

    fig,axes=plt.subplots(1,2,figsize=(7.3,3.3),constrained_layout=True)
    for ax,q in zip(axes,['q3','q4']):
        rows=e['practice'][q]['rows'];x=np.arange(6);bottom=np.zeros(6)
        for k,n,col in zip(costs,costnames,costcolors):
            vals=[r['costs'][k]/r['cleared_count'] for r in rows];ax.bar(x,vals,bottom=bottom,color=col,label=n);bottom+=vals
        ax.set(xticks=x,xticklabels=[r['case_code'][:4] for r in rows],ylabel='完整费用 / s/源',title=q.upper()+' 六次演练')
        ax.axhline(e['practice'][q]['mean'],color=colors['m020' if q=='q3' else 'm021'],ls='--',lw=1)
    axes[1].legend(frameon=False,fontsize=7.4,ncol=3,loc='upper right')
    note(fig,'横轴为案例码前四位，完整案例码见结果表；虚线为逐场等权均值，原始加密日志未解密。')
    save(fig,'fig04_practice_cost')

    fig,axes=plt.subplots(1,2,figsize=(7.3,3.75),constrained_layout=True)
    for ax,q in zip(axes,['q3','q4']):
        worst=max(e['practice'][q]['rows'],key=lambda r:r['per_source_s']);code=worst['case_code']
        raw=gzip.decompress((data_dir/'practice'/code/'actions.jsonl.gz').read_bytes()).decode('utf-8')
        records=[json.loads(x) for x in raw.splitlines() if x.strip()]
        points=[(0,0)];success=[];fail=[]
        for r in records:
            pos=r['request'].get('position')
            if not pos or not r.get('accepted'):continue
            xy=(pos['x'],pos['y'])
            if xy!=points[-1]:points.append(xy)
            if r['endpoint']=='/clear':
                (success if r['response'].get('clear_result')=='success' else fail).append(xy)
        a=np.array(points);ax.plot(a[:,0],a[:,1],color=navy,lw=.8,alpha=.7);ax.add_patch(Circle((0,0),1800,fill=False,ec=gray,ls='--'))
        if success:
            a=np.array(success);ax.scatter(a[:,0],a[:,1],color=saved_color,s=18,label='成功清除位置')
        if fail:
            a=np.array(fail);ax.scatter(a[:,0],a[:,1],color=extra_color,marker='x',s=19,label='失败试清位置')
        ax.scatter(0,0,marker='*',color='black',s=50);ax.set(aspect='equal',xlabel='x / m',ylabel='y / m',title=q.upper()+' '+code[:4]+' 样本最慢局')
        ax.legend(frameon=False,fontsize=7,loc='upper right')
    note(fig,'实际动作轨迹；清除位置不是被披露的源真值。展示本批最慢局，未按图形美观挑选案例。')
    save(fig,'fig14_practice_trajectories')
    # 图5、图14于V19复核中按上方源程序修正；全量入口恢复已核对的定稿画面。
    # names仅导出指定图件，不运行任何模型或模拟器。
    if names is None:
        restore_final_figures(data_dir, output, {'fig05_strategy_flow', 'fig16_source_count_cost', 'fig04_practice_cost'})

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=Path(__file__).resolve().parent/'数据');p.add_argument('--output',type=Path,default=Path('运行结果/图件'))
    a=p.parse_args();render(a.data,a.output)
