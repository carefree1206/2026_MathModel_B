# -*- coding: utf-8 -*-
"""根据几何模型与六场演练原始汇总生成论文插图。"""
from pathlib import Path
import json
import math
import sys


# 内部标识保持兼容；导出的中文文件名与论文图1—图16逐一对应。
FIGURE_FILENAMES = {
    'fig06_feasible_contraction': '01_多测点定位区域收缩',
    'fig01_diameter_circle': '02_定位直径与最小包围圆',
    'fig02_second_point': '03_第二测点安全域与候选位置',
    'fig15_q2_cost_accuracy': '04_问题二移动费用与定位精度',
    'fig05_strategy_flow': '05_搜索定位与清除流程',
    'fig03_search_coverage': '06_问题三七点巡检布局',
    'fig18_q3_cost_candidates': '07_问题三局部测点费用比较',
    'fig11_q3_paired': '08_问题三同场策略对照',
    'fig12_q3_stress_tradeoff': '09_问题三困难场景费用权衡',
    'fig08_directional_hull': '10_定向源近邻凸包覆盖',
    'fig20_directional_coverage': '11_问题四二十一点发现布局',
    'fig19_q4_transit_information': '12_问题四途中测向决策',
    'fig17_q4_regression': '13_问题四退步案例分析',
    'fig16_source_count_cost': '14_源数量与每源费用',
    'fig04_practice_cost': '15_官方演练费用构成',
    'fig14_practice_trajectories': '16_官方演练轨迹',
}


def restore_final_figures(data_dir, output, names=None, chinese_names=True):
    """恢复人工定稿PNG及同画面的SVG位图封装，不重算人工图层。

    来源与适用范围见 数据/定稿图件/说明.md；names使用原内部绘图名。
    """
    import base64
    import hashlib
    import struct
    from xml.sax.saxutils import escape
    records = [('fig15_q2_cost_accuracy', '464b529444600da908899c2b981441d6cc809bf13b90ebc84a7ffda052127a22'), ('fig05_strategy_flow', '0197bd8014a2dd1430152a2208aac7a86501ce57a2a22c21e7d576a565e13b04'), ('fig03_search_coverage', 'fe02971301269926d95eb9748fd84788b0c707991e34e4bfe7022f41f4bdda49'), ('fig16_source_count_cost', '9703e69d37747fd7f6a21cb0c3e1a8b0da7d56f031c35076a3667ba5d3b03ff3'), ('fig04_practice_cost', '6dd291e62e517e063c707c1ac3c910e09e39e039ca0f096035514068b2dbf955')]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    restored = []
    for internal, expected in records:
        if names is not None and internal not in names:
            continue
        filename = FIGURE_FILENAMES[internal] + '.png'
        raw = (Path(data_dir) / '定稿图件' / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('定稿图件摘要不一致：' + filename)
        width, height = struct.unpack('>II', raw[16:24])
        stem = Path(filename).stem if chinese_names else internal
        (output / (stem + '.png')).write_bytes(raw)
        encoded = base64.b64encode(raw).decode('ascii')
        svg = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{width}px" height="{height}px" viewBox="0 0 {width} {height}">\n'
            f'<title>{escape(filename)} 定稿PNG的SVG位图封装</title>\n'
            '<desc>与同名PNG逐字节一致的嵌入位图；不是可编辑矢量重绘，'
            '也不表示重新计算了人工图层。来源见数据/定稿图件/说明.md。</desc>\n'
            f'<image width="{width}" height="{height}" '
            f'xlink:href="data:image/png;base64,{encoded}"/>\n</svg>\n')
        (output / (stem + '.svg')).write_text(svg, encoding='utf-8')
        restored.append(stem)
    return restored

def render_basic(out, data_dir):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    from matplotlib import font_manager
    root=Path(__file__).resolve().parent
    out.mkdir(parents=True,exist_ok=True)
    available={f.name for f in font_manager.fontManager.ttflist}
    cn=next((n for n in ['Microsoft YaHei','SimHei','Noto Sans CJK SC','DejaVu Sans'] if n in available),'sans-serif')
    plt.rcParams.update({'font.family':cn,'font.size':10,'axes.unicode_minus':False,
        'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#929AA3',
        'axes.labelcolor':'#374151','xtick.color':'#59636F','ytick.color':'#59636F',
        'savefig.dpi':240,'figure.facecolor':'white','svg.fonttype':'none'})
    navy='#234F6D';teal='#4B898B';gray='#A4ADB6'
    def save(fig,name):
        name = FIGURE_FILENAMES[name]
        fig.savefig(out/(name+'.png'),bbox_inches='tight',facecolor='white')
        fig.savefig(out/(name+'.svg'),bbox_inches='tight',facecolor='white');plt.close(fig)
    # 图2用等边三角形展示直径与包围圆的区别，避免暗示错误的清除判据。
    fig,ax=plt.subplots(figsize=(6.2,3.5),constrained_layout=True)
    tri=np.array([[0,0],[40,0],[20,20*math.sqrt(3)],[0,0]])
    center=(20,20/math.sqrt(3));radius=40/math.sqrt(3)
    ax.fill(tri[:,0],tri[:,1],color=navy,alpha=.12)
    ax.plot(tri[:,0],tri[:,1],color=navy,lw=1.7)
    ax.add_patch(Circle(center,radius,fill=False,color=navy,lw=1.4))
    ax.add_patch(Circle((20,0),20,fill=False,color=gray,lw=1.2,ls='--'))
    ax.scatter(*center,color=navy,s=20)
    ax.text(48,27,'定位区域直径  40 m',color=navy)
    ax.text(48,16,'最小包围圆半径\n40/√3 ≈ 23.09 m',color=navy,linespacing=1.6)
    ax.text(48,1,'虚线圆半径  20 m',color='#737D87')
    ax.set(xlim=(-7,112),ylim=(-23,44),aspect='equal',xlabel='x / m',ylabel='y / m')
    save(fig,'fig01_diameter_circle')
    # 图3直接计算四个圆盘的交集；虚线只是坐标轴，三个标记是正文候选测点。
    fig,ax=plt.subplots(figsize=(6.3,4.1),constrained_layout=True)
    x=np.linspace(-80,1580,601);y=np.linspace(-1030,1030,601);xx,yy=np.meshgrid(x,y)
    delta=math.radians(1.005)
    mask=np.ones_like(xx,dtype=bool)
    for r in [5,1000]:
        for sign in [-1,1]:mask &= (xx-r*math.cos(delta))**2+(yy-sign*r*math.sin(delta))**2<=1000**2
    ax.contourf(xx,yy,mask.astype(float),levels=[.5,1.5],colors=['#DFEAF0'])
    ax.contour(xx,yy,mask.astype(float),levels=[.5],colors=[navy],linewidths=1.2)
    ax.plot([0,1500*math.cos(delta)],[0,1500*math.sin(delta)],color=gray,lw=1)
    ax.plot([0,1500*math.cos(delta)],[0,-1500*math.sin(delta)],color=gray,lw=1)
    for p,label,offset,color in [((750,500),'基准 (750, 500)',(-165,-290),gray),((710,555),'均衡 (710, 555)',(-570,160),teal),((840,548),'精度 (840, 548)',(95,180),navy)]:
        ax.scatter(*p,color=color,s=32,zorder=5)
        ax.annotate(label,p,(p[0]+offset[0],p[1]+offset[1]),arrowprops={'arrowstyle':'-','color':color,'lw':.8},fontsize=9,color=color)
    ax.scatter(0,0,color='black',s=20);ax.text(30,-145,'首测点')
    ax.text(490,-620,'安全候选区域 Ω',color=navy,ha='center')
    ax.set(aspect='equal',xlabel='局部横坐标 / m',ylabel='局部纵坐标 / m',xlim=(-80,1580),ylim=(-1000,1000))
    save(fig,'fig02_second_point')
    # 两问分别输出构造图，避免在第三问中提前混入定向模型。
    fig,axes=plt.subplots(1,3,figsize=(7.3,2.7),constrained_layout=True)
    for ax,n,radius in zip(axes,[6,7,8],[1125,998,940]):
        ax.add_patch(Circle((0,0),1800,facecolor='#F4F7F9',edgecolor=navy,lw=1))
        angles=np.arange(n)*2*math.pi/n
        points=[(0,0)]+list(zip(radius*np.cos(angles),radius*np.sin(angles)))
        for point in points:ax.add_patch(Circle(point,1000,fill=False,color='#C7D4DF',lw=.65))
        arr=np.array(points);ax.scatter(arr[:,0],arr[:,1],s=15,color=navy,zorder=3)
        ax.scatter(0,0,s=23,color=teal,zorder=4)
        ax.set(aspect='equal',xlim=(-2200,2200),ylim=(-2200,2200),xlabel='x / m',ylabel='y / m',title=f'1+{n}  环半径{radius} m')
        ax.set_xticks([-1800,0,1800]);ax.set_yticks([-1800,0,1800]);ax.tick_params(labelsize=7)
    save(fig,'fig03_search_coverage')

    # 同一坐标尺度比较两种经连续认证的发现构造；不把点数减少写成整场提速。
    layouts=json.loads((Path(data_dir)/'layout_comparison.json').read_text(encoding='utf-8'))['layouts']
    fig,axes=plt.subplots(1,2,figsize=(7.3,3.2),constrained_layout=True)
    for ax,item,label in zip(axes,layouts,['27点三角格','21点双环']):
        pts=np.array(item['points'])
        ax.add_patch(Circle((0,0),1800,facecolor='#F4F7F9',edgecolor=gray,lw=1))
        if len(pts)==27:
            for i in range(len(pts)):
                for j in range(i):
                    if abs(np.linalg.norm(pts[i]-pts[j])-900)<.01:
                        ax.plot(pts[[i,j],0],pts[[i,j],1],color='#CAD4DD',lw=.65,zorder=1)
        else:
            for radius in [999,1867]:ax.add_patch(Circle((0,0),radius,fill=False,color='#BBC9D4',ls='--',lw=.8))
        ax.scatter(pts[:,0],pts[:,1],color=navy,s=17,zorder=3)
        ax.scatter(0,0,marker='x',color=teal,s=32,zorder=4)
        ax.set(aspect='equal',xlim=(-2550,2550),ylim=(-2550,2550),xlabel='x / m',ylabel='y / m',title=label)
        ax.set_xticks([-1800,0,1800]);ax.set_yticks([-1800,0,1800])
    save(fig,'fig20_directional_coverage')

def render_geometry(data_dir, output):
    """读取项目相对路径中的数据；不访问网络或官方模拟器。"""
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Circle, Polygon, FancyBboxPatch

    data = {'q1_sequential':json.loads((Path(data_dir)/'q1_examples.json').read_text(encoding='utf-8'))['sequential'], 'q2':json.loads((Path(data_dir)/'q2_results.json').read_text(encoding='utf-8'))['candidates']}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((n for n in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'DejaVu Sans']
                 if n in available), 'sans-serif')
    navy, teal, gray = '#234F6D', '#4B898B', '#A4ADB6'
    pale, ink, rust = '#DFEAF0', '#374151', '#9A6555'
    plt.rcParams.update({'font.family': font, 'font.size': 9.2, 'axes.unicode_minus': False,
        'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#929AA3',
        'axes.labelcolor': ink, 'xtick.color': '#59636F', 'ytick.color': '#59636F',
        'savefig.dpi': 260, 'figure.facecolor': 'white', 'svg.fonttype': 'none'})

    def save(fig, name):
        name = FIGURE_FILENAMES[name]
        fig.savefig(output / (name + '.png'), bbox_inches='tight', facecolor='white')
        fig.savefig(output / (name + '.svg'), bbox_inches='tight', facecolor='white')
        plt.close(fig)

    def note(fig, message='几何示意，非实测结果'):
        fig.text(.5, -.025, message, ha='center', fontsize=8.2, color='#68737E')

    # 与 问题一_多测点示例与退化检验.py 采用同一四测站与两位小数读数；给定坐标仅服务几何解释。
    fig, axes_grid = plt.subplots(2, 2, figsize=(7.1, 5.4), constrained_layout=True)
    axes = axes_grid.flat
    sequential = data['q1_sequential']
    target = np.array(sequential['reference_source_m'])
    stations = np.array([z['station_m'] for z in sequential['observations']])
    # 只为显示而裁剪画窗；求解器返回的无界状态和直径不受此裁剪影响。
    def display_clip(poly, a, b, c):
        clipped=[]
        for u,v in zip(poly,poly[1:]+poly[:1]):
            fu=a*u[0]+b*u[1]-c;fv=a*v[0]+b*v[1]-c
            if fu<=0:clipped.append(u)
            if (fu<=0)!=(fv<=0):
                ratio=fu/(fu-fv);clipped.append([u[0]+ratio*(v[0]-u[0]),u[1]+ratio*(v[1]-u[1])])
        return clipped
    for i, ax in enumerate(axes):
        p = stations[i]; observation = sequential['observations'][i]
        poly=[[845.,35.],[955.,35.],[955.,145.],[845.,145.]]
        for hp in observation['accumulated_halfplanes']:
            poly=display_clip(poly,hp['a'],hp['b'],hp['c'])
        ax.add_patch(Polygon(poly,facecolor=pale,edgecolor='none' if i==0 else navy,lw=1.2))
        if i==0:
            # 无界楔形的左右视窗边缘不描边，避免被误读成真正的约束。
            for hp in observation['accumulated_halfplanes']:
                xx=np.array([845.,955.]);yy=(hp['c']-hp['a']*xx)/hp['b']
                ax.plot(xx,yy,color=navy,lw=1.2)
        ax.scatter(*target, color=teal, s=19, marker='x', zorder=5)
        ax.set(aspect='equal', xlabel='x / m', xlim=(845,955), ylim=(35,145))
        ax.set_xticks([860,900,940]); ax.set_yticks([50,90,130])
        ax.set_title('纳入第 ' + str(i+1) + ' 次观测', fontsize=10.1, pad=9)
        ax.text(.04,.96,'测点 '+str(tuple(map(int,p))),transform=ax.transAxes,va='top',fontsize=7.7)
        d=observation['region']['diameter_m']
        text='直径无界' if d is None else '直径 '+f'{d:.2f}'+' m'
        ax.text(.04,.07,text,transform=ax.transAxes,fontsize=8.2,color=navy)
    axes_grid[0,0].set_ylabel('y / m'); axes_grid[1,0].set_ylabel('y / m')
    note(fig, '几何示例，非实测；误差半宽 1.005°；× 为示例真值；第 4 次观测仅用于展示区域继续收缩')
    save(fig, 'fig06_feasible_contraction')

    # 原点位于邻近搜索点凸包内，任一过原点闭半平面必含至少一个这些点。
    fig, axes = plt.subplots(1,2,figsize=(7.1,3.2),constrained_layout=True)
    pts=np.array([[-.65,-.50],[.72,-.30],[-.08,.80]])
    for ax, angle in zip(axes,[18,116]):
        phi=math.radians(angle);n=np.array([math.cos(phi),math.sin(phi)]);v=np.array([-n[1],n[0]])
        ax.add_patch(Circle((0,0),1,fill=False,color=gray,lw=1.0))
        ax.add_patch(Polygon([-1.3*v,1.3*v,1.3*v+1.6*n,-1.3*v+1.6*n],facecolor='#E9F1ED',edgecolor='none'))
        ax.add_patch(Polygon(pts,facecolor=pale,edgecolor=navy,alpha=.85,lw=1.2))
        ax.plot([-1.3*v[0],1.3*v[0]],[-1.3*v[1],1.3*v[1]],color=teal,lw=1.4)
        good=pts@n>=0
        ax.scatter(pts[:,0],pts[:,1],s=35,color=[teal if g else navy for g in good],zorder=5)
        ax.scatter(0,0,color=ink,marker='x',s=28,zorder=5)
        ax.annotate('', .7*n, (0,0),arrowprops={'arrowstyle':'->','color':teal,'lw':1.3})
        ax.text(.78*n[0],.78*n[1],'辐射方向',fontsize=8.5,color=teal,ha='center')
        ax.set(aspect='equal',xlim=(-1.25,1.25),ylim=(-1.15,1.2));ax.axis('off')
        ax.set_title('方向 '+str(angle)+'°：有搜索点落入辐射半平面',fontsize=9.6)
    note(fig, '几何示意；× 为源位置，圆为最小接收距离，三角形为邻近搜索点凸包')
    save(fig, 'fig08_directional_hull')

    # Q2的点间连线只辅助对应关系，不能当成连续参数搜索的帕累托前沿。
    fig,axes=plt.subplots(1,2,figsize=(7.1,3.2),constrained_layout=True)
    candidates=data['q2'];names={'legacy':'基准','balanced':'均衡','accuracy':'精度'}
    for i,c in enumerate(candidates):
        name=names.get(c['name'],c['name']);bound=next(z for z in c['bounds'] if abs(z['delta_deg']-1.005)<1e-8)
        t=c['selection']['move_time_s'];lo=bound['lower_m'];hi=bound['upper_m']
        axes[0].errorbar(t,(lo+hi)/2,yerr=(hi-lo)/2,fmt='o',color=[gray,teal,navy][i],capsize=4,ms=6)
        offsets={'legacy':(7,5),'balanced':(7,-16),'accuracy':(-34,7)}
        axes[0].annotate(name,(t,(lo+hi)/2),xytext=offsets.get(c['name'],(6,6)),textcoords='offset points',fontsize=9)
    axes[0].set(xlabel='移动时间 / s',ylabel='最坏定位直径 / m',xlim=(176,206),ylim=(107,134))
    axes[0].set_title('有限候选点的精度与移动代价',fontsize=10)
    x=np.arange(len(candidates))
    for offset,delta,color,label in [(-.16,1.,gray,'理论 1°'),(.16,1.005,navy,'实现 1.005°')]:
        upp=[next(z['upper_m'] for z in c['bounds'] if abs(z['delta_deg']-delta)<1e-8) for c in candidates]
        axes[1].bar(x+offset,upp,width=.29,color=color,label=label)
        for xx,v in zip(x+offset,upp):axes[1].text(xx,v+1,f'{v:.2f}',ha='center',fontsize=7.4,rotation=90)
    axes[1].set(xticks=x,xticklabels=[names.get(c['name'],c['name']) for c in candidates],ylabel='最坏直径计算上界 / m',ylim=(0,164))
    axes[1].legend(frameon=False,fontsize=8.1,loc='upper center',ncol=2);axes[1].set_title('加入读数舍入半单位后的影响',fontsize=10)
    note(fig,'几何计算结果；左图误差棒为上下界区间，非统计置信区间；没有证明三个候选构成全局最优前沿')
    save(fig,'fig15_q2_cost_accuracy')



def render(data_dir, output):
    render_basic(Path(output), data_dir)
    render_geometry(data_dir, output)
    # 图4、图6采用人工定稿素材，复制恢复并同步SVG画面。
    restore_final_figures(data_dir, output, {'fig15_q2_cost_accuracy', 'fig03_search_coverage'})
