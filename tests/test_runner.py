"""Cross-platform end-to-end tests using a mock CLI implemented in Python."""
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest
from collections import deque
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from pkg_batch_extractor.backend import Extractor  # noqa: E402
from pkg_batch_extractor.core import plan_jobs  # noqa: E402
from pkg_batch_extractor.runner import JobRunner  # noqa: E402


class PythonMockEngine(Extractor):
    def __init__(self, script: Path):
        super().__init__('pkgextract', Path(sys.executable))
        object.__setattr__(self, 'script', script)

    def command(self, source: Path, staging: Path) -> list[str]:
        self.validate()
        return [str(self.executable), str(self.script), str(source), '-o', str(staging)]


class RunnerIntegrationTests(unittest.TestCase):
    def test_speed_smoothing_suppresses_single_scan_burst(self):
        # A completed file may appear in one tree scan despite being written
        # over time; a lone byte-count jump should not become the displayed rate.
        samples = deque([(0.0, 0), (1.0, 0), (2.0, 100_000_000),
                         (3.0, 100_000_000), (4.0, 100_000_000),
                         (5.0, 100_000_000)], maxlen=6)
        self.assertIsNone(JobRunner._smoothed_speed(samples))

    def test_speed_smoothing_reports_steady_output_rate(self):
        samples = deque([(0.0, 0), (1.0, 1_000_000), (2.0, 2_000_000),
                         (3.0, 3_000_000), (4.0, 4_000_000)], maxlen=6)
        self.assertEqual(JobRunner._smoothed_speed(samples), 1_000_000)

    def _fake_engine(self, directory: Path, *, fail=False, slow=False) -> PythonMockEngine:
        path = directory / 'fake_engine.py'
        body = [
            'import pathlib, sys, time',
            'source = pathlib.Path(sys.argv[1])',
            'assert sys.argv[2] == "-o"',
            'out = pathlib.Path(sys.argv[3])',
            'out.mkdir(parents=True, exist_ok=True)',
            '(out / "content.bin").write_bytes(source.read_bytes())',
            'print("sample extraction", flush=True)',
        ]
        if slow:
            body.append('time.sleep(10)')
        if fail:
            body.append('sys.exit(9)')
        path.write_text('\n'.join(body) + '\n', encoding='utf-8')
        return PythonMockEngine(path)

    def _collect(self, events: queue.Queue) -> list[tuple]:
        all_events = []
        while not events.empty():
            all_events.append(events.get_nowait())
        return all_events

    def test_end_to_end_two_packages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = self._fake_engine(root)
            a, b = root / 'First.pkg', root / 'Second.pkg'
            a.write_bytes(b'hello')
            b.write_bytes(b'world')
            out = root / 'out'
            jobs = plan_jobs([a, b], out)
            events = queue.Queue()
            runner = JobRunner(events)
            runner.start(jobs, engine)
            runner.thread.join(timeout=12)
            self.assertFalse(runner.active)
            self.assertEqual((out / 'First' / 'content.bin').read_bytes(), b'hello')
            self.assertEqual((out / 'Second' / 'content.bin').read_bytes(), b'world')
            self.assertEqual(a.read_bytes(), b'hello')
            self.assertEqual(b.read_bytes(), b'world')
            self.assertIn(('finished', 2, 0, False), self._collect(events))

    def test_runner_reports_live_file_and_byte_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = self._fake_engine(root, slow=True)
            source = root / 'Metrics.pkg'
            source.write_bytes(b'bytes')
            events = queue.Queue()
            runner = JobRunner(events)
            runner.start(plan_jobs([source], root / 'out'), engine)
            deadline = time.monotonic() + 4
            metrics = []
            while time.monotonic() < deadline:
                metrics.extend(event for event in self._collect(events) if event[0] == 'metrics')
                if any(event[2] == 1 and event[3] == 5 for event in metrics):
                    break
                time.sleep(0.05)
            runner.cancel()
            runner.thread.join(timeout=8)
            self.assertFalse(runner.active)
            self.assertTrue(any(event[2] == 1 and event[3] == 5 for event in metrics), metrics)

    def test_progress_log_is_periodic_and_engine_messages_are_forwarded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = self._fake_engine(root, slow=True)
            source = root / 'Progress.pkg'
            source.write_bytes(b'bytes')
            events = queue.Queue()
            runner = JobRunner(events)
            with patch('pkg_batch_extractor.runner.METRIC_SAMPLE_INTERVAL', 0.03), \
                 patch('pkg_batch_extractor.runner.PROGRESS_LOG_INTERVAL', 0.09):
                runner.start(plan_jobs([source], root / 'out'), engine)
                deadline = time.monotonic() + 3
                observed = []
                while time.monotonic() < deadline:
                    observed.extend(self._collect(events))
                    if any(event[0] == 'log' and str(event[1]).startswith('Progress:')
                           for event in observed):
                        break
                    time.sleep(0.02)
                runner.cancel()
                runner.thread.join(timeout=8)
                observed.extend(self._collect(events))

            log_lines = [str(event[1]) for event in observed if event[0] == 'log']
            self.assertTrue(any(line.startswith('[Progress.pkg] sample extraction')
                                for line in log_lines), log_lines)
            progress = [line for line in log_lines if line.startswith('Progress:')]
            self.assertTrue(progress, log_lines)
            self.assertRegex(progress[0], r'^Progress: Progress\.pkg • 00:00:\d{2} elapsed$')
            self.assertNotRegex(progress[0], r'\b(files|written|MB/s|KB|MB|GB)\b')

    def test_short_extraction_keeps_result_without_final_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = self._fake_engine(root)
            source = root / 'Quick.pkg'
            source.write_bytes(b'quick data')
            events = queue.Queue()
            runner = JobRunner(events)
            runner.start(plan_jobs([source], root / 'out'), engine)
            runner.thread.join(timeout=8)
            logs = [event[1] for event in self._collect(events) if event[0] == 'log']
            self.assertTrue(any(str(line).startswith('Done: Quick.pkg ->') for line in logs), logs)
            self.assertFalse(any('Final snapshot:' in str(line) for line in logs), logs)
            self.assertFalse(any(str(line).startswith('Progress:') for line in logs), logs)

    def test_title_id_names_published_output_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script = root / 'engine.py'
            script.write_text(r'''import pathlib, struct, sys
out = pathlib.Path(sys.argv[3]); out.mkdir(parents=True)
s = out / "sce_sys"; s.mkdir()
key = b"TITLE_ID\0"; value = b"CUSA01022\0"; kb = 36; db = kb + len(key)
entry = struct.pack("<HHIII", 0, 0x0204, len(value), len(value), 0)
(s / "param.sfo").write_bytes(struct.pack("<4sIIII", b"\0PSF", 0x101, kb, db, 1) + entry + key + value)
(out / "game.bin").write_bytes(b"data")
''', encoding='utf-8')
            engine = PythonMockEngine(script)
            source = root / 'OriginalName.pkg'; source.write_bytes(b'pkg')
            events = queue.Queue(); runner = JobRunner(events)
            runner.start(plan_jobs([source], root / 'out'), engine)
            runner.thread.join(timeout=12)
            self.assertFalse(runner.active)
            self.assertTrue((root / 'out' / 'CUSA01022' / 'game.bin').is_file())
            self.assertIn(('finished', 1, 0, False), self._collect(events))

    def test_failed_extract_keeps_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = self._fake_engine(root, fail=True)
            source = root / 'Fail.pkg'
            source.write_bytes(b'keep input')
            events = queue.Queue()
            runner = JobRunner(events)
            runner.start(plan_jobs([source], root / 'out'), engine)
            runner.thread.join(timeout=12)
            self.assertFalse((root / 'out' / 'Fail').exists())
            self.assertEqual(source.read_bytes(), b'keep input')
            leftovers = list((root / 'out').glob('.pkg-batch-partial-*'))
            self.assertEqual(len(leftovers), 1)
            self.assertEqual((leftovers[0] / 'payload' / 'content.bin').read_bytes(), b'keep input')
            self.assertIn(('finished', 0, 1, False), self._collect(events))

    def test_cancel_before_second_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = self._fake_engine(root, slow=True)
            a, b = root / 'Slow.pkg', root / 'Waiting.pkg'
            a.write_bytes(b'slow')
            b.write_bytes(b'wait')
            events = queue.Queue()
            runner = JobRunner(events)
            runner.start(plan_jobs([a, b], root / 'out'), engine)
            deadline = time.monotonic() + 6
            while not (root / 'out').exists() and time.monotonic() < deadline:
                time.sleep(.05)
            runner.cancel()
            runner.thread.join(timeout=9)
            self.assertFalse(runner.active)
            self.assertFalse((root / 'out' / 'Waiting').exists())
            self.assertIn(('finished', 0, 0, True), self._collect(events))


if __name__ == '__main__':
    unittest.main()
