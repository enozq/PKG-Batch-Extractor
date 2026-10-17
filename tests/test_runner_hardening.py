"""Adversarial fake-engine tests; no copyrighted PKG contents required."""
from pathlib import Path
import os
import queue
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from pkg_batch_extractor.core import plan_jobs
from pkg_batch_extractor.runner import JobRunner, MAX_ENGINE_LOG_LINES
from test_runner import PythonMockEngine


class HardeningTests(unittest.TestCase):
    def execute(self, root: Path, script_text: str, *, name='Demo.pkg'):
        engine_script = root / 'fake_cli.py'
        engine_script.write_text(script_text, encoding='utf-8')
        pkg = root / name
        pkg.write_bytes(b'original PKG unchanged')
        output = root / 'output folder'
        events = queue.Queue()
        runner = JobRunner(events)
        runner.start(plan_jobs([pkg], output), PythonMockEngine(engine_script))
        runner.thread.join(timeout=12)
        self.assertFalse(runner.active, 'worker thread hung')
        trace = []
        while not events.empty():
            trace.append(events.get_nowait())
        return output, pkg, trace

    def test_engine_refuses_existing_directory_receives_new_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, pkg, trace = self.execute(root, '''
from pathlib import Path
import sys
out = Path(sys.argv[3])
if out.exists():
    print('OUTPUT WAS ALREADY PRESENT', flush=True)
    sys.exit(44)
out.mkdir(parents=True)
(out / 'ok.txt').write_text('worked', encoding='utf-8')
''')
            self.assertEqual((output / 'Demo' / 'ok.txt').read_text(), 'worked')
            self.assertEqual(pkg.read_bytes(), b'original PKG unchanged')
            self.assertFalse(list(output.glob('.pkg-batch-partial-*')))
            self.assertIn(('finished', 1, 0, False), trace)

    def test_empty_success_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, pkg, trace = self.execute(root, 'import sys\nfrom pathlib import Path\nPath(sys.argv[3]).mkdir(parents=True)\n')
            self.assertFalse((output / 'Demo').exists())
            self.assertEqual(len(list(output.glob('.pkg-batch-partial-*'))), 1)
            self.assertIn(('finished', 0, 1, False), trace)

    def test_many_log_lines_are_bounded_and_stdout_is_drained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, _, trace = self.execute(root, '''
from pathlib import Path
import sys
out = Path(sys.argv[3]); out.mkdir(parents=True)
(out / 'ok').write_bytes(b'1')
for i in range(2700):
    print('line ' + str(i))
''')
            logs = [evt[1] for evt in trace if evt[0] == 'log']
            self.assertTrue(any('suppressed' in line for line in logs))
            self.assertLessEqual(len(logs), MAX_ENGINE_LOG_LINES + 4)
            self.assertIn(('finished', 1, 0, False), trace)
            self.assertTrue((output / 'Demo' / 'ok').exists())

    def test_exit_nonzero_keeps_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, _, trace = self.execute(root, '''
import sys
from pathlib import Path
out=Path(sys.argv[3]); out.mkdir(parents=True)
(out / 'partial').write_bytes(b'partial')
sys.exit(17)
''')
            self.assertIn(('finished', 0, 1, False), trace)
            self.assertEqual(len(list(output.glob('.pkg-batch-partial-*'))), 1)
            self.assertFalse((output / 'Demo').exists())

    def test_unicode_source_and_output_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, pkg, trace = self.execute(root, '''
from pathlib import Path
import sys
src=Path(sys.argv[1]); out=Path(sys.argv[3]); out.mkdir(parents=True)
(out/'f.txt').write_text(src.name, encoding='utf-8')
''', name='Örnek Oyun.pkg')
            self.assertEqual((output / 'Örnek Oyun' / 'f.txt').read_text(encoding='utf-8'), 'Örnek Oyun.pkg')
            self.assertIn(('finished', 1, 0, False), trace)

    def test_target_created_during_extraction_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, _, trace = self.execute(root, "from pathlib import Path\nimport sys\nout = Path(sys.argv[3]); out.mkdir(parents=True)\n(out/'new.txt').write_text('new data', encoding='utf-8')\noriginal_target = out.parent.parent / 'Demo'\noriginal_target.mkdir(exist_ok=True)\n(original_target/'important.txt').write_text('keep me', encoding='utf-8')\n")
            self.assertEqual((output / 'Demo' / 'important.txt').read_text(), 'keep me')
            self.assertEqual((output / 'Demo (2)' / 'new.txt').read_text(), 'new data')
            self.assertIn(('finished', 1, 0, False), trace)

    def test_missing_pkg_source_is_failed_without_starting_engine(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / 'Gone.pkg'; src.write_bytes(b'data')
            engine = root / 'fake_cli.py'
            engine.write_text('raise AssertionError("should never run")', encoding='utf-8')
            jobs = plan_jobs([src], root / 'out')
            src.unlink()
            events = queue.Queue(); runner = JobRunner(events)
            runner.start(jobs, PythonMockEngine(engine))
            runner.thread.join(timeout=8)
            self.assertFalse(runner.active)
            self.assertIn(('finished', 0, 1, False), list(events.queue))
            self.assertFalse((root / 'out').exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX process groups only')
    def test_cancel_stops_subprocess_children(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            child_script = root / 'child.py'
            marker = root / 'child_finished.txt'
            child_script.write_text('''import pathlib, sys, time
time.sleep(2.0)
pathlib.Path(sys.argv[1]).write_text('SURVIVED', encoding='utf-8')
''', encoding='utf-8')
            engine_script = root / 'fake_cli.py'
            engine_script.write_text('''import pathlib, subprocess, sys, time
out = pathlib.Path(sys.argv[3]); out.mkdir(parents=True)
subprocess.Popen([sys.executable, sys.argv[4], sys.argv[5]])
pathlib.Path(sys.argv[6]).write_text('running', encoding='utf-8')
time.sleep(30)
''', encoding='utf-8')
            ready = root / 'ready'
            class TreeEngine(PythonMockEngine):
                def command(self, source, staging):
                    return [sys.executable, str(engine_script), str(source), '-o', str(staging),
                            str(child_script), str(marker), str(ready)]
            src = root / 'A.pkg'; src.write_bytes(b'a')
            events = queue.Queue()
            runner = JobRunner(events)
            runner.start(plan_jobs([src], root / 'output'), TreeEngine(engine_script))
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.025)
            self.assertTrue(ready.exists(), 'fake engine did not spawn child')
            runner.cancel()
            runner.thread.join(timeout=7)
            self.assertFalse(runner.active)
            time.sleep(2.3)  # The child would write the marker if orphaned.
            self.assertFalse(marker.exists(), 'child survived cancellation')
            self.assertFalse((root / 'output' / 'A').exists())
            statuses = [event for event in list(events.queue) if event[0] == 'status']
            self.assertTrue(any(event[2] == 'Cancelled' for event in statuses))


if __name__ == '__main__':
    unittest.main()
