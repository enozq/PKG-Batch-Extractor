"""Sequential PKG extraction with staging, bounded logs and process-tree cancellation.

Each subprocess is isolated so cancelling an extraction does not leave its
helper processes running. UI events are delivered via a thread-safe Queue.
"""
from __future__ import annotations

import os
from pathlib import Path
import queue
from collections import deque
from statistics import median
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

from .backend import Extractor
from .core import Job, find_title_id, next_available_target

EventQueue = queue.Queue[tuple[Any, ...]]
MAX_ENGINE_LOG_LINES = 2500
METRIC_SAMPLE_INTERVAL = 1.0
PROGRESS_LOG_INTERVAL = 5.0
SPEED_SAMPLE_COUNT = 6


class JobRunner:
    def __init__(self, events: EventQueue):
        self.events = events
        self.cancelled = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, jobs: list[Job], extractor: Extractor) -> None:
        if self.active:
            raise RuntimeError('Extraction is already running')
        self.cancelled.clear()
        self.thread = threading.Thread(target=self._work, args=(list(jobs), extractor), daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        self.cancelled.set()

    def _notify(self, *event: Any) -> None:
        self.events.put(event)

    @staticmethod
    def _measure_tree(root: Path) -> tuple[int, int]:
        """Return regular file count and bytes currently visible under root."""
        file_count = 0
        byte_count = 0
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                file_count += 1
                                byte_count += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            # Files may be renamed or removed while an engine writes.
                            continue
            except OSError:
                continue
        return file_count, byte_count

    @staticmethod
    def _smoothed_speed(samples: deque[tuple[float, int]]) -> float | None:
        """Return a robust recent output rate, suppressing short write bursts.

        Tree scans can observe a whole file only after it has been written, so a
        single delta may look like an implausibly fast transfer. Require several
        intervals and report their median instead of the latest instantaneous
        delta. A zero median means output has paused; in that case omit the rate.
        """
        rates = []
        for (old_time, old_bytes), (new_time, new_bytes) in zip(samples, list(samples)[1:]):
            elapsed = new_time - old_time
            if elapsed > 0 and new_bytes >= old_bytes:
                rates.append((new_bytes - old_bytes) / elapsed)
        if len(rates) < 4:
            return None
        smoothed = median(rates)
        return smoothed if smoothed > 0 else None

    @staticmethod
    def _progress_log_line(name: str, elapsed: float) -> str:
        seconds = max(0, int(elapsed))
        duration = f'{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}'
        return f'Progress: {name} • {duration} elapsed'

    def _work(self, jobs: list[Job], extractor: Extractor) -> None:
        completed = 0
        failed = 0
        try:
            for number, job in enumerate(jobs):
                if self.cancelled.is_set():
                    for remaining in range(number, len(jobs)):
                        self._notify('status', remaining, 'Cancelled', '')
                    break
                self._notify('status', number, 'Extracting', '')
                result, message = self._extract(job, extractor)
                if result == 'Completed':
                    completed += 1
                elif result == 'Failed':
                    failed += 1
                self._notify('status', number, result, message)
                self._notify('progress', number + 1, len(jobs), completed, failed)
                if result == 'Cancelled':
                    for remaining in range(number + 1, len(jobs)):
                        self._notify('status', remaining, 'Cancelled', '')
                    break
        except Exception as exc:
            # Preserve runner liveness and mark any unhandled errors in logs.
            self._notify('log', f'Unexpected runner error: {exc}')
        finally:
            self._notify('finished', completed, failed, self.cancelled.is_set())

    @staticmethod
    def _stop_tree(process: subprocess.Popen[str]) -> None:
        """Stop a spawned engine and children (best effort on each platform)."""
        if os.name == 'nt':
            # taskkill /T is needed because many .NET/Rust wrappers spawn helpers.
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL, timeout=5, check=False,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return

        # start_new_session=True lets POSIX signal the whole child process group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The leader may exit before children. Kill survivors in its group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait(timeout=3)

    def _extract(self, job: Job, extractor: Extractor) -> tuple[str, str]:
        target = job.destination
        staging: Path | None = None
        try:
            if not job.source.is_file():
                raise FileNotFoundError(f'Input PKG is missing: {job.source}')
            target.parent.mkdir(parents=True, exist_ok=True)
            # pkgextract refuses an *existing* output directory without -f.
            # Give every CLI a NONEXISTENT payload path within a unique staging
            # directory; never enable an engine's overwrite flag.
            staging = Path(tempfile.mkdtemp(prefix='.pkg-batch-partial-', dir=target.parent))
            payload = staging / 'payload'
            command = extractor.command(job.source, payload)
            if self.cancelled.is_set():
                return 'Cancelled', f'No engine started; empty stage: {staging}'
            self._notify('log', f'Start: {job.source.name}')
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            with subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                bufsize=1, creationflags=flags,
                start_new_session=os.name != 'nt',
            ) as process:
                pump = threading.Thread(target=self._drain_output, args=(process, job.source.name), daemon=True)
                pump.start()
                started = time.monotonic()
                next_metrics = started
                next_progress_log = started + PROGRESS_LOG_INTERVAL
                speed_samples: deque[tuple[float, int]] = deque(maxlen=SPEED_SAMPLE_COUNT)
                while True:
                    now = time.monotonic()
                    if now >= next_metrics:
                        file_count, byte_count = self._measure_tree(payload)
                        if speed_samples and byte_count < speed_samples[-1][1]:
                            # A file was replaced/truncated; restart the rate window.
                            speed_samples.clear()
                        speed_samples.append((now, byte_count))
                        speed = self._smoothed_speed(speed_samples)
                        self._notify('metrics', job.source.name, file_count, byte_count,
                                     int(now - started), speed)
                        if now >= next_progress_log:
                            self._notify('log', self._progress_log_line(job.source.name, now - started))
                            next_progress_log = now + PROGRESS_LOG_INTERVAL
                        next_metrics = now + METRIC_SAMPLE_INTERVAL
                    if process.poll() is not None:
                        break
                    if self.cancelled.is_set():
                        self._stop_tree(process)
                        pump.join(timeout=3)
                        self._notify('log', f'Cancelled: {job.source.name}')
                        return 'Cancelled', f'Partial files kept at: {staging}'
                    time.sleep(0.08)
                file_count, byte_count = self._measure_tree(payload)
                now = time.monotonic()
                if speed_samples and byte_count < speed_samples[-1][1]:
                    speed_samples.clear()
                speed_samples.append((now, byte_count))
                speed = self._smoothed_speed(speed_samples)
                self._notify('metrics', job.source.name, file_count, byte_count,
                             int(now - started), speed)
                pump.join(timeout=3)
                # A last-moment cancel must not publish a completed directory.
                if self.cancelled.is_set():
                    self._stop_tree(process)
                    return 'Cancelled', f'Partial files kept at: {staging}'
                if process.returncode != 0:
                    self._notify('log', f'Failed ({process.returncode}): {job.source.name}')
                    return 'Failed', f'Exit code {process.returncode}; partial files: {staging}'
            if not payload.is_dir() or not any(payload.iterdir()):
                return 'Failed', f'Engine produced no files; partial stage: {staging}'
            if self.cancelled.is_set():
                return 'Cancelled', f'Partial files kept at: {staging}'
            title_id = find_title_id(payload)
            if title_id:
                target = target.parent / title_id
                self._notify('log', f'Title ID: {title_id}')
            target = next_available_target(target)
            if target.exists() or target.is_symlink():
                raise FileExistsError(f'Output folder already exists: {target}')
            payload.rename(target)
            # Only the empty staging wrapper is removed after a complete run.
            staging.rmdir()
            self._notify('log', f'Done: {job.source.name} -> {target}')
            return 'Completed', str(target)
        except Exception as exc:
            self._notify('log', f'Error extracting {job.source.name}: {exc}')
            extra = f'; partial files: {staging}' if staging and staging.exists() else ''
            return 'Failed', f'{exc}{extra}'

    def _drain_output(self, process: subprocess.Popen[str], name: str) -> None:
        assert process.stdout is not None
        try:
            count = 0
            suppressed = 0
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                if count < MAX_ENGINE_LOG_LINES:
                    self._notify('log', f'[{name}] {line[:800]}')
                    count += 1
                else:
                    suppressed += 1
            if suppressed:
                self._notify('log', f'[{name}] {suppressed} additional engine log lines suppressed.')
        except (ValueError, OSError):
            pass
