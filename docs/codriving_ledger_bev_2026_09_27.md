# Stage 2 续接：已购证据转换与录制时标核对

2026-09-27。本批完成 **可信 ledger → P/F 规范记录 → 既有 BEV** 的接口及契约检查，并核对 Town05-11 录制时标。没有运行检测/MTR/规划器、训练或闭环。真实 CoDriving peer 检测跟踪 → receipt → 输入整链仍未完成。

## 修改与验证

- `src/planning/codriving_ledger_bev.py` 新增 `records_from_ledger(ledger, binding)`。返回可供 `rasterize_pf` 使用的 P/F 记录；绑定要求 scene/g、decision_time、time_binding、ego actor 原点与 x-forward/y-left。
- 对已有 receipt 重新解码 wire，核对 response、ID、scene/g、通信字节数；acquired 字段必须匹配解码值及 receipt。复用 `known_field_manifest` 和已有 decoder，不新建服务/认证体系。
- 只消费 acquired 字段；本地 derived forecast 不成为远端 F。P 不执行预测器。
- 速度使用已购历史末两个 valid 状态和真实相对间隔，语义为 causal tracking-state motion proxy。F 的 refs 包含 anchor/history/forecast，不能在通信核算时删除 history 的代价。
- 新增 `tests/test_codriving_ledger_bev.py` 六项测试并注册 `scripts/check_review.py`。测试覆盖付费 PF 十通道转换、P 不调用预测器、F 缺历史拒绝、内容/时空绑定篡改拒绝、派生结果不算远端 F、有效历史存在间隙时的速度数值。
- 首次新增测试因模块未实现而失败，随后实现通过；新增与原 BEV 合计17项通过。主目录受影响回归 **94项通过，0.850秒**，包括 ledger、v1 vehicle tools、task spec；日志在 `docs/evidence/codriving_ledger_bev_2026_09_27/tests.log`。本批未再运行完整资源独立套件。
- 独立只读审查执行初版5项检查通过，没有提出阻塞缺陷；建议的间隙速度测试已补充。审查确认这里不是 F-only 完整路径，也不验证调用者坐标声明真实性。

所有测试中的预测器均为合成契约 fixture，不是模型效果证据。main 新增文件与 worktree 同步，未提交/推送。CoDriving 原配置、权重和主干未修改。

## 实际录制时间核对

读取 `routes_town05_11_w0_04_30_23_14_33/log/args.json`，采集配置记录指向 `data_collection/yamls/weather-0.yaml`。本地官方源码该配置 save_skip_frames=4、仿真20Hz；保存函数用 step // save_skip_frames 编号。CoDriving 默认 skip_frames=1，输出下一批连续10个保存帧。

使用本车 measurement 的 x/y/speed 做**离线时标一致性核对**：仅连续文件号、平均速度>2m/s、端点速度差<0.5m/s。车0共161个measurement、21对入选，位移/平均速度的5/50/95分位=0.19469/0.20151/0.20786秒；车1共160条、55对，0.19722/0.20064/0.20325秒。支持本路线以 **0.2秒保存间隔、0.2…2.0秒十点输出**推进适配。

这是采集配置加运动一致性支持，不是逐帧timestamp认证；保存记录没有timestamp。不得推广为所有天气/路线均相同。读到的JSON还有future_waypoints等标签，但审计只取x/y/speed，不把该离线核对接入在线输入。脚本及结果见同名evidence目录 `audit_timebase.py` / `timebase.json`。

## 本批决定、限制与下一步

1. Ruling：保留旧wire及黄金测试；不把0.2秒原生历史伪称0.1秒。当前旧decoder明确要求11个历史点为−1…0秒、0.1秒间隔。因此新适配器目前是**既有合法ledger兼容接口**，不是原生CoDriving时序协议已经完成。后续需版本化原生时间轴；如果MTR需要0.1秒，重采样只发生在显式预测输入适配中，并保存来源/有效性。选错时间适配会破坏速度和预测，必须另有测试。
2. Ruling：F缺已购历史时拒绝公平F-CV构造。当前可支持购买P+F后的成对比较，不能称独立F-only，也不偷偷读取peer速度。下一步优先让新版本F返回最小因果运动锚点（当前速度、有效性、来源），按最终wire计费，并让F/F-CV共享相同目标与锚点；无需为F-only强制购买完整P。该新wire本批尚未实现。
3. binding是可信调用者对固定当前ego坐标/时刻的声明，不是标定证明；不能把逐帧各自ego系历史直接差分。实际peer到ego变换、实体关联还需真实样本验收。
4. 不扩训练，不将合成测试称作协作收益；旧sidecar仍未被原planner消费。
5. 原9月22日native LiDAR原始目录当前不存在，虽有跟踪归档，不能假装可重新读取完整标定。后续使用现有Town05公开录制接入本车/peer因果感知，而非重启旧PDM控制路线。

下一批工作收敛为：**原生时序与F运动锚点的版本化接口 → 一段Town05真实peer因果检测/跟踪 → P/真实F/F-CV同网格样本**。之后才做planner输入层适配与共同训练；本批不支持P/F已改善规划的结论。
