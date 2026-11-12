"""Frozen real-condition extraction, fitting, calibration and development report.

This adapter never replays AVstack or reads new GT. Label joining starts only
once every public per-job feature file has been closed.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
import sys
import traceback
import numpy as np

try:
    from . import geometry, model
except ImportError:
    import geometry
    import model

ROOT = Path('/root/autodl-tmp/ToolV2X')
OLD = ROOT / 'docs/evidence/rq1_static_trial_2026_11_10/run_001/manifest.json'
DEFAULT_OUT = ROOT / 'docs/evidence/rq1_real_cue_2026_11_11/run_001'


def read_jsonl(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def dump_json(path, obj):
    with open(path, 'x') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def write_jsonl(path, rows):
    with gzip.open(path, 'xt') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def source_record(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=h.hexdigest())


def code_record():
    cwd = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=cwd, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', 'scripts/rq1_real_cue'], cwd=cwd, text=True).strip()
    return dict(commit=commit, dirty=bool(dirty), files=[source_record(p) for p in sorted(Path(__file__).parent.glob('*.py'))])


def check_new(out, names):
    out.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (out / name).exists():
            raise FileExistsError('refusing to overwrite ' + str(out / name))


def parent_splits(jobs):
    eval_parents = {j['parent'] for j in jobs if j['split'] == 'eval'}
    attack = {j['parent'] for j in jobs if j['kind'] == 'attack'}
    parents = sorted({j['parent'] for j in jobs})
    splits = {p: 'eval' if p in eval_parents else 'cal' if p in attack else 'fit' for p in parents}
    if Counter(splits.values()) != Counter(fit=5, cal=4, eval=1):
        raise ValueError('expected exactly five fit/four cal/one eval parents: ' + repr(splits))
    return splits


def extract_frame(events, sender, source_ids):
    if len(set(source_ids)) != len(source_ids):
        raise ValueError('duplicate registered source')
    messages = sender['messages']
    if sorted(m['source_id'] for m in messages) != sorted(source_ids):
        raise ValueError('sender source set mismatch')
    for message in messages:
        if message['frame'] != sender['frame'] or abs(message['timestamp'] - sender['timestamp']) > 1e-8:
            raise ValueError('message time mismatch')
    queries = []
    for row in events:
        if row['source_ids'] != source_ids or row['frame'] != sender['frame'] or row['index'] != sender['index'] or abs(row['timestamp'] - sender['timestamp']) > 1e-8:
            raise ValueError('event frame/source/time mismatch')
        if len(row['U']) != len(source_ids) or len(row['X']) != len(source_ids):
            raise ValueError('event dimensions mismatch')
        g = row.get('query_geometry')
        if g is not None:
            if g['id'] != row['id']:
                raise ValueError('query ID mismatch')
            queries.append(dict(id=g['id'], xyz=g.get('xyz'), corners=g.get('corners')))
    poses = {m['source_id']: m.get('pose_xyz') for m in messages}
    cues, stats = geometry.frame_cues(queries, poses)
    features = []
    for row in events:
        present = row.get('query_geometry') is not None
        feature = {k: row[k] for k in ['key', 'job_id', 'id', 'frame', 'index', 'timestamp', 'source_ids', 'U',
                                            'newborn', 'native_adopted', 'output_present', 'identity_ok'] if k in row}
        feature['X'] = [None if x is None else x[:5] for x in row['X']]
        feature['query_present'] = present
        cue = cues[row['id']] if present else {sid: dict(C=0., C_missing=1, main_id=None, ray_ids=[None]*9) for sid in source_ids}
        feature.update(C=[cue[s]['C'] for s in source_ids], C_missing=[cue[s]['C_missing'] for s in source_ids],
                       main_blocker_ids=[cue[s]['main_id'] for s in source_ids], ray_ids=[cue[s]['ray_ids'] for s in source_ids])
        public_groups = geometry.groups_from_cues(source_ids, cue)
        feature['public_groups'] = public_groups
        feature['groups'] = [[source_ids.index(s) for s in group] for group in public_groups]
        features.append(feature)
    return features, stats


def extract(manifest_path, out):
    out, manifest_path = Path(out), Path(manifest_path)
    check_new(out, ['manifest.json', 'features', 'labelled_features.jsonl.gz', 'extraction_summary.json'])
    old = json.loads(manifest_path.read_text())
    jobs = old['jobs']
    if len(jobs) != 39 or len({j['job_id'] for j in jobs}) != 39:
        raise ValueError('expected original 39 distinct jobs')
    splits = parent_splits(jobs)
    print('Fixed parent split:', json.dumps(splits), flush=True)
    inputs = {str(manifest_path.resolve()): source_record(manifest_path)}
    configurations = {}
    for job in jobs:
        path = Path(job['config'])
        inputs[str(path.resolve())] = source_record(path)
        config = json.loads(path.read_text())
        if config['job_id'] != job['job_id']:
            raise ValueError('config job mismatch')
        configurations[job['job_id']] = config
        for path in [Path(config['sender_path']), manifest_path.parent / 'events' / (job['job_id'] + '.jsonl.gz')]:
            inputs[str(path.resolve())] = source_record(path)
    # Hash once at the stage boundary; do not inspect label fields yet.
    label_path = manifest_path.parent / 'labelled.jsonl.gz'
    inputs[str(label_path.resolve())] = source_record(label_path)
    code = code_record()
    (out / 'features').mkdir()
    totals = Counter()
    per_job = {}
    for job in jobs:
        jid = job['job_id']; config = configurations[jid]
        event_path = manifest_path.parent / 'events' / (jid + '.jsonl.gz')
        grouped = iter(itertools.groupby(read_jsonl(event_path), key=lambda r: r['frame']))
        current = next(grouped, None)
        expected = config['expected_frames']
        rows_out = []
        stats = Counter()
        frames = 0
        for sender in read_jsonl(config['sender_path']):
            if frames >= len(expected):
                raise ValueError('extra sender frame')
            exp = expected[frames]
            if sender['frame'] != exp['frame'] or sender['index'] != exp['index'] or abs(sender['timestamp'] - exp['timestamp']) > 1e-8:
                raise ValueError('sender/config frame mismatch')
            frame_rows = []
            if current is not None:
                if current[0] < sender['frame']:
                    raise ValueError('events missing sender frame')
                if current[0] == sender['frame']:
                    frame_rows = list(current[1])
                    current = next(grouped, None)
            features, frame_stats = extract_frame(frame_rows, sender, config['source_ids'])
            for feature in features:
                if feature['job_id'] != jid:
                    raise ValueError('event job mismatch')
            rows_out.extend(features)
            stats.update(frame_stats)
            frames += 1
        if current is not None or frames != len(expected):
            raise ValueError('incomplete sender/event join')
        write_jsonl(out / 'features' / (jid + '.jsonl.gz'), rows_out)
        stats.update(frames=frames, rows=len(rows_out), newborn=sum(r['newborn'] for r in rows_out), no_query=sum(not r['query_present'] for r in rows_out))
        totals.update(stats); per_job[jid] = dict(stats)
        print('extracted', jid, 'frames', frames, 'queries', len(rows_out), flush=True)
    # All public cues are now finalized. Offline labels cannot affect geometry.
    features = {}
    job_map = {j['job_id']: j for j in jobs}
    for job in jobs:
        for feature in read_jsonl(out / 'features' / (job['job_id'] + '.jsonl.gz')):
            key = tuple(feature['key'])
            if key in features:
                raise ValueError('duplicate feature key')
            features[key] = feature
    seen = set()
    with gzip.open(out / 'labelled_features.jsonl.gz', 'xt') as stream:
        for labelled in read_jsonl(label_path):
            key = tuple(labelled['key'])
            if key not in features or key in seen:
                raise ValueError('label/feature keys not one-to-one')
            feature = features[key]
            for field in ['source_ids', 'U', 'frame', 'index', 'timestamp']:
                if feature[field] != labelled[field]:
                    raise ValueError('label/feature metadata mismatch: ' + field)
            job = job_map[feature['job_id']]
            if labelled['parent'] != job['parent'] or labelled['kind'] != job['kind']:
                raise ValueError('label parent/kind mismatch')
            for field in ['parent', 'kind', 'query_truth', 'query_label_reason', 'output_truth']:
                feature[field] = labelled[field]
            feature['split'] = splits[job['parent']]
            stream.write(json.dumps(feature, allow_nan=False) + '\n')
            seen.add(key)
        if len(seen) != len(features):
            raise ValueError('unlabelled feature key')
    dump_json(out / 'manifest.json', dict(source_manifest=str(manifest_path.resolve()), jobs=jobs,
                                         parent_splits=splits, input_sources=list(inputs.values()), code=code,
                                         specification=dict(probe_half=.5, probe_z=.75, rays=9, near_radius=3.,
                                                            clip=model.CLIP, rho_max=.95, l2=.01, alpha=.05,
                                                            false_independent=[.1,.2,.4], false_common=.2, false_margin=.225)))
    dump_json(out / 'extraction_summary.json', dict(complete=True, totals=dict(totals), per_job=per_job,
                                                   joined_labels=len(seen), unknown_labels=sum(r['query_truth'] == -1 for r in features.values())))


def fit(out):
    out = Path(out)
    check_new(out, ['models.json', 'models.error.json'])
    if not json.loads((out / 'extraction_summary.json').read_text())['complete']:
        raise ValueError('incomplete extraction')
    rows = [r for r in read_jsonl(out / 'labelled_features.jsonl.gz') if r['split'] == 'fit']
    try:
        oof, folds = model.crossfit_cue_margin(rows)
        rho = model.fit_rho(oof)
        stability = {p: model.fit_rho([r for r in oof if r['parent'] != p]) for p in sorted(folds)}
        fitted = dict(B=model.fit_margin(rows, False), C=model.fit_margin(rows, True), rho=rho['rho'],
                      rho_fit=rho, rho_leave_one_parent_out=stability, folds=folds, clip=model.CLIP, code=code_record())
        dump_json(out / 'models.json', fitted)
    except Exception as exc:
        dump_json(out / 'models.error.json', dict(error=str(exc), traceback=traceback.format_exc()))
        raise


def six_cells(rows, method):
    answer = {}
    for truth, label in [(1, 'true'), (0, 'false')]:
        subset = [r for r in rows if primary_row(r) and r['query_truth'] == truth]
        weights = model.query_weights(subset)
        counts = Counter(r['decisions'][method] for r in subset)
        rates = {d: float(sum(w for r, w in zip(subset, weights) if r['decisions'][method] == d)) if subset else None
                 for d in ['accept', 'unknown', 'reject']}
        answer[label] = dict(n=len(subset), counts={d: counts[d] for d in rates}, weighted=rates)
    t, f = answer['true']['weighted'], answer['false']['weighted']
    answer['correct_definite'] = (t['accept'] + f['reject']) / 2 if t['accept'] is not None and f['reject'] is not None else None
    return answer


def primary_row(r):
    return model.primary(r)


def evaluate(rows):
    primary = [r for r in rows if primary_row(r)]
    eligible = [r for r in primary if r['eligible']]
    result = dict(n_all=len(rows), n_primary=len(primary), n_eligible=len(eligible),
                  n_newborn=sum(r['newborn'] for r in rows), n_no_query=sum(not r['query_present'] for r in rows),
                  n_m_lt2=sum(r['m'] < 2 for r in rows), n_unsupported=sum(not r['supported'] for r in rows),
                  eligible={name: six_cells(eligible, name) for name in model.METHODS},
                  system_query={name: six_cells(primary, name) for name in model.METHODS}, strata={})
    for field, getter in [('m', lambda r: r['m']), ('k', lambda r: r['k']),
                          ('C_positive', lambda r: any(c > 0 for c in r['C'])),
                          ('common_effective_group', lambda r: r['common_effective_group']),
                          ('output_present', lambda r: r['output_present'])]:
        values = sorted({getter(r) for r in rows})
        result['strata'][field] = {str(value): dict(system_query={name: six_cells([r for r in primary if getter(r) == value], name) for name in model.METHODS},
                                                   eligible={name: six_cells([r for r in eligible if getter(r) == value], name) for name in model.METHODS}) for value in values}
    unknown = [r for r in rows if r['query_truth'] not in (0, 1)]
    result['unknown_label'] = dict(n=len(unknown), decisions={name: dict(Counter(r['decisions'][name] for r in unknown)) for name in model.METHODS})
    background = [r for r in rows if r['kind'] == 'attack' and r['query_truth'] == 1]
    result['attack_true_background'] = dict(n=len(background), by_parent={})
    for parent in sorted({r['parent'] for r in background}):
        subset = [r for r in background if r['parent'] == parent]
        weights = model.query_weights(subset)
        result['attack_true_background']['by_parent'][parent] = dict(
            n=len(subset), n_eligible=sum(r['eligible'] for r in subset),
            decisions={name: dict(counts=dict(Counter(r['decisions'][name] for r in subset)),
                                  weighted={d: float(sum(w for r,w in zip(subset,weights) if r['decisions'][name] == d))
                                            for d in ['accept','unknown','reject']}) for name in model.METHODS})
    result['native_MATE'] = {}
    for truth, label in [(1, 'true'), (0, 'false')]:
        subset = [r for r in primary if r['query_truth'] == truth]
        w = model.query_weights(subset)
        result['native_MATE'][label] = dict(n=len(subset), adopted=sum(bool(r['native_adopted']) for r in subset),
                                           not_adopted=sum(not bool(r['native_adopted']) for r in subset),
                                           adoption_rate=float(sum(weight * bool(r['native_adopted']) for r, weight in zip(subset, w))) if subset else None)
    return result


def probability_metrics(rows):
    rows = model.normal_rows(rows)
    def compute(subset):
        marginal = {name: dict(nll=0., brier=0.) for name in ['B', 'C']}
        source_rows = [r for r in subset if r['m']]
        for row, weight in zip(source_rows, model.query_weights(source_rows)):
            u = np.array([row['U'][i] for i in row['valid_indices']])
            for name in marginal:
                p = np.asarray(row['p_' + name])
                marginal[name]['nll'] += float(weight * -np.where(u == 1, np.log(p), np.log1p(-p)).mean())
                marginal[name]['brier'] += float(weight * ((p - u)**2).mean())
        if not source_rows:
            marginal = {name: dict(nll=None, brier=None) for name in marginal}
        jc = jj = 0.
        for row, weight in zip(subset, model.query_weights(subset)):
            q = model.false_logprob(row['U']) if len(row['valid_indices']) == len(row['U']) else model.false_logprob([row['U'][i] for i in row['valid_indices']])
            jc -= weight * (row['raw_scores']['C'] + q)
            jj -= weight * (row['raw_scores']['J'] + q)
        return dict(n_queries=len(subset), n_sources=sum(r['m'] for r in subset), marginal=marginal,
                    C_minus_B={metric: marginal['C'][metric] - marginal['B'][metric] if source_rows else None for metric in ['nll','brier']},
                    joint_nll_C=float(jc) if subset else None, joint_nll_J=float(jj) if subset else None,
                    J_minus_C=float(jj-jc) if subset else None)
    supported = [r for r in rows if r['supported']]
    return dict(all=compute(supported), common_group=compute([r for r in supported if r['common_effective_group']]),
                unsupported_normal_queries=len(rows)-len(supported))


def feature_ranges(rows):
    summaries = {}
    for name, use_cue in [('B',False), ('C',True)]:
        x = [v for row in rows for v in model.margin_features(row, use_cue)[0]]
        x = np.asarray(x)
        summaries[name] = dict(n=len(x), min=x.min(axis=0).tolist() if len(x) else None,
                               max=x.max(axis=0).tolist() if len(x) else None)
    return summaries


def save_six_cell_figure(out, metrics):
    """One class-normalized eligible-query figure in both requested formats."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Patch
    from matplotlib.ticker import PercentFormatter

    colors = {'accept': '#3975b7', 'unknown': '#aaaeb4', 'reject': '#d16b5d'}
    figure = Figure(figsize=(12, 5.8))
    FigureCanvasAgg(figure)
    axes = figure.subplots(1, 2, sharey=True)
    labels = [f'{method} {truth}' for method in model.METHODS for truth in ['true', 'false']]
    for axis, split in zip(axes, ['cal', 'eval']):
        for y, (method, truth) in enumerate(itertools.product(model.METHODS, ['true', 'false'])):
            values = metrics[split]['eligible'][method][truth]['weighted']
            left = 0.
            for decision, color in colors.items():
                value = values[decision]
                if value is not None:
                    axis.barh(y, value, left=left, height=.72, color=color)
                    if value > .07:
                        axis.text(left + value / 2, y, f'{100 * value:.1f}%',
                                  va='center', ha='center', color='white', fontsize=9)
                    left += value
            if values['accept'] is None:
                axis.text(.5, y, 'No labelled queries', ha='center', va='center', fontsize=9)
        axis.set(title=split, xlim=(0, 1), ylim=(len(labels) - .4, -.6))
        axis.set_yticks(range(len(labels)))
        axis.set_yticklabels(labels)
        axis.xaxis.set_major_formatter(PercentFormatter(1))
        axis.set_xlabel('Within-class query weight')
    figure.suptitle('Eligible pre-query decisions (class-normalized weights)')
    figure.legend(handles=[Patch(color=color, label=decision) for decision, color in colors.items()],
                  loc='lower center', ncol=3, frameon=False)
    figure.tight_layout(rect=(0, .07, 1, .94))
    figure.savefig(out / 'six_cells.png', dpi=180)
    figure.savefig(out / 'six_cells.svg')


def method_decisions(metrics, probabilities):
    eva = metrics['eval']['eligible']
    pb = probabilities['eval']['all']
    b, c, j, g = [eva[name] for name in model.METHODS]
    def risk_ok(method):
        t, f = method['true']['weighted']['reject'], method['false']['weighted']['accept']
        return t is not None and f is not None and t <= .05+1e-12 and f <= .05+1e-12
    c_improved = pb['C_minus_B']['nll'] is not None and pb['C_minus_B']['nll'] < 0
    c_task = risk_ok(c) and c['correct_definite'] is not None and b['correct_definite'] is not None and c['correct_definite'] >= b['correct_definite']
    j_improved = pb['J_minus_C'] is not None and pb['J_minus_C'] < 0
    j_task = risk_ok(j) and all(e['correct_definite'] is not None for e in [c,j,g]) and j['correct_definite'] > max(c['correct_definite'],g['correct_definite'])
    return dict(retain_C_effect_claim=bool(c_improved and c_task), retain_joint_increment_claim=bool(j_improved and j_task),
                C_probability_improved=bool(c_improved), C_task_condition=bool(c_task),
                J_joint_nll_improved=bool(j_improved), J_task_condition=bool(j_task),
                rule='If a condition fails, retain the interface but withdraw this fixed-version effect claim; do not tune on eval.')


def report(out):
    out = Path(out)
    check_new(out, ['predictions.jsonl.gz', 'metrics.json', 'cases.json', 'summary.md', 'six_cells.svg', 'six_cells.png'])
    fitted = json.loads((out / 'models.json').read_text())
    rows = list(read_jsonl(out / 'labelled_features.jsonl.gz'))
    clipping, ranges = {}, {}
    for split in ['fit','cal','eval']:
        subset = [r for r in rows if r['split'] == split]
        clipping[split] = {name: model.attach_probabilities(subset, fitted[name], 'p_' + name) for name in ['B','C']}
        ranges[split] = feature_ranges(subset)
    for row in rows:
        row.update(model.score_query(row, fitted))
    cal = [r for r in rows if r['split'] == 'cal']
    policies = {name: model.calibrate(cal, name) for name in model.METHODS}
    for row in rows:
        row['decisions'] = {name: model.decide(row['scores'][name], row['eligible'] and row['supported'], policies[name]) for name in model.METHODS}
    evaluated = {split: evaluate([r for r in rows if r['split'] == split]) for split in ['cal','eval']}
    for split in ['cal','eval']:
        evaluated[split]['by_parent'] = {parent: evaluate([r for r in rows if r['split'] == split and r['parent'] == parent])
                                             for parent in sorted({r['parent'] for r in rows if r['split'] == split})}
    probabilities = {split: probability_metrics([r for r in rows if r['split'] == split]) for split in ['cal','eval']}
    decisions = method_decisions(evaluated, probabilities)
    metrics = dict(by_split=evaluated, normal_probability=probabilities, policies=policies, rho=fitted['rho_fit'],
                   rho_leave_one_parent_out=fitted['rho_leave_one_parent_out'], C_coefficient=fitted['C']['coef'][5],
                   clipping=clipping, feature_ranges=ranges, method_decisions=decisions, code=code_record())
    eval_rows = sorted([r for r in rows if r['split'] == 'eval'], key=lambda r: tuple(r['key']))
    cases = dict(common_positive=[r for r in eval_rows if any(c > 0 for c in r['C']) and r['common_effective_group']][:12],
                 C_J_different=[r for r in eval_rows if r['decisions']['C'] != r['decisions']['J']][:12])
    write_jsonl(out / 'predictions.jsonl.gz', rows)
    dump_json(out / 'metrics.json', metrics)
    dump_json(out / 'cases.json', cases)
    save_six_cell_figure(out, evaluated)
    lines = ['# 真实观测条件接入固定批次', '',
             '本批仅评价成熟预查询的静态判决。全部材料属于已查看过的开发数据。', '',
             '所有真假率在类内按父、任务、查询逐层等权。有资格预查询与全部query的分母分别保存于metrics.json。', '',
             '| split | method | 真采纳 | 真未知 | 真拒绝 | 假采纳 | 假未知 | 假拒绝 | 正确明确率 |',
             '|---|---|---|---|---|---|---|---|---|']
    def fmt(x):return 'null' if x is None else f'{100*x:.3f}%'
    for split in ['cal','eval']:
        for name in model.METHODS:
            item = evaluated[split]['eligible'][name]
            cells = [item[t]['weighted'][d] for t in ['true','false'] for d in ['accept','unknown','reject']]
            lines.append('| ' + ' | '.join([split,name] + [fmt(x) for x in cells] + [fmt(item['correct_definite'])]) + ' |')
    lines += ['', '方法决定', '',
              ('保留本版真实C效果主张。' if decisions['retain_C_effect_claim'] else '保留输入接口，撤下本固定probe版本的效果主张。'),
              ('保留本版真实联合增量主张。' if decisions['retain_joint_increment_claim'] else '撤下本版真实联合增量主张。'), '',
              f"rho={fitted['rho']:.8g}，状态{fitted['rho_fit']['status']}。rho表示残余统计依赖，可能吸收边际模型误差。", '',
              '证据边界', '',
              'C表示已知历史预测框的潜在阻挡，不是物理可见率。假侧Q_F是固定声明参考，不是一般攻击模型估计。',
              '旧假标签依赖相容当前输出，删除假查询可能保留未知标签。未知标签分布另列，未匹配GT没有补成假。',
              '原生MATE只旁列采用与未采用，未采用没有改称主动拒绝。删除查询的kernel采纳不代表已恢复中央输出。',
              '当前没有出生核验或长时序真实性更新，也不能据单源注入外推多源串谋。', '',
              '未调整probe、rho上界、划分、概率裁剪或预算；结果不触发扩采或同一eval再拟合。']
    (out / 'summary.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(decisions, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['extract','fit','report','all'], required=True)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--manifest', type=Path, default=OLD)
    args = parser.parse_args()
    if args.stage in ['extract','all']:extract(args.manifest, args.out)
    if args.stage in ['fit','all']:fit(args.out)
    if args.stage in ['report','all']:report(args.out)


if __name__ == '__main__':
    main()
