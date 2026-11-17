"""Confirmation-list boundaries; no point clouds or native replay are read."""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO/'docs/REALLY_MAYBE/rq1_joint_supplement_2026_11_17/config.json'


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())

    def module(self):
        return importlib.import_module('scripts.rq1_joint_confirmation')

    def test_frozen_specs_match_existing_detection_metadata(self):
        # A changed source/frame binding must fail before any preprocessing.
        module = self.module()
        module.validate_config(self.config)
        changed = copy.deepcopy(self.config)
        parent = changed['additional_eval_parents'][0]
        changed['parent_specs'][parent]['frames'][-1] += 2
        with self.assertRaises(ValueError):
            module.validate_config(changed)

    def test_invalid_attempts_cannot_start_frontend(self):
        module = self.module()
        mutations = [
            lambda c: c['jobs'][1].update(seed=1),
            lambda c: c['jobs'][1].update(attack_k=3),
            lambda c: c['jobs'].pop(),
            lambda c: c['additional_eval_parents'].append(c['existing_eval_parents'][0]),
            lambda c: c['attack'].update(total_scans=79),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(self.config)
            mutate(changed)
            with tempfile.TemporaryDirectory() as tmp:
                with patch.object(module.frozen, 'parent_worker', side_effect=AssertionError('frontend started')):
                    with self.assertRaises(ValueError):
                        module.prepare(changed, Path(tmp)/'out', workers=1)
                self.assertFalse((Path(tmp)/'out'/'manifest.json').exists())

    def test_changed_config_cannot_reuse_manifest(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            old = copy.deepcopy(self.config)
            old['scope'] = 'another bound configuration'
            (out/'manifest.json').write_text(json.dumps({'config': old, 'jobs': old['jobs']}))
            with patch.object(module.frozen, 'parent_worker', side_effect=AssertionError('frontend started')):
                with self.assertRaises(ValueError):
                    module.prepare(self.config, out, workers=1)

    def test_resume_keeps_unrealizable_and_checks_completed_artifacts(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            parents = {p: dict(spec=s, source_ids=s['source_ids'], scan_path=str(out/'unused'))
                       for p, s in self.config['parent_specs'].items()}
            manifest = dict(config=self.config, jobs=self.config['jobs'], parents=parents)
            (out/'manifest.json').write_text(json.dumps(manifest))
            first = self.config['jobs'][0]['job_id']
            for job in self.config['jobs']:
                dest = out/'jobs'/job['job_id']
                dest.mkdir(parents=True)
                status = 'COMPLETE' if job['job_id'] == first else 'UNREALIZABLE'
                (dest/'complete.json').write_text(json.dumps(dict(status=status)))
                if status == 'COMPLETE':
                    for name in ('online.jsonl.gz', 'rows.jsonl.gz', 'entity_coverage.jsonl.gz', 'attack.json'):
                        (dest/name).touch()
            # Real completed-job branch verifies files and must not import native replay.
            with patch.object(module.native, 'imports', side_effect=AssertionError('native replay started')):
                with patch.object(module.frozen, 'parent_worker', side_effect=AssertionError('parent restarted')):
                    module.prepare(self.config, out, workers=1)
                    result = json.loads((out/'prepare.complete.json').read_text())
                    self.assertEqual(result['planned_jobs'], 15)
                    self.assertEqual(sum(v['status'] == 'UNREALIZABLE' for v in result['jobs'].values()), 14)
                    module.prepare(self.config, out, workers=1)
                    (out/'jobs'/first/'rows.jsonl.gz').unlink()
                    with self.assertRaises(RuntimeError):
                        module.prepare(self.config, out, workers=1)


if __name__ == '__main__':
    unittest.main()
