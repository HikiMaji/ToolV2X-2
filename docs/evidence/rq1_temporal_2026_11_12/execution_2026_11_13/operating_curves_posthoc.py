"""Frozen-score descriptive curves; thresholds use cal only, main results untouched."""
import os
for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[name] = '1'
import json
from pathlib import Path
import sys
sys.path.insert(0, '/root/autodl-tmp/ToolV2X/.worktrees/rq1-temporal-2026-11-12')
from scripts.rq1_temporal import data, run
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

out = data.DEFAULT_OUT
dest = Path(__file__).resolve().parent
if (dest / 'operating_curves_posthoc.json').exists():
    raise FileExistsError('descriptive curves already exist')
assert (out / 'report.complete.json').exists()
manifest = json.loads((out / 'manifest.json').read_text())
frozen = json.loads((out / 'report/metrics.json').read_text())
layers = {(j['family'], j['attack_k']) for j in manifest['jobs']
          if j['kind'] == 'attack' and j['split'] == 'cal'}
rows = {s: run.load_report_split(out / 'report/cache/main.sqlite', s) for s in ('cal', 'eval')}
points = []
for alpha in (0., .01, .02, .05, .1):
    policies = {m: run.calibrate(rows['cal'], m, layers, alpha) for m in run.METHODS}
    results = {}
    for split, values in rows.items():
        run.apply_policies(values, policies)
        results[split] = run.six_cells_many(values)
        if alpha == .05:
            reference = frozen['variants']['main']['metrics'][split]['system_query']
            for method in run.METHODS:
                for truth in ('true', 'false'):
                    for decision in run.DECISIONS:
                        assert abs(results[split][method][truth]['weighted'][decision]
                                   - reference[method][truth]['weighted'][decision]) < 1e-10
    points.append(dict(cal_alpha=alpha, policies=policies, metrics=results))
data.atomic_json(dest / 'operating_curves_posthoc.json', dict(
    scope='Posthoc descriptive operating curves from frozen main scores. Cal-only thresholds; no eval selection or change to main alpha=0.05.',
    main_point_reproduced=True, points=points, source=data.source_record(out / 'report/metrics.json'),
    script=data.source_record(Path(__file__))))
fig = Figure(figsize=(11, 4.5)); FigureCanvasAgg(fig)
left, right = fig.subplots(1, 2)
for method in ('D', 'C', 'T', 'J', 'G', 'MATE_policy'):
    adoption, false_adoption, coverage, selective_risk = [], [], [], []
    for point in points:
        r = point['metrics']['eval'][method]
        t, f = r['true']['weighted'], r['false']['weighted']
        cov = (2-t['unknown']-f['unknown'])/2
        adoption.append(100*t['accept']); false_adoption.append(100*f['accept'])
        coverage.append(100*cov)
        selective_risk.append(100*(t['reject']+f['accept'])/(2*cov) if cov else float('nan'))
    left.plot(adoption, false_adoption, 'o-', label=method, markersize=3)
    right.plot(coverage, selective_risk, 'o-', label=method, markersize=3)
    left.scatter(adoption[3], false_adoption[3], marker='s', s=50)
    right.scatter(coverage[3], selective_risk[3], marker='s', s=50)
left.set(xlabel='True adoption (%)', ylabel='False adoption (%)', title='Adoption tradeoff on development eval')
right.set(xlabel='Definite coverage, class balanced (%)', ylabel='Wrong / definite, class balanced (%)', title='Descriptive risk and coverage')
for ax in (left, right):
    ax.grid(alpha=.25); ax.legend(fontsize=8)
fig.suptitle('Cal budgets 0/1/2/5/10%; squares = frozen 5% main point. No eval tuning.', fontsize=10)
fig.tight_layout(); fig.savefig(dest / 'operating_curves_posthoc.png', dpi=180)
print('Descriptive curves complete; 5% main six cells reproduced exactly.')
