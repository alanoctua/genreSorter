"""Exercise publication guards without needing a Docker daemon."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'sha256:' + 'a' * 64
REVISION = 'b' * 40


class Release(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.calls = self.folder / 'calls.jsonl'
        self.env = {**os.environ, 'PATH': str(self.folder) + os.pathsep + os.environ.get('PATH', ''),
                    'IMAGE_NAME': 'ghcr.io/example/genresorter', 'IMAGE_DIGEST': DIGEST,
                    'EXPECTED_VERSION': '0.3.5', 'EXPECTED_REVISION': REVISION,
                    'GITHUB_SHA': REVISION, 'GITHUB_REF': 'refs/heads/main',
                    'GITHUB_STEP_SUMMARY': str(self.folder / 'summary'),
                    'TEST_CALLS': str(self.calls), 'TEST_MAIN': REVISION, 'TEST_DIGEST': DIGEST,
                    'TEST_VERSION': '0.3.5', 'APP_REVISION': REVISION}
        mock = '''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["TEST_CALLS"], "a") as f:
    f.write(json.dumps([Path(sys.argv[0]).name, *args]) + "\\n")
if Path(sys.argv[0]).name == "git":
    print(os.environ["TEST_MAIN"] + "\\trefs/heads/main")
elif args[:3] == ["buildx", "imagetools", "inspect"]:
    print(os.environ["TEST_DIGEST"])
elif args and args[0] == "run":
    Path("server.py").write_text("APP_VERSION = " + repr(os.environ["TEST_VERSION"]) + "\\n")
    raise SystemExit(subprocess.call([sys.executable, "-c", args[args.index("-c") + 1]]))
'''
        for name in ['docker', 'git']:
            p = self.folder / name; p.write_text(mock); p.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name):
        return subprocess.run(
            ['bash', str(ROOT / 'scripts' / name)],
            cwd=self.folder, env=self.env,
            text=True, capture_output=True
        )

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_candidate_checks_both_architectures_by_digest(self):
        result = self.run_script('verify-image.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [call for call in self.recorded() if call[:2] == ['docker', 'run']]
        self.assertEqual(len(runs), 2)
        self.assertEqual([call[call.index('--platform') + 1] for call in runs], ['linux/amd64', 'linux/arm64'])
        self.assertTrue(all('ghcr.io/example/genresorter@' + DIGEST in call for call in runs))

    def test_candidate_rejects_old_version_and_wrong_commit(self):
        self.env['TEST_VERSION'] = '0.1.0'
        self.assertNotEqual(self.run_script('verify-image.sh').returncode, 0)
        self.env['TEST_VERSION'] = '0.3.5'
        self.env['APP_REVISION'] = 'old-commit'
        self.assertNotEqual(self.run_script('verify-image.sh').returncode, 0)

    def test_current_main_promotes_the_verified_digest(self):
        result = self.run_script('promote-latest.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        promotion = [call for call in self.recorded() if call[:4] == ['docker', 'buildx', 'imagetools', 'create']]
        self.assertEqual(promotion, [['docker', 'buildx', 'imagetools', 'create', '--tag',
                                     'ghcr.io/example/genresorter:latest', 'ghcr.io/example/genresorter@' + DIGEST]])
        self.assertIn(REVISION, (self.folder / 'summary').read_text())

    def test_tag_and_stale_main_rerun_do_not_move_latest(self):
        self.env['GITHUB_REF'] = 'refs/tags/v0.3.4'
        self.assertEqual(self.run_script('promote-latest.sh').returncode, 0)
        self.assertEqual(self.recorded(), [])
        self.env['GITHUB_REF'] = 'refs/heads/main'
        self.env['TEST_MAIN'] = 'newer-commit'
        self.assertEqual(self.run_script('promote-latest.sh').returncode, 0)
        self.assertFalse(any(call[0] == 'docker' for call in self.recorded()))

    def test_latest_digest_mismatch_fails_verification(self):
        self.env['TEST_DIGEST'] = 'sha256:unexpected'
        result = self.run_script('promote-latest.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('digest mismatch', result.stderr)


if __name__ == '__main__':
    unittest.main()
