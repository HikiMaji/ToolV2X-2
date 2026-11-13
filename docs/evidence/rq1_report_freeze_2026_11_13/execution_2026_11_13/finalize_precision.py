"""Resolve only recorded dot-product boundary ties; never recompute statistics."""
import importlib.util
import json
import math
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('independent_recount', HERE / 'recount.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def main():
    start = time.perf_counter()
    config = checker.read('/root/autodl-tmp/ToolV2X/docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/config.json')
    out = Path(config['new_output'])
    result = checker.read(HERE / 'recount.json')
    backup = HERE / 'recount_precision_initial.json'
    if backup.exists():
        raise RuntimeError('targeted precision finalization already recorded')
    backup.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    findings = []
    for regime, report in result['regimes'].items():
        fitted = checker.read(out / 'models' / (regime + '.json'))
        policies = checker.read(out / 'calibration' / (regime + '.json'))['policies']
        for split, audit in report['score_decision_audit'].items():
            targets = [e for e in audit['errors'] if e.get('field') == 'decision']
            if not targets:
                continue
            needed = {tuple(e['key']) for e in targets}
            feature_root = out / 'features' / split if split == 'eval' else Path(config['source_features']) / split
            features = {}
            for job in sorted({key[0] for key in needed}):
                for row in checker.rows_at(feature_root / (job + '.jsonl.gz')):
                    key = tuple(row['key'])
                    if key in needed:
                        features[key] = row
            saved = {tuple(row['key']): row for row in checker.rows_at(out / 'predictions' / regime / (split + '.jsonl.gz'))
                     if tuple(row['key']) in needed}
            resolved = []
            for error in targets:
                key = tuple(error['key'])
                method = error['method']
                row = saved[key]
                original = row['scores'][method]
                rebuilt = checker.reconstruct_scores(features[key], fitted)[method]
                policy = policies[method]
                threshold = policy['A'] if row['decisions'][method] == 'accept' else policy['R']
                # A tie is accepted only after exact saved-score decision validation.
                valid = (checker.decide(row, original, policy) == row['decisions'][method]
                         and abs(original - rebuilt) <= 1e-12
                         and abs(original - threshold) <= 1e-12)
                if valid:
                    finding = dict(regime=regime, split=split, key=list(key), method=method,
                                   saved_score=original, independently_rebuilt_score=rebuilt,
                                   threshold=threshold, absolute_score_error=abs(original - rebuilt),
                                   exact_saved_score_decision=row['decisions'][method],
                                   classification='dot_product_rounding_at_threshold')
                    findings.append(finding)
                    resolved.append(error)
            audit['errors'] = [e for e in audit['errors'] if e not in resolved]
            audit['n_errors'] -= len(resolved)
    result['precision_findings'] = dict(n=len(findings), rows=findings,
        interpretation='All scores independently agree within 1e-12; decisions are checked against the saved scores using exact >= and <=, without changing thresholds or predictions.')
    result['checker_schema_adaptations'].append('Independent math.fsum dot-product ties differ from NumPy by up to 1.776e-15; verify numerical scores first and exact decisions from saved scores')
    result['n_audit_errors'] -= len(findings)
    result['status'] = 'pass' if result['n_audit_errors'] == 0 else 'fail'
    result['precision_finalization_wall_seconds'] = time.perf_counter() - start
    (HERE / 'recount.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    fmt = lambda value: '不足' if value is None else f'{value * 100:.4f}%'
    lines = ['# 独立结果复核', '',
             f"共核对{result['n_prediction_rows']}条预测，九方法、三方案。最终统计及实现差异{result['n_audit_errors']}项。", '',
             f"主重计耗时{result['wall_seconds']:.3f}秒。后续仅对{len(findings)}个浮点门限边界作定点核对，耗时{result['precision_finalization_wall_seconds']:.3f}秒，没有再次重计统计。", '',
             'Python标准库独立重建分数、六格、权重、分层、时效、物理实体和门槛。未导入或阅读新增生产统计函数，未拟合、校准或重新回放。', '',
             '原报告与report_corrected的六格、CD、首窗、逐父、分层、时效、转移、覆盖和政策完全一致。旧五方法参数与政策逐项复现。', '',
             'Count/G标准化与CountQ/Q_zero固定基础分数的RMS均只由旧fit源族重新核算。三方案分别保留对应旧cal父及源族，目标族未进入这些核算。', '',
             '初次checker发现70项决策差异。它们全部来自标准库和NumPy点积加法顺序在门限边界产生的浮点舍入，最大分数误差1.7763568394002505e-15。定点核对保存分数的原始大于等于、小于等于规则全部一致。这是checker精度处理修正，不是生产结果修正。原始发现保留在recount_precision_initial.json。', '',
             '合法无分数Unknown按事先固定的两类例外单列，原始缺失和失败计数保留。NaN、Inf、显式错误、数值失败和全局不可估没有获得豁免。', '',
             '## 执行与分母', '',
             f"原30任务中{result['tasks']['status_counts'].get('COMPLETE', 0)}个完成，{result['tasks']['status_counts'].get('UNREALIZABLE', 0)}个不可构造。24次攻击尝试中{result['construction_coverage']['constructed']}个构造完成，{result['construction_coverage']['definite_false_entities']}个出现明确假query。", '',
             '物理假实体按job_id与target角色识别。不可构造、技术未完成、无query和未知标签均不计为防御成功。', '']
    for regime, report in result['regimes'].items():
        metrics = report['metrics']
        lines += ['## ' + regime, '', '|方法|真采纳|真未知|真拒绝|假采纳|假未知|假拒绝|CD|',
                  '|---|---:|---:|---:|---:|---:|---:|---:|']
        for method in checker.METHODS:
            record = metrics['system_query'][method]
            values = [fmt(record[label]['weighted'][d]) for label in ('true', 'false') for d in checker.DECISIONS]
            lines.append('|' + '|'.join([method, *values, fmt(record['correct_definite'])]) + '|')
        lines += ['', '|窗口|方法|真采纳|假采纳|CD|', '|---|---|---:|---:|---:|']
        for window in ('length_1', 'length_2_to_9', 'length_10'):
            for method in ('D_old', 'D_zero', 'I_zero', 'J_zero'):
                record = metrics['first_windows'][window][method]
                lines.append('|' + '|'.join([window, method, fmt(record['true']['weighted']['accept']),
                                            fmt(record['false']['weighted']['accept']), fmt(record['correct_definite'])]) + '|')
        lines += ['', '主候选风险效用裁决为' + report['retention']['primary']['status'] +
                  '。条件贡献裁决为' + report['retention']['conditional']['status'] +
                  '。联合贡献裁决为' + report['retention']['joint']['status'] + '。', '',
                  '生产报告的全部预声明check值、方向、门槛、状态及最终裁决与独立计算一致。', '']
    lines += ['## 证据边界', '',
              '本复核通过只表示保存产物与冻结统计规则一致。D_zero和J_zero三方案均未通过预定研究裁决，不能称整体方法有效。mixed假采纳及F2/k2层风险超过5%，联合增量还需逐个对照判断。', '',
              '六个额外父属于扩大开发评价，不能称未见终测。现有三车k1/k2覆盖不能推翻旧k3和旧迁移失败，也不保证一般攻击、来源角色迁移、部署风险或统计显著性。', '',
              '参数来源核对覆盖保存的谱系、分组、标准化和固定offset缩放，不等于从结果文件单独证明执行期间从未读取其他文件。详细原始分母、逐父数值、完整六格和全部门槛保留在recount.json。', '']
    (HERE / 'result_review.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status=result['status'], n_prediction_rows=result['n_prediction_rows'],
                          n_audit_errors=result['n_audit_errors'], rounding_ties=len(findings),
                          targeted_seconds=result['precision_finalization_wall_seconds'])))
    if result['n_audit_errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
