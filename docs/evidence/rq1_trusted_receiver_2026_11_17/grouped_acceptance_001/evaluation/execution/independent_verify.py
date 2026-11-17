"""Read-only, stdlib audit of grouped acceptance, without threshold search.

Run with --evaluation /absolute/path/to/grouped_acceptance_001/evaluation.
Reuses only the earlier independent stdlib audit, never the method implementation.
Writes independent_verify.json and execution/result_review.md in that directory.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

METHODS = ('Local', 'LocalCount', 'LocalCond')
REMOTE = METHODS[1:]
TOL = 1e-10


def read(path):
    return json.loads(path.read_text())


def rows(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def audit(evaluation):
    started = time.monotonic()
    evaluation = evaluation.resolve()
    screen_dir = evaluation.parent
    binding = read(evaluation/'evaluate.binding.json')
    source = Path(binding['source']).resolve()
    assert source != evaluation and source not in evaluation.parents
    helper = source/'execution/independent_verify.py'
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('prior_independent_stdlib_audit', helper)
    independent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(independent)
    report = read(evaluation/'evaluate.report.json')
    screen = read(screen_dir/'screen.json')
    config = read(source/'evaluate.binding.json')['config']
    assert set(report['regimes']) == set(report['go_regimes']) == set(screen['go_regimes'])
    assert Path(read(screen_dir/'binding.json')['source_run']).resolve() == source
    candidates = read(screen_dir/'candidate_policies.json')
    errors, comparisons, maximum = [], 0, 0.

    def same(actual, expected, label):
        nonlocal comparisons, maximum
        if isinstance(actual, dict):
            for key, value in actual.items():
                if key not in expected:
                    errors.append(label+'/'+key+': missing')
                else:
                    same(value, expected[key], label+'/'+key)
        else:
            comparisons += 1
            if isinstance(actual, (float, int)) and isinstance(expected, (float, int)):
                difference = abs(actual-expected)
                maximum = max(maximum, difference)
                equal = difference <= TOL
            else:
                equal = actual == expected
            if not equal:
                errors.append(f'{label}: {actual!r} != {expected!r}')

    def mass(group, truth, predicate):
        return math.fsum(w for r, w in zip(group, independent.weights(group, truth)) if predicate(r)) if group else None

    def own(group, old_six, new_six):
        true = [r for r in group if independent.primary(r, 1)]
        result = {}
        for method in REMOTE:
            result[method] = dict(old={t: old_six[method][t]['weighted'] for t in ('true', 'false')},
                new={t: new_six[method][t]['weighted'] for t in ('true', 'false')},
                true_accept_loss=None if not true else old_six[method]['true']['weighted']['accept']-new_six[method]['true']['weighted']['accept'],
                remote_true_accept=mass(true, 1, lambda r: r['decision_reasons'][method] == 'message_support'))
            result[method]['unknown_increase'] = {t: None if new_six[method][t]['n'] == 0 else
                new_six[method][t]['weighted']['unknown']-old_six[method][t]['weighted']['unknown'] for t in ('true', 'false')}
        return result

    result = dict(schema='grouped_acceptance_independent_audit_v1', implementation='stdlib only; no method imports, scoring or threshold search',
        source=str(source), evaluation=str(evaluation), tolerance=TOL, regimes={}, prediction_rows=0,
        decision_pairs_checked=0, unchanged_input_fields_checked=0)
    for regime in screen['go_regimes']:
        old_policy = read(source/'calibration'/f'{regime}.json')
        new_policy = read(evaluation/'calibration'/f'{regime}.json')
        assert old_policy['Local'] == new_policy['Local']
        for method in REMOTE:
            assert {k: v for k, v in old_policy[method].items() if k != 'tauC'} == {k: v for k, v in new_policy[method].items() if k != 'tauC'}
            assert float(new_policy[method]['tauC']) >= float(old_policy[method]['tauC'])
            assert new_policy[method] == candidates[regime][method]
            assert float(new_policy[method]['tauC']) == float(screen['regimes'][regime]['methods'][method]['new_tauC'])
        result['regimes'][regime] = dict(thresholds={m: dict(old=old_policy[m]['tauC'], new=new_policy[m]['tauC']) for m in REMOTE})
        for split in ('cal', 'eval'):
            previous = rows(source/'predictions'/regime/f'{split}.jsonl.gz')
            revised = rows(evaluation/'predictions'/regime/f'{split}.jsonl.gz')
            old_by_key = {tuple(r['key']): r for r in previous}
            assert len(old_by_key) == len(previous) == len(revised) == len({tuple(r['key']) for r in revised})
            assert set(old_by_key) == {tuple(r['key']) for r in revised}
            transitions = {m: Counter() for m in METHODS}
            for row in revised:
                old = old_by_key[tuple(row['key'])]
                assert row['split'] == old['split'] == split
                assert row['previous_decisions'] == old['decisions']
                assert row['previous_decision_reasons'] == old['decision_reasons']
                assert set(row) == set(old) | {'previous_decisions', 'previous_decision_reasons'}
                for field in old:
                    if field not in ('decisions', 'decision_reasons'):
                        result['unchanged_input_fields_checked'] += 1
                        if row[field] != old[field]:
                            errors.append(f'{regime}/{split}/{row["key"]}/changed_input/{field}')
                for method in METHODS:
                    a, why_a, state_a = independent.decision(old, old_policy[method], method)
                    b, why_b, state_b = independent.decision(row, new_policy[method], method)
                    same((a, why_a, state_a), (old['decisions'][method], old['decision_reasons'][method], old['local_state']), regime+'/'+split+'/old_decision')
                    same((b, why_b, state_b), (row['decisions'][method], row['decision_reasons'][method], row['local_state']), regime+'/'+split+'/new_decision')
                    assert a == b or (a, b) == ('accept', 'unknown')
                    assert a != 'reject' or b == 'reject'
                    assert method != 'Local' or (a, why_a) == (b, why_b)
                    transitions[method][a+'/'+b] += 1
                    result['decision_pairs_checked'] += 1
            result['prediction_rows'] += len(revised)
            old_six, new_six = independent.six(previous), independent.six(revised)
            saved = report['regimes'][regime][split]
            same(new_six, saved['system_query'], regime+'/'+split+'/six')
            comparison = own(revised, old_six, new_six)
            same(comparison, saved['own_comparison'], regime+'/'+split+'/own')
            measured = dict(system_query=new_six, old_system_query=old_six, own_comparison=comparison,
                family_k={}, row_count=len(revised), transitions={m: dict(v) for m, v in transitions.items()}, by_group={})
            spec_regime = config['regimes'][regime]
            for family in spec_regime[split+'_families']:
                for k in config['required_k']:
                    group = [r for r in revised if (r['family'], r['attack_k']) == (family, k)]
                    false = [r for r in group if independent.primary(r, 0)]
                    layer = family+'/'+str(k)
                    measured['family_k'][layer] = dict(status='observed' if false else 'not_tested',
                        support=independent.support(false), metrics=independent.six(group))
            same(measured['family_k'], saved['family_k'], regime+'/'+split+'/layers')
            false = [r for r in revised if independent.primary(r, 0)]
            groups = defaultdict(list)
            for row in false:
                groups[row['family']+'/'+str(row['attack_k'])+'/'+row['parent']].append(row)
            for name, group in groups.items():
                rates = {m: dict(false_accept=mass(group, 0, lambda r: r['decisions'][m] == 'accept'),
                    old_false_accept=mass(group, 0, lambda r: r['previous_decisions'][m] == 'accept'),
                    unknown_increase=mass(group, 0, lambda r: r['decisions'][m] == 'unknown')-mass(group, 0, lambda r: r['previous_decisions'][m] == 'unknown')) for m in REMOTE}
                measured['by_group'][name] = rates
                for method, values in rates.items():
                    expected = saved['by_group']['groups'][name]['methods'][method]
                    same(values, dict(false_accept=expected['new']['false']['accept'], old_false_accept=expected['old']['false']['accept'], unknown_increase=expected['unknown_increase']['false']), regime+'/'+split+'/'+name+'/'+method)
            measured['worst_group_FA'] = {m: max((v[m]['false_accept'] for v in measured['by_group'].values()), default=None) for m in REMOTE}
            same({m: dict(false_accept=v) for m, v in measured['worst_group_FA'].items()}, saved['by_group']['worst'], regime+'/'+split+'/worst')
            if split == 'cal':
                screen_methods = {}
                true = [r for r in revised if independent.primary(r, 1)]
                risk_groups = dict(overall=false)
                for layer in measured['family_k']:
                    risk_groups[layer] = [r for r in false if r['family']+'/'+str(r['attack_k']) == layer]
                risk_groups.update(groups)
                for method in REMOTE:
                    expected = screen['regimes'][regime]['methods'][method]
                    actual = {}
                    for version, decisions, reasons in (('old', 'previous_decisions', 'previous_decision_reasons'), ('new', 'decisions', 'decision_reasons')):
                        actual[version] = dict(true_accept=mass(true, 1, lambda r: r[decisions][method] == 'accept'),
                            remote_true_accept=mass(true, 1, lambda r: r[reasons][method] == 'message_support'),
                            false_accept={name: mass(group, 0, lambda r: r[decisions][method] == 'accept') for name, group in risk_groups.items()})
                    fixed = {name: mass(group, 0, lambda r: r['previous_decisions'][method] == 'accept' and r['previous_decision_reasons'][method] != 'message_support') for name, group in risk_groups.items()}
                    missing = [name for name in measured['family_k'] if not risk_groups[name]]
                    loss = actual['old']['true_accept']-actual['new']['true_accept']
                    checks = dict(risk=not missing and all(x is not None and x <= .05+1e-12 for x in actual['new']['false_accept'].values()),
                        true_accept_loss=loss <= .02+1e-12, remote_true_accept=actual['new']['remote_true_accept'] > 0,
                        local_feasible=all(x is None or x <= .05+1e-12 for x in fixed.values()), false_coverage=not missing)
                    actual.update(true_accept_loss=loss, checks=checks, go=all(checks.values()), local_false_accept=fixed, missing_layers=missing)
                    same(actual, expected, regime+'/cal_screen/'+method)
                    screen_methods[method] = dict(go=actual['go'], true_accept_loss=loss,
                        worst_group_FA=measured['worst_group_FA'][method], remote_true_accept=actual['new']['remote_true_accept'])
                same(all(v['go'] for v in screen_methods.values()), screen['regimes'][regime]['go'], regime+'/cal_screen/regime_go')
                measured['cal_screen'] = screen_methods
            else:
                measured['paired_timeliness'] = {m: independent.paired(revised, m) for m in ('Local', 'LocalCond')}
                same(measured['paired_timeliness'], saved['paired_timeliness'], regime+'/eval/paired')
            result['regimes'][regime][split] = measured
            del previous, revised, old_by_key
        ev = result['regimes'][regime]['eval']
        conditional = independent.verdict(ev, new_policy, config['criteria'])['LocalCond']
        checks = dict(conditional['checks'])
        for method in REMOTE:
            checks['own_TA_loss_'+method] = independent.check(ev['own_comparison'][method]['true_accept_loss'], .02)
            remote = ev['own_comparison'][method]['remote_true_accept']
            checks['remote_TA_'+method] = dict(status='insufficient' if remote is None else 'pass' if remote > 0 else 'fail', value=remote, requirement='positive')
            checks['TR_'+method] = independent.check(ev['system_query'][method]['true']['weighted']['reject'], config['criteria']['max_TR_global'])
            checks['FA_'+method] = independent.check(ev['system_query'][method]['false']['weighted']['accept'], config['criteria']['max_FA_global_and_layer'])
            for layer, group in ev['family_k'].items():
                checks['FA_'+method+'_'+layer] = independent.check(group['metrics'][method]['false']['weighted']['accept'], config['criteria']['max_FA_global_and_layer'])
        statuses = {v['status'] for v in checks.values()}
        verdict = dict(status='not_retained' if 'fail' in statuses else 'evidence_insufficient' if 'insufficient' in statuses else 'retained',
            checks=checks, conditional_comparison=conditional, Local_reference='descriptive_only')
        same(verdict, report['regimes'][regime]['verdict'], regime+'/final_verdict')
        result['regimes'][regime]['verdict'] = verdict
        result['regimes'][regime]['failed_checks'] = [k for k, v in checks.items() if v['status'] == 'fail']
    result.update(status='PASS' if not errors else 'FAIL', errors=errors[:30], error_count=len(errors), compared_scalar_fields=comparisons,
        max_absolute_numeric_difference=maximum, seconds=time.monotonic()-started,
        audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        independent_helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
        source_report_sha256=hashlib.sha256((evaluation/'evaluate.report.json').read_bytes()).hexdigest(),
        not_checked=['PCD/geometry', 'upstream models and C/R recomputation', 'original labels', 'threshold optimality or new calibration', 'blind-test or population guarantees'])
    (evaluation/'independent_verify.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    markdown = ['# 分组采纳约束开发结果独立复核', '', '2026-11-17。标准库独立复核'+result['status']+'。三个配置的最终裁决均为 not_retained，旧 run_002 结论保留。', '',
        '审计按主键逐行比对原运行和新运行，核对全部原始字段、分数及资格不变，只提高 tauC；独立复现新旧决定及原因，确认只允许采纳转未知，全部拒绝保留。没有修改源文件、搜索门限、重做校准或运行几何与模型。', '',
        f'核对 {result["prediction_rows"]} 条跨配置 cal/eval 记录、{result["decision_pairs_checked"]} 组方法新旧决定、{result["unchanged_input_fields_checked"]} 个保留输入字段。时间点和派生配置不是独立样本。数值容差 {TOL:g}，最大差 {maximum:.3g}，错误 {len(errors)}。', '',
        '## 评价结论', '', '| 配置 | Cond旧FA | 新FA | Cond旧TA | 新TA | Cond自身TA损失 | Count自身TA损失 | 新Cond相对新Count CD增益 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for regime, item in result['regimes'].items():
        ev = item['eval']; c = ev['system_query']['LocalCond']; old = ev['old_system_query']['LocalCond']; b = ev['system_query']['LocalCount']
        values = [old['false']['weighted']['accept'], c['false']['weighted']['accept'], old['true']['weighted']['accept'], c['true']['weighted']['accept'],
            ev['own_comparison']['LocalCond']['true_accept_loss'], ev['own_comparison']['LocalCount']['true_accept_loss'], c['correct_definite']-b['correct_definite']]
        markdown.append('| '+regime+' | '+' | '.join(f'{100*v:.4f}'+('%' if i < 4 else '个百分点') for i, v in enumerate(values))+' |')
    markdown += ['', '所有表格和裁决按完整主真假、原层/父/query epoch/时刻权重独立重计。Local 只作描述基线，没有将其相对增益失败算作候选失败。']
    for regime, item in result['regimes'].items():
        ev = item['eval']; layer_risks = {k: v['metrics']['LocalCond']['false']['weighted']['accept'] for k, v in ev['family_k'].items()}
        excessive = ', '.join(f'{k} 为 {100*v:.4f}%' for k, v in layer_risks.items() if v is not None and v > .05+1e-12)
        markdown += ['', regime+' 的失败检查为 '+', '.join(item['failed_checks'])+'。'+('Cond超限层 '+excessive+'。' if excessive else 'Cond各声明层假采纳未超5%，仍因自身采用代价失败。')]
    markdown += ['', '## 校准筛选与范围', '', '| 配置 | Count cal TA损失 | Cond cal TA损失 | Count/Cond最差cal父组FA |', '| --- | ---: | ---: | ---: |']
    for regime, item in result['regimes'].items():
        cal = item['cal']['cal_screen']; a,b=cal['LocalCount'],cal['LocalCond']
        markdown.append(f'| {regime} | {100*a["true_accept_loss"]:.4f}个百分点 | {100*b["true_accept_loss"]:.4f}个百分点 | {100*a["worst_group_FA"]:.4f}% / {100*b["worst_group_FA"]:.4f}% |')
    markdown += ['', '三个配置 cal 两方法均满足完整总体、攻击层及已观察父组5%约束、自身真采纳损失不超过2个百分点、正质量远端真采纳。此次仅用已保存 cal 判决核对 screen.json，没有重新搜索门限。所有 eval 中两方法也保留正质量远端真采纳；失败不能归因于把远端采纳全部关闭。', '',
        '本次是 cal 改动后，在已看过 eval 上进行的开发验证。总体误采下降不代表各攻击层风险通过，cal 通过不保证跨父采用代价达标。新增未知不得称为成功拒绝。此次结果不支持替换完整方法，也不否定已有条件反证的有限增益；不增加多车依赖或新父总体风险保证。', '',
        '可复现命令', '', '```bash', f'python {Path(__file__).resolve()} --evaluation {evaluation}', '```', '',
        '审计复用 run_002/execution/independent_verify.py 中已独立编写的标准库统计与判决函数。没有导入项目方法实现。复核范围不包括原始标签、上游分数重算、PCD几何、门限最优性或盲测保证。']
    (evaluation/'execution/result_review.md').write_text('\n'.join(markdown)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'prediction_rows', 'decision_pairs_checked', 'compared_scalar_fields', 'max_absolute_numeric_difference', 'error_count', 'seconds')}, ensure_ascii=False))
    for regime, item in result['regimes'].items():
        print(regime, item['verdict']['status'], json.dumps(item['failed_checks']))
    if errors:
        print('\n'.join(errors[:10]))
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation', type=Path, required=True)
    audit(parser.parse_args().evaluation)
