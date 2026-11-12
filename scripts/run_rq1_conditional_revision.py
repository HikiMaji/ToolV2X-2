"""One frozen conditional mechanism batch. Run only after independent code review."""
import argparse
import itertools
import json
import math
import subprocess
import time
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from rq1_conditional_revision import (METHODS, REFERENCE, STATES, TOL, actual_false_probability,
                                      cue_distribution, decide, evaluate_policy, false_probabilities,
                                      fit_policy, score_methods, true_logprob)

BUDGETS = (.01, .05, .10)
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / 'docs/evidence/rq1_conditional_revision_2026_11_11/run_001'
# A worktree lives below .worktrees/<name>; ordinary checkouts use their own root.
CODE_ROOT = Path(__file__).resolve().parents[1]
if CODE_ROOT.parent.name != '.worktrees':
    DEFAULT_OUTPUT = CODE_ROOT / 'docs/evidence/rq1_conditional_revision_2026_11_11/run_001'
STRATA = ('N', 'layout', 'quality', 'peer_count', 'C_type', 'pattern')


def build_base_contexts():
    contexts = []
    for n in (2, 3, 4):
        peers = tuple(range(1, n))
        layouts = [('independent', tuple((i,) for i in peers))]
        if n >= 3:
            layouts.append(('shared', (peers,)))
        if n == 4:
            layouts.append(('split', ((1, 2), (3,))))
        block = []
        for layout, groups in layouts:
            for quality in ('high', 'heterogeneous'):
                clear = {i: .9 if quality == 'high' or i % 2 == 0 else .65 for i in peers}
                blocked = {i: .1 if quality == 'high' or i % 2 == 0 else .05 for i in peers}
                masks = (tuple(range(n)), tuple(range(n - 1)), (0,))
                for observed in dict.fromkeys(masks):
                    block.append({'N': n, 'anchor': 0, 'groups': groups, 'layout': layout,
                                  'quality': quality, 'observed': observed, 'p_clear': clear,
                                  'p_blocked': blocked, 'peer_count': len(observed) - 1})
        for context in block:
            contexts.append({**context, 'base_id': len(contexts), 'base_weight': 1 / (3 * len(block))})
    return contexts


def build_rows(base, reference_params, generation_params, attack_override=None):
    rows = []
    for item in base:
        groups = item['groups']
        registered = tuple(i for group in groups for i in group)
        peers = [i for i in item['observed'] if i != item['anchor']]
        # All registered groups emit C before masking, including wholly hidden groups.
        for cues, cue_prob in cue_distribution(groups, generation_params['theta'], generation_params['accuracy']):
            context = {**item, 'C': cues}
            context_id = f"{item['base_id']}:" + ''.join(map(str, cues))
            weight = item['base_weight'] * cue_prob
            totals = [0.] * 6
            for bits in itertools.product((0, 1), repeat=len(peers)):
                events = {item['anchor']: 1, **dict(zip(peers, bits))}
                pt = math.exp(true_logprob(events, groups, item['p_clear'], item['p_blocked'],
                                           generation_params['theta'], generation_params['accuracy'], cues, True, True))
                pf = false_probabilities(events, registered)
                pattern = ('no_peer' if not bits else 'all_report' if all(bits) else
                           'all_unreported' if not any(bits) else 'mixed')
                row = {**context, 'context_id': context_id, 'cue_prob': cue_prob, 'context_weight': weight,
                       'C_type': 'all_clear' if all(cues) else 'all_blocked' if not any(cues) else 'mixed',
                       'events': events, 'eligible': bool(peers), 'pattern': pattern,
                       'probT': pt, 'probFk': pf, 'wT': weight * pt, 'wFk': [weight * p for p in pf],
                       'scores': score_methods(context, events, reference_params)}
                totals[0] += pt
                for k, p in enumerate(pf):
                    totals[k + 1] += p
                if attack_override is not None:
                    actual = actual_false_probability(events, registered, attack_override)
                    row.update(probActualF=actual, wActualF=weight * actual)
                    totals[5] += actual
                rows.append(row)
            expected_totals = totals if attack_override is not None else totals[:5]
            if any(abs(total - 1) > TOL for total in expected_totals):
                raise ArithmeticError('within-context class probabilities must sum to one')
    keys = [('true', sum(r['wT'] for r in rows))]
    keys.extend((f'F{k + 1}', sum(r['wFk'][k] for r in rows)) for k in range(4))
    if attack_override is not None:
        keys.append(('actual_F', sum(r['wActualF'] for r in rows)))
    if any(abs(total - 1) > TOL for _, total in keys):
        raise ArithmeticError('global class weights must sum to one')
    return rows


def stress_configs():
    return ([{'name': f'a_{a}', 'generation': {**REFERENCE, 'accuracy': a}} for a in (.6, .95)] +
            [{'name': f'theta_{t}', 'generation': {**REFERENCE, 'theta': t}} for t in (.6, .95)] +
            [{'name': f'r_{r}', 'generation': dict(REFERENCE), 'attack': {'kind': 'independent', 'r': r}}
             for r in (.05, .3, .6)] +
            [{'name': 'partial', 'generation': dict(REFERENCE), 'attack': {'kind': 'partial'},
              'note': 'Choose one registered peer before mask; N2 reduces to full coordination.'}])


def report(rows, policies, event_conditioned=False):
    return {method: {scope: evaluate_policy(rows, method, policy, scope == 'eligible', event_conditioned)
                     for scope in ('system', 'eligible')} for method, policy in policies.items()}


def summarize_strata(rows, policies):
    return {'overall': report(rows, policies), 'strata': {
        field: {str(value): report([r for r in rows if r[field] == value], policies, field == 'pattern')
                for value in sorted({r[field] for r in rows}, key=str)} for field in STRATA}}


def summarize_stress(rows, policies, config):
    result = {'config': config, 'report': summarize_strata(rows, policies), 'actual_risk': {}}
    for method in METHODS:
        metrics = result['report']['overall'][method]['eligible']
        false_key = 'actual_F' if config.get('attack') else 'Q_F'
        t, f = metrics['true']['rates'], metrics[false_key]['rates']
        result['actual_risk'][method] = {'false_distribution': false_key,
                                          'false_adopt': f['adopt'], 'true_reject': t['reject'],
                                          'false_unknown': f['unknown'], 'true_unknown': t['unknown'],
                                          'max_error': max(f['adopt'], t['reject']),
                                          'exceeds_5_percent': max(f['adopt'], t['reject']) > .05 + TOL}
    return result


def transitions(rows, policies):
    result = {}
    for original in ('Ic', 'JcF', 'J0'):
        tables = {}
        for pattern in ('all_report', 'all_unreported', 'mixed', 'no_peer'):
            part = [r for r in rows if r['pattern'] == pattern]
            denominators = {'true': sum(r['wT'] for r in part),
                            'Q_F': sum(sum(r['wFk']) / 4 for r in part)}
            cells = {f'{a}_to_{b}': {'true': 0., 'Q_F': 0.} for a, b in itertools.product(STATES, repeat=2)}
            for row in part:
                states = [decide(row['scores'][m]['score'], row['scores'][m]['supported'], row['eligible'], policies[m])
                          for m in (original, 'Jc')]
                cell = cells[f'{states[0]}_to_{states[1]}']
                cell['true'] += row['wT']
                cell['Q_F'] += sum(row['wFk']) / 4
            tables[pattern] = {'denominators': denominators,
                               'cells': {key: {'masses': mass,
                                               'rates': {t: mass[t] / d if d else None for t, d in denominators.items()}}
                                         for key, mass in cells.items()}}
        result[f'{original}_to_Jc'] = tables
    return result


def fixed_examples(rows, policies):
    return [{**row, 'decisions': {m: decide(row['scores'][m]['score'], row['scores'][m]['supported'], row['eligible'], policies[m])
                                for m in METHODS}}
            for row in rows if row['N'] == 4 and row['layout'] in ('shared', 'split') and row['peer_count'] == 3]


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            raise ValueError('NaN is forbidden in experiment output')
        return '+inf' if value > 0 else '-inf'
    if isinstance(value, dict):
        return {key: json_safe(v) for key, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    return value


def save_json(path, value):
    Path(path).write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepare_output(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f'refusing to overwrite nonempty output: {path}')
    path.mkdir(parents=True, exist_ok=True)


def plot_results(output, frontiers, stress):
    fig, ax = plt.subplots(figsize=(7, 4))
    for method in METHODS:
        points = frontiers[method]
        x = [p['metrics']['max_error'] for p in points]
        y = [p['metrics']['correct_clear'] for p in points]
        ax.plot(x, y, marker='o', label=method + (' (robust calibration)' if method == 'Ec' else ''))
    ax.set(xlabel='Maximum mixed-distribution class error (eligible)', ylabel='Mean correct clear decision',
           title='Declared synthetic distribution; Ec calibrated conservatively')
    ax.legend(fontsize=8)
    fig.tight_layout()
    for extension in ('png', 'svg'):
        fig.savefig(output / f'main_frontier.{extension}', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 4))
    for method in METHODS:
        ax.plot(range(len(stress)), [s['actual_risk'][method]['max_error'] for s in stress], marker='.', label=method)
    ax.axhline(.05, color='black', linestyle='--', linewidth=1)
    ax.set_xticks(range(len(stress)))
    ax.set_xticklabels([s['config']['name'] for s in stress], rotation=45, ha='right')
    ax.set(ylabel='Maximum actual class error (eligible)', title='Frozen 5% policies; actual stress distributions')
    ax.legend(ncol=4)
    fig.tight_layout()
    for extension in ('png', 'svg'):
        fig.savefig(output / f'stress_risk.{extension}', dpi=160)
    plt.close(fig)


def summary_text(config, frontiers, strata, stress, common_policy):
    main = {m: frontiers[m][1]['metrics'] for m in METHODS}
    lines = ['# 条件联合核验固定机制结果', '',
             '本表只评价声明的受控分布。参数与C误差率不是车辆实测，也没有验证时间状态或缓存迁移。', '',
             f"来源提交 `{config['source_commit']}`，34个base、128个带C context、460个模式，均非独立实测样本。", '',
             '主5%工作点。Ec的校准风险和保守正确明确率单列，其余方法按四族等权混合。', '',
             '|方法|真采纳|真未知|真拒绝|混合假采纳|混合假未知|混合假拒绝|正确明确率|context最坏假采纳|保守正确明确率|预算满足|',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    def fmt(x):
        return 'null' if x is None else f'{100 * x:.4f}%'
    for m, v in main.items():
        t, f = v['true']['rates'], v['Q_F']['rates']
        calibration_false = v['context_worst_false_adopt'] if m == 'Ec' else f['adopt']
        valid = max(t['reject'], calibration_false) <= .05 + TOL
        values = [t[s] for s in STATES] + [f[s] for s in STATES] + [v['correct_clear'], v['context_worst_false_adopt'], v['conservative_correct_clear']]
        lines.append('|' + m + '|' + '|'.join(map(fmt, values)) + '|' + ('是' if valid else '否') + '|')
    lines += ['', '1%和10%工作点完整保存在main_frontier.json；系统与eligible六格、单族及max-context风险见main_strata.json。', '',
              '|方法|F1假采纳|F2假采纳|F3假采纳|F4假采纳|单context最高假采纳|', '|---|---:|---:|---:|---:|---:|']
    for m, v in main.items():
        lines.append('|' + m + '|' + '|'.join(fmt(f['rates']['adopt']) for f in v['Fk']) + '|' + fmt(v['max_context_false_adopt']) + '|')
    lines += ['', '共同政策使用Ic主5%门限。该比较只改变评分。', '', '|评分|真误拒|混合假采纳|正确明确率|', '|---|---:|---:|---:|']
    for m, v in common_policy.items():
        lines.append(f"|{m}|{fmt(v['true']['rates']['reject'])}|{fmt(v['Q_F']['rates']['adopt'])}|{fmt(v['correct_clear'])}|")
    lines += ['', '冻结压力使用实际生成分布。a/theta使用实际C加权Q_F，r/partial使用actual_F。', '',
              '|压力|方法|实际假采纳|真误拒|实际假未知|真未知|超5%|', '|---|---|---:|---:|---:|---:|---|']
    for s in stress:
        for m, v in s['actual_risk'].items():
            lines.append(f"|{s['config']['name']}|{m}|{fmt(v['false_adopt'])}|{fmt(v['true_reject'])}|{fmt(v['false_unknown'])}|{fmt(v['true_unknown'])}|{'是' if v['exceeds_5_percent'] else '否'}|")
    jc = main['Jc']
    comparisons = {m: jc['correct_clear'] > main[m]['correct_clear'] + TOL for m in ('Ic', 'Gc', 'JcF', 'J0')}
    lines += ['', '本批预定条件决定', '']
    valid = max(jc['true']['rates']['reject'], jc['Q_F']['rates']['adopt']) <= .05 + TOL
    lines.append('- ' + ('保留本版条件联合kernel。' if valid and comparisons['Ic'] and comparisons['Gc'] else
                         '本版尚未达到相对Ic/Gc的预定保留条件，撤下其已获收益的主张。'))
    lines.append('- ' + ('本批支持正常侧残余依赖的条件增量。' if comparisons['JcF'] else
                         '撤下本版正常侧残余依赖增益主张，Jc未超过JcF。'))
    lines.append('- ' + ('Jc相对J0具有条件收益。' if comparisons['J0'] else
                         'Jc相对J0无条件收益，不继续扩大本版噪声条件模块。'))
    lines.append('- 单族或压力超预算只支持参考混合效用，不支持该攻击下稳健性。Ec的低错误须同时检查未知代价。')
    lines.append('- 当前仅完成受控kernel机制。C合法接入与参数来源未解决，不自动进入车辆缓存迁移。')
    lines += ['', f"运行耗时{config['elapsed_seconds']:.3f}秒。新生成过程与旧39.49%结果不能直接比较。", '']
    return '\n'.join(lines)


def run(output):
    started = time.monotonic()
    output = Path(output).resolve()
    prepare_output(output)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=CODE_ROOT, text=True).strip()
    base = build_base_contexts()
    rows = build_rows(base, REFERENCE, REFERENCE)
    counts = {'base': len(base), 'contexts': len({r['context_id'] for r in rows}), 'rows': len(rows)}
    if counts != {'base': 34, 'contexts': 128, 'rows': 460}:
        raise ArithmeticError('frozen enumeration changed')
    if abs(sum(r['wT'] for r in rows if r['eligible']) - 11 / 18) > TOL:
        raise ArithmeticError('eligible denominator changed')
    frontiers = {m: [fit_policy(rows, m, e, robust=m == 'Ec') for e in BUDGETS] for m in METHODS}
    policies = {m: frontiers[m][1]['policy'] for m in METHODS}
    strata = summarize_strata(rows, policies)
    common = {m: evaluate_policy(rows, m, policies['Ic'], True) for m in ('Ic', 'Jc')}
    stress = [summarize_stress(build_rows(base, REFERENCE, c['generation'], c.get('attack')), policies, c)
              for c in stress_configs()]
    config = {'source_commit': commit, 'code_root': str(CODE_ROOT), 'reference_params': dict(REFERENCE),
              'generation_params': dict(REFERENCE), 'false_rates': [.1, .2, .4], 'false_weights': [.25] * 4,
              'F4': 'all registered peers always report conditional on anchor report', 'budgets': BUDGETS,
              'score_decimals': 12, 'counts': counts, 'stress_configs': stress_configs(),
              'eligibility': 'at least one observed non-anchor event', 'parameters_are_declared': True,
              'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=CODE_ROOT, text=True).strip())}
    with (output / 'main_rows.jsonl').open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(json_safe(row), ensure_ascii=False, allow_nan=False) + '\n')
    save_json(output / 'main_frontier.json', {'frontiers': frontiers, 'common_Ic_policy': common})
    save_json(output / 'main_strata.json', strata)
    save_json(output / 'stress_summary.json', stress)
    save_json(output / 'transitions.json', transitions(rows, policies))
    save_json(output / 'examples.json', fixed_examples(rows, policies))
    plot_results(output, frontiers, stress)
    config['elapsed_seconds'] = time.monotonic() - started
    save_json(output / 'config.json', config)
    (output / 'summary.md').write_text(summary_text(config, frontiers, strata, stress, common), encoding='utf-8')
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({'output': str(args.output.resolve()), 'source_commit': result['source_commit'],
                      'elapsed_seconds': result['elapsed_seconds']}, ensure_ascii=False))
