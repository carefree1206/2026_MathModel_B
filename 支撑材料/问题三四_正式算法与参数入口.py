"""唯一正式选型入口；离线基线比较不改变 GUI / CLI 的默认算法。"""
from pathlib import Path
import hashlib,importlib,json,sys,urllib.parse
ROOT=Path(__file__).resolve().parent
MODEL=ROOT
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def local_url(value):
    """官方入口只接受本机 HTTP 端口；不依赖可视化模块。"""
    if not isinstance(value,str) or any(c.isspace() for c in value):raise ValueError('本机地址格式无效')
    p=urllib.parse.urlsplit(value)
    if (p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.port is None
            or not 1<=p.port<=65535 or p.username is not None or p.password is not None
            or p.path not in ('','/') or p.query or p.fragment):raise ValueError('只接受带端口的本机 HTTP 地址')
    return value.rstrip('/')
def verify_files():
    manifest=read(ROOT/'数据/程序校验.json')
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('交付程序或参数发生变化：'+name)
    return dict(passed=True,frozen_files=len(manifest['sha256']),
                original_candidate_source_files=84,chinese_program_copy=True,network_requests=0)
def load(problem,comparison=None):
    if problem not in ('q3','q4'):raise ValueError('题号无效')
    verify_files()
    sys.path.insert(0,str(ROOT))
    bootstrap=importlib.import_module('问题三四_模型加载')
    if Path(bootstrap.__file__).resolve()!=MODEL/'问题三四_模型加载.py':raise RuntimeError('检测到其他版本模块缓存；请使用新进程')
    chosen=read(ROOT/'数据/参数/问题三四_正式算法选型.json')[problem]
    alg=comparison or chosen['algorithm']
    if alg=='m019':
        settings=bootstrap.baseline_settings(problem)
        cls=bootstrap.NegativeSolver if problem=='q3' else bootstrap.Solver
        solve=bootstrap.solve_baseline;module=cls.__module__;variant='baseline'
    else:
        if alg not in ('m020','m021'):raise ValueError('离线对照无效')
        selected=read(MODEL/('数据/参数/问题三四_费用模型选型.json' if alg=='m020' else '数据/参数/问题三四_信息调度选型.json'))['selected'][problem]
        settings=bootstrap.m020_settings(problem)
        if alg=='m021':settings.update(selected['settings'])
        module=selected['module'];variant=selected['name']
        mod=importlib.import_module(module)
        cls=getattr(mod,{'m020':{'q3':'Cost5Q3','q4':'CandidateQ4'},'m021':{'q3':'Q3','q4':'Q4'}}[alg][problem]);solve=mod.solve
    if comparison is None and (settings!=read(ROOT/'数据/参数'/({'q3':'问题三_算法参数.json','q4':'问题四_算法参数.json'}[problem])) or module!=chosen['module']):
        raise ValueError('正式配置与冻结选型不一致')
    from 问题三四_动作接口协议 import Session, HttpTransport, ExecutionLimit
    config=bootstrap.baseline_config(problem)
    version=alg.upper()+('-v2' if alg=='m021' else '')+'-'+problem+'-'+variant
    config['version']=version
    return dict(problem=problem,algorithm=alg,version=version,module=module,settings=settings,config=config,
                klass=cls,solve=solve,Session=Session,ObservedSession=bootstrap.ObservedSession,
                HttpTransport=HttpTransport,ExecutionLimit=ExecutionLimit)
