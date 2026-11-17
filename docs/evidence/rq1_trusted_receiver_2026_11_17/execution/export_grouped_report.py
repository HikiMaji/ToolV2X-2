"""Export fixed saved comparisons; no scoring, fitting or threshold selection."""
import argparse
import csv
import json
from pathlib import Path


def main(run):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    run = Path(run)
    report = json.loads((run / 'evaluate.report.json').read_text())
    regimes = ('mixed', 'F1_only', 'F2_only')
    records = []
    for regime in regimes:
        entry = report['regimes'][regime]
        for method, pair in entry['eval']['own_comparison'].items():
            for version in ('old', 'new'):
                record = dict(regime=regime, method=method, version=version)
                for prefix, truth in (('T', 'true'), ('F', 'false')):
                    rates = pair[version][truth]
                    assert abs(sum(rates.values()) - 1) < 1e-9
                    for suffix, decision in (('A', 'accept'), ('U', 'unknown'), ('R', 'reject')):
                        record[prefix + suffix] = 100 * rates[decision]
                record['CD'] = (record['TA'] + record['FR']) / 2
                record['candidate_status'] = entry['verdict']['status']
                records.append(record)
            for truth in ('true', 'false'):
                assert abs(pair['old'][truth]['reject'] - pair['new'][truth]['reject']) < 1e-9
                assert pair['new'][truth]['accept'] <= pair['old'][truth]['accept'] + 1e-9
    with (run / 'comparison_for_report.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(11.4, 8))
    names = ['Mixed', 'F1 cal / F2 eval', 'F2 cal / F1 eval']
    pairs = [report['regimes'][r]['eval']['own_comparison']['LocalCond'] for r in regimes]
    colors = ('#8695ac', '#267d88')
    for ax, truth, decision, title, ylim in (
            (axes[0, 0], 'false', 'accept', 'Conditional method: false acceptance', (0, 6)),
            (axes[0, 1], 'true', 'accept', 'Conditional method: true acceptance', (0, 75))):
        for version, shift, color in zip(('old', 'new'), (-.18, .18), colors):
            values = [100 * p[version][truth][decision] for p in pairs]
            x = [i + shift for i in range(3)]
            ax.bar(x, values, width=.34, color=color, label=version.title())
            for pos, value in zip(x, values):
                ax.text(pos, value + (ylim[1] / 50), f'{value:.2f}', ha='center', fontsize=9)
        ax.set_xticks(range(3))
        ax.set_xticklabels(names)
        ax.set_ylim(*ylim)
        ax.set_title(title, loc='left')
        ax.set_ylabel('Weighted rate (%)')
    axes[0, 0].legend(frameon=False)
    axes[0, 0].axhline(5, color='#777777', linestyle='--', linewidth=1)
    ax = axes[1, 0]
    for method, shift, color in zip(('LocalCount', 'LocalCond'), (-.18, .18), colors):
        values = [100 * report['regimes'][r]['eval']['own_comparison'][method]['true_accept_loss'] for r in regimes]
        x = [i + shift for i in range(3)]
        ax.bar(x, values, width=.34, color=color, label=method)
        for pos, value in zip(x, values):
            ax.text(pos, value + .08, f'{value:.2f}', ha='center', fontsize=9)
    ax.axhline(2, color='#aa3344', linestyle='--', linewidth=1)
    ax.set_xticks(range(3))
    ax.set_xticklabels(names)
    ax.set_ylim(0, 4.4)
    ax.set_ylabel('Percentage points lost versus own old method')
    ax.set_title('True adoption cost: frozen cap = 2 pp', loc='left')
    ax.legend(frameon=False)
    ax = axes[1, 1]
    values = [100 * max(v['value'] for k, v in report['regimes'][r]['verdict']['checks'].items()
                       if k.startswith('false_accept_')) for r in regimes]
    ax.bar(names, values, color=['#b94c5c' if v > 5 else '#267d88' for v in values], width=.6)
    for pos, value in enumerate(values):
        ax.text(pos, value + .15, f'{value:.2f}%', ha='center')
    ax.axhline(5, color='#aa3344', linestyle='--', linewidth=1)
    ax.set_ylim(0, 9)
    ax.set_ylabel('False acceptance (%)')
    ax.set_title('Worst family / k layer: conditional method', loc='left')
    fig.suptitle('Remote acceptance retained: lower error, all final retention gates not passed', fontsize=13)
    fig.text(.5, .018,
             'Same 12 development recordings; fixed scores and rejection decisions; acceptance threshold only.\n'
             'Mixed remote true acceptance: 13.90 to 11.94 pp. Fewer false accepts become Unknown, not Reject.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, .95))
    figures = run / 'figures'
    figures.mkdir(exist_ok=True)
    for extension in ('png', 'svg'):
        fig.savefig(figures / ('grouped_acceptance_comparison.' + extension), dpi=180)
    plt.close(fig)
    print('Exported', len(records), 'six-cell comparisons and PNG/SVG figure.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    main(parser.parse_args().run)
