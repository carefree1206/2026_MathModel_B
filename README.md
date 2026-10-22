# 2026_MathModel_B

2026 年数学建模 B 题工程归档：**基于连续覆盖与费用驱动决策的无线电干扰源自动定位与清除**。

本仓库收录最终论文、Q1–Q4 求解与核验程序、冻结参数、实验数据、官方测试日志、论文图件及答辩材料。Q3 正式算法为 **M020**，Q4 为 **M021**。模型源码和参数保持原有字节及校验摘要，新增脚本提供统一的工程入口。

## 材料入口

| 内容 | 位置 |
| --- | --- |
| 最终论文 | [PDF](我的论文.pdf) · [Word](我的论文.docx) |
| 算法、数据与图件 | [支撑材料](支撑材料/) · [原始复现说明](支撑材料/复现说明.md) |
| 最新完整答辩稿 | [总结展望重写版 PPTX](答辩材料/无线电干扰源定位与清除_答辩_总结展望重写版.pptx) |
| 答辩完整母版与配套 PDF | [PPTX](答辩PPT制作/数学建模答辩_完整母版.pptx) · [PDF](答辩PPT制作/数学建模答辩_完整母版.pdf) |
| 公式、追问与补充核验 | [答辩准备](答辩材料/答辩准备_20261006/) · [Q2 参数依据](答辩材料/问题二参数依据补充/) |
| 两局已审计的演示回放 | [操作提示](答辩PPT制作/演示运行/现场演示操作提示.md) |
| 题目与附件 | [data/raw](data/raw/) |
| 工程结构和归档选择 | [材料索引](docs/MATERIALS.md) |

完整母版及其 PDF 形成一套配对材料；最新答辩 PPT 是其后的独立修订稿，母版 PDF 不代表最新 PPT 的逐页内容。

## 下载与安装

PPTX 通过 Git LFS 保存。先安装 Git LFS，再克隆仓库，以获取完整演示文件：

```bash
git lfs install
git clone https://github.com/carefree1206/2026_MathModel_B.git
cd 2026_MathModel_B
git lfs pull
```

指定复现环境为 Python **3.9.13**、NumPy **1.21.5**、SciPy **1.9.1**、Matplotlib **3.5.2**。在 Windows PowerShell 中：

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/verify_archive.py
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/reproduce.py --task verify
```

其他系统使用 Python 3.9.13 创建虚拟环境，并将命令中的解释器路径替换为 `.venv/bin/python`。主依赖版本见 `requirements.txt`，本次归档核验的完整依赖版本见 `requirements-lock.txt`。

## 复现与演示

```powershell
# 几何、问题二数值界及问题四理论证书
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/reproduce.py --task geometry
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/reproduce.py --task q2
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/reproduce.py --task theory

# 一局新的离线合成演示；将 q3 改为 q4 可切换题号
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/reproduce.py --task simulate --problem q3

# 完整离线实验；含 1482 次性能配置运行及严格重放
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/reproduce.py --task all --workers 6

# 浏览器交互终端
.\.venv\Scripts\python.exe -s -B -X utf8 scripts/launch_demo.py

# 播放已归档的两局演示
.\.venv\Scripts\python.exe -s -B -X utf8 "答辩PPT制作/制作源文件/真实单局回放服务.py"
```

新增结果默认写入带时间标识的 `results/` 子目录，可用 `--output` 指定位置。两局历史回放位于本机端口 8876（Q3）和 8877（Q4）。GUI 新跑曾在原机器上出现启动停滞，现场展示前需彩排；已审计回放可直接作为后备。

严格官方请求重放要求 Python 3.9.13。`all` 包含既有 12 局演练重放；6 局正式测试的原始账本及核验记录单独保存在 `支撑材料/数据/正式测试/`。本次工程整理执行的检查范围见 [VALIDATION.md](docs/VALIDATION.md)。

更多任务参数、数据口径和官方模拟器操作见 [复现指南](docs/REPRODUCIBILITY.md)。

## 完整性与归档边界

- [material_manifest.json](docs/material_manifest.json) 记录 352 份收录材料的路径、大小、当前摘要、原始摘要及路径适配说明。
- `scripts/verify_archive.py` 核对材料摘要和冻结源码；`--scope core` 可在没有下载 LFS 演示文件时仅核验模型材料。
- 保留原始目录关系，便于核对论文、日志和既有补充程序；虚拟环境、缓存、重复交付压缩包和中间 PPT 未收录。
- 现有 `支撑材料/文件清单.json` 是历史清单，其中 `AI工具使用详情.docx` 在当前项目中已不存在；本仓库收录实际可用的 `AI工具使用详情.pdf`。其余 264 个历史条目的摘要与原清单一致。

本次工程归档日期：2026-10-22（Asia/Shanghai）。
