"""加载M019冻结协议与基线的公共配置。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def hashes():
    files=list(ROOT.glob('*.py'))+list((ROOT/'数据/参数').glob('*.json'))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}

def baseline_config(problem):
    name={'q3':'数据/参数/问题三_物理与动作参数.json','q4':'数据/参数/问题四_物理与动作参数.json'}[problem]
    return read(ROOT/name)
