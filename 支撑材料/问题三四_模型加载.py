"""加载问题三、四固定模型及基线参数，程序身份由文件校验记录。"""
import hashlib,importlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FROZEN=ROOT
from 问题三四_基础参数读取 import baseline_config
from 问题三四_几何求解基线 import Solver, ObservedSession
from 问题三_阴性观测收缩 import NegativeSolver
from 问题三四_动作接口协议 import Session
from 问题三四_离线物理模拟 import LocalSimulator
from 问题三四_动作费用核算 import recompute
from 问题三四_动作轨迹独立核验 import audit_records, ReplayTransport
from 问题三_阴性观测几何核验 import audit_trace
sys.path.insert(0,str(ROOT))
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def baseline_settings(problem):return dict(read(ROOT/'数据/参数/问题三四_共同基线参数.json')[problem])
def m020_settings(problem):return dict(baseline_settings(problem),**read(ROOT/'数据/参数/问题三四_费用模型选型.json')['selected'][problem]['settings'])
def solve_baseline(session,problem,settings=None):
    return (NegativeSolver if problem=='q3' else Solver)(session,problem,baseline_settings(problem) if settings is None else settings).run()
def solve_m020(session,problem,settings=None):
    variant=read(ROOT/'数据/参数/问题三四_费用模型选型.json')['selected'][problem]
    return importlib.import_module(variant['module']).solve(session,problem,m020_settings(problem) if settings is None else settings)
