"""Regression checks for relocation-safe paths and documented module commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    def test_default_paths_stay_at_project_root_from_another_working_directory(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        for key in ('SLP_DATA', 'SLP_DB', 'SLP_RUNTIME'):
            env.pop(key, None)
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-c',
                'import json; from slp.config import DATA_DIR,DB_PATH,RUNTIME_DIR; '
                'print(json.dumps([str(p) for p in (DATA_DIR,DB_PATH,RUNTIME_DIR)]))'],
                cwd=folder, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout),
                         [str(ROOT / 'data'), str(ROOT / 'slp.duckdb'), str(ROOT / 'runtime')])

    def test_explicit_operator_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / name) for name in ('dataset', 'analysis.duckdb', 'generated')]
            env = dict(os.environ, SLP_DATA=paths[0], SLP_DB=paths[1], SLP_RUNTIME=paths[2])
            result = subprocess.run([sys.executable, '-c',
                'import json; from slp.config import DATA_DIR,DB_PATH,RUNTIME_DIR; '
                'print(json.dumps([str(p) for p in (DATA_DIR,DB_PATH,RUNTIME_DIR)]))'],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), paths)

    def test_operator_cli_modules_are_importable_without_api_calls(self):
        for module in ('scripts.checks.check_agentstream', 'slp.management.production_report'):
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, '-m', module, '--help'],
                    cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)
