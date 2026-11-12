# ToolV2X 研究点一

面向目标真实性核验的观测条件与多源依赖证据建模。

本分支 `research/rq1-current-2026-11-12` 是独立研究快照。它整理当前有用实现及必要证据，入口不再指向旧驾驶实验。原工作区和历史分支仍保留。当前真实缓存实验未完成，已完成的合成结果不能当作车辆实验效果。

## 从这里开始

1. [当前方案](docs/研究点一_当前方案.md)：实际输入、证据强度、联合计算、参数来源、三态和效果边界。
2. [当前状态](docs/STATUS.md)：已完成内容与中断位置。
3. [协作交接](docs/COLLABORATION.md)：分工、任务提交和实验数据权限。
4. [当前实施规格](docs/REALLY_MAYBE/rq1_real_cue_2026_11_11/SDS.md)和[代码审核](docs/REALLY_MAYBE/rq1_real_cue_2026_11_11/code_review.md)。

## 代码与证据

| 路径 | 用途 |
| --- | --- |
| `scripts/rq1_real_cue/` | 当前几何C、正常概率、联合修正及B/C/J/G比较 |
| `scripts/rq1_conditional_revision.py` | 前一阶段受控条件机制 |
| `scripts/run_rq1_conditional_revision.py` | 受控机制枚举入口 |
| `scripts/rq1_common_factor.py` | 受控机制依赖及历史核函数 |
| `examples/real_frame.json` | 一帧实际预查询、公开位姿及已保存几何输出 |
| `docs/REALLY/` | 有条件的实验结论，含不利结果 |
| `docs/REALLY_MAYBE/` | 计划、规格及审核依据 |
| `docs/evidence/` | 已完成的受控结果与旧静态开发摘要 |
| `docs/provenance/` | 导出文件来源及校验记录 |

## 在另一环境运行

本次验证使用Python 3.8.10。依赖版本为本次打包环境实际版本，不要求GPU、AVstack或检测模型。

```bash
git clone --single-branch --branch research/rq1-current-2026-11-12 https://github.com/HikiMaji/ToolV2X-2.git
cd ToolV2X-2
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s scripts/rq1_real_cue -p 'test_real_cue.py' -v
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s tests -p 'test_rq1_conditional_revision.py' -v
```

第一组包含临时小型fixture的提取、拟合和报告流程。它检验代码接口，不产生真实缓存效果。

实际一帧样例可以直接复算几何，不拟合模型。

```bash
python - <<'PYCODE'
import json
from scripts.rq1_real_cue.run import extract_frame
s = json.load(open('examples/real_frame.json'))
rows, stats = extract_frame(s['events'], s['sender'], s['source_ids'])
fields = list(s['expected_geometry'][0])
assert [{k: r[k] for k in fields} for r in rows] == s['expected_geometry']
print('Geometry matches stored output:', len(rows), 'queries')
PYCODE
```

受控实验已有完整结果。若需复现，显式使用新输出目录。

```bash
python scripts/run_rq1_conditional_revision.py --output outputs/conditional-reproduction
```

完整真实缓存批次需要服务器上的39任务configs、events、sender和labelled数据，本分支没有上传这些大型依赖。历史manifest保留绝对路径以说明来源，不表示在异地可直接运行。`run.py`支持`--manifest`和`--out`；迁移时不仅要替换manifest参数，还须解析其中config路径及config内sender路径。当前run_001不完整，恢复说明见协作交接。

代码主要从817aa47原样导出，合成核心来源d3c29ae。整理不改变评分算法；详见[来源清单](docs/provenance/export_manifest.json)。
