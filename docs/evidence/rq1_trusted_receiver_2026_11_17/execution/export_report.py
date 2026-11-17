"""Export saved results only; never fit a model or choose a threshold."""
import argparse
import csv
import json
from pathlib import Path


def main(run):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    run = Path(run)
    report = json.loads((run/'evaluate.report.json').read_text())
    methods = ('Local', 'LocalCount', 'LocalCond')
    regimes = ('mixed', 'F1_only', 'F2_only')
    records = []
    for regime in regimes:
        evaluation = report['regimes'][regime]['eval']
        domains = dict(overall=evaluation['system_query'], **evaluation['by_domain'])
        for domain, stats in domains.items():
            for method in methods:
                table = stats[method]
                record = dict(regime=regime, domain=domain, method=method)
                for prefix, truth in (('T', 'true'), ('F', 'false')):
                    for suffix, decision in (('A', 'accept'), ('U', 'unknown'), ('R', 'reject')):
                        record[prefix+suffix] = 100*table[truth]['weighted'][decision]
                    record[prefix+'_rows'] = table[truth]['n']
                    record[prefix+'_parents'] = table[truth]['parents']
                record['CD'] = 100*table['correct_definite']
                records.append(record)
    path = run/'metrics_for_report.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(10.4, 7.5))
    stats = report['regimes']['mixed']['eval']['system_query']
    colors = ['#9ba4b5', '#4477aa', '#228877']
    names = ['Local', 'Local + count', 'Local + condition']
    for ax, truth, decision, title in (
            (axes[0, 0], 'true', 'accept', 'Mixed: true acceptance'),
            (axes[0, 1], 'false', 'reject', 'Mixed: false rejection')):
        values = [100*stats[m][truth]['weighted'][decision] for m in methods]
        ax.bar(names, values, color=colors, width=.62)
        for x, value in enumerate(values):
            ax.text(x, value+1.3, f'{value:.2f}%', ha='center')
        ax.set_ylim(0, 100)
        ax.set_title(title, loc='left')
        ax.set_ylabel('Weighted rate (%)')
    axes[0, 1].set_title('Mixed: false rejection\nTrue rejection: count 2.40%, condition 4.38%',
                         loc='left', fontsize=10)
    gains = [100*(report['regimes'][r]['eval']['system_query']['LocalCond']['correct_definite']-
                  report['regimes'][r]['eval']['system_query']['LocalCount']['correct_definite']) for r in regimes]
    ax = axes[1, 0]
    ax.bar(['Mixed', 'F1 cal / F2 eval', 'F2 cal / F1 eval'], gains, color=colors[2], width=.62)
    for x, value in enumerate(gains):
        ax.text(x, value+.12, f'+{value:.2f}', ha='center')
    ax.axhline(1, color='#666666', linestyle='--', linewidth=1)
    ax.set_ylim(0, 6)
    ax.set_ylabel('CD difference (percentage points)')
    ax.set_title('Condition versus count, same local input', loc='left')
    failures = []
    for regime in regimes:
        checks = report['regimes'][regime]['verdict']['LocalCond']['checks']
        for key, item in checks.items():
            if key.startswith('false_accept_') and item['status'] == 'fail':
                failures.append((regime, key[len('false_accept_'):], 100*item['value']))
    ax = axes[1, 1]
    labels = [f'{"Mixed" if r == "mixed" else "F1->F2" if r == "F1_only" else "F2->F1"}\n{layer}'
              for r, layer, _ in failures]
    values = [value for _, _, value in failures]
    ax.bar(labels, values, color='#bb4455', width=.62)
    for x, value in enumerate(values):
        ax.text(x, value+.15, f'{value:.2f}%', ha='center')
    ax.axhline(5, color='#333333', linestyle='--', linewidth=1)
    ax.set_ylim(0, 10)
    ax.set_ylabel('False acceptance (%)')
    ax.set_title('Risk gate still fails in two-source attacks', loc='left')
    fig.suptitle('Trusted receiver development results: utility gain, risk gate not passed', fontsize=13)
    fig.text(.5, .015,
        '12 evaluation recordings; 277 true GT entities; 28 injected false entities in mixed.\n'
        'CD = (true acceptance + false rejection) / 2. Same calibration budget, not identical realized error.',
        ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .95))
    figures = run/'figures'
    figures.mkdir(exist_ok=True)
    fig.savefig(figures/'trusted_receiver_results.png', dpi=180)
    fig.savefig(figures/'trusted_receiver_results.svg')
    plt.close(fig)
    print('Exported', len(records), 'metric rows and PNG/SVG figures.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    main(parser.parse_args().run)
