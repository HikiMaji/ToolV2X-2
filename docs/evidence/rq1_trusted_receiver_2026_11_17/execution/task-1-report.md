# Task 1 实施报告

状态完成。实现和合成输入验收已完成，未运行真实效果、训练、其他车辆跟踪或中央融合。BASE为321a89a。最终commit见主会话交付消息。

## 交付范围

- `scripts/rq1_trusted_receiver/local.py` 实现 `measure_local`、`measure_frame`、BEV IoU双向唯一相容、原始射线0.25米采样体素穿越、截断末格实际体积计权及终点占据优先。
- `scripts/rq1_trusted_receiver/run.py` 实现 `prepare(config, out)`。每父重建一次指定ego的clean本地tracker，完整时序调用原有fresh_tracks，不创建其他车tracker或中央融合。缓存ego pose与fresh车辆框，clean fit仅供固定参考形体。cal/eval读取每个job自己的public online查询，按job/frame独立匹配，同帧只读取一次ego PCD，相同xyz/yaw/shape的F在该帧临时复用。
- `__init__.py`、`test_local.py`、`test_run.py`。未修改既有方法、门限、冻结输入或文档镜像。

## 最小config与调用

```json
{
  "parents": [{"parent":"split/recording", "split":"fit|cal|eval", "root":"raw recording root", "detections":"npz directory", "frames":[2,4,6], "receiver_id":7, "source_ids":[1,4,7]}],
  "jobs": [{"job_id":"filename-safe id", "parent":"split/recording", "kind":"clean|attack", "online_path":"public online.jsonl.gz", "rows_path":"offline rows.jsonl.gz", "features_path":"existing feature path"}]
}
```

`source_ids`是可选父元数据，若提供则核查receiver在内；每条cal/eval online记录也核查其原source_ids包含固定receiver。shape角色要求至少一个clean fit job。fit的online_path只检查存在，不打开。Task1不打开rows_path或features_path。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m scripts.rq1_trusted_receiver.run --stage prepare --config CONFIG.json --out NEW_OUT
```

连续帧沿用原native适配的frame步长2与每扫描0.1秒，并检查online index/timestamp严格对应。额外或乱序frame直接停止，防止错误对应。单行时间或receiver不对应保留主键并标input_fault。

## Task2消费接口

输出 `shape.json`、`parents/<parent slash replaced __>/receiver.jsonl.gz`、`jobs/<job_id>/local.jsonl.gz`、`prepare.config.json`、`prepare.complete.json`。配置发生变化拒绝复用同一输出。存在完整侧录时不覆盖。

fit固定仅shape，不开PCD、不生成local侧录；其complete jobs项为 `{"status":"SHAPE_ONLY","rows":0}`。Task2应只消费cal/eval。

每条local JSON公共字段如下。

| 字段 | 语义 |
| --- | --- |
| key/job_id/parent/id | 原job/frame/id主键和父录制 |
| receiver_id/frame/index/timestamp/receiver_timestamp | 固定接收车及原查询/本地时间 |
| query_present/newborn | 原查询存在和出生状态 |
| I/F | 数值或null。null为不可用，不补0 |
| I_eligible/F_eligible | 原始几何资格，未套校准门限 |
| input_fault | true必须故障未知，不进入消息回退 |
| status | ok、no_query、input_fault |
| I_status | matched、no_support、ambiguous、no_query或unavailable |
| F_status | covered、no_coverage、no_query或unavailable |
| n_compatible/matched_local_id | 相容数量和唯一本地框ID，可选 |
| n_points/n_intersecting_rays/n_voxels/n_free/n_occupied/n_covered | 原始射线与体素诊断，仅有效F行有值 |
| fault | 故障说明，可选 |

有效空PCD为 `F=0,F_eligible=true,F_status=no_coverage`。缺PCD/坏pose/非有限geometry使I和F都为null，两个资格false，input_fault=true。newborn/no-query在公共输入正常时保持no_query。无检测不产生I，也不会把F补成反证。Task2仍需根据原共同资格处理newborn/identity等政策。该侧录不接入任何标签或controlled_sources。

`measure_local(query, fresh_boxes, origin_world, points_world, shape_hwl)`为单查询几何入口。多查询调用必须用`measure_frame`，否则无法检验框对全部查询的双向唯一性。query需xyz/yaw以及timestamp，native轨迹xyz为bottom，yaw为弧度。fresh_boxes需id/xyz/yaw/hwl/timestamp/fresh/obj_type。

## 坐标、PCD差异与限制

真实坐标追到原run_native的S、rot、ref_from_pose，以及Box3D.yaw、原生角点构造。变换为原始点先乘S，再按原生参考旋转和平移转全局；射线起点是ref.x。合成非零roll/yaw/pitch验证和native角点匹配均已通过。

原 `load_points` 在无DATA头时可能无限读EOF，空或单点数组的len检查也不正确。经主会话明确同意，新runner保留其ASCII前三列语义，增加DATA/POINTS/FIELDS/EOF、0/1点形状、计数与有限性检查。仅支持ASCII xyz PCD；binary或计数错误是明确input_fault，不吞错变empty。未修改旧loader。

F仍是射线穿越体素体积分数，不代表体素被完全观测为空闲；没有引入默认形体、FOV外补反证、消息攻击身份或GT。时间/帧验证不能替代实际采集同步精度结论。本轮没有真实运行性能或方法效果证据。

## 验证

native Python命令 `-m unittest discover -s scripts/rq1_trusted_receiver -p 'test_*.py'` 最终17项通过，7.725秒。覆盖前/内/后回波、占据优先、末格体积、旋转坐标、角点擦过、稀疏射线、重复/歧义检测、跨job匹配隔离、F缓存不复用I、零点与缺文件、ASCII损坏、非有限geometry、时间异常不污染其他查询、clean fit形体均衡、fit跳过PCD、保留故障/newborn主键、拒绝标签文件，以及合成冻结npz通过真实native ego tracker。

CLI help与git diff whitespace检查通过。已有16+4旧测试按委托不重复执行。native依赖有已存在的NumPy/quaternion弃用提示；损坏空payload用例触发loadtxt无数据提示，测试确认最终按故障处理。

没有需要用户裁决的新增问题。正式清单、离线接收车排除攻击身份、声明假层与不可构造统计由主会话绑定；Task1没有自行选择实际数据角色。

## 独立审核后定点修复

审核指出空POINTS字段会在取第0项时抛IndexError，超出prepare已声明的传感器故障异常范围。新增回归在修复前复现prepare中止及空字段IndexError，同时发现缺字段为KeyError、多值字段被错误接受。根因是未验证POINTS字段的基数与整数语法。

修复只将POINTS限定为恰好一个非负十进制整数。缺字段、空值、多值、非整数、负数统一抛ValueError，未扩大prepare捕获范围。新增真实损坏PCD文件经prepare的回归，确认COMPLETE结果及原主键保留，I/F均null、两资格false、input_fault=true。

定点验证在native环境执行 `python -m unittest scripts.rq1_trusted_receiver.test_run.SidecarTests.test_points_header_requires_one_nonnegative_integer scripts.rq1_trusted_receiver.test_run.SidecarTests.test_bad_points_header_preserves_prepare_fault_key scripts.rq1_trusted_receiver.test_run.SidecarTests.test_raw_zero_one_and_missing_pcd`。3项通过，1.242秒；差异空白检查通过。未重跑无关旧20项或真实效果。修复提交号见交付消息。
