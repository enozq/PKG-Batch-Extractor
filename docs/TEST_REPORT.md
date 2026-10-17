# Validation report

Date: 2026-10-17. Windows checks used Python 3.11.9 from the project's `build-venv`; Linux checks ran in WSL Ubuntu 22.04.5 (glibc 2.35) with Python 3.11.17.

| Check | Result |
| --- | --- |
| Windows unit, synthetic-engine integration, build helper and hardening suite | **62 tests run: 60 passed, 2 skipped** (POSIX-only symlink and process-group cases) |
| Windows Python bytecode compilation | **Passed** for `src`, `tests`, `run.py` and `build.py` |
| Windows Tk GUI smoke | **Passed**: UI load, file selection, failure/retry, success notification, final result in exported log and queue progress; no final snapshot line |
| v1.0.0 Windows PyInstaller build | **Passed** again from current source into a fresh output directory; app EXE and adjacent `tools/pkgextract.exe` included |
| Bundled Windows engine | **Passed**: freshly rebuilt `pkgextract.exe --help` returned successfully |
| Portable ZIP | **Passed**: recreated from the fresh build with app, engine and license notices; archive contents inspected |
| Packaged Windows GUI startup | **Passed**: current ZIP extracted to a fresh directory, bundled engine help passed, and GUI became responsive and remained open with a restricted system-only `PATH` |
| Linux source tests | **Passed** under Ubuntu 22.04.5 / glibc 2.35: 62 tests passed; bytecode compilation passed |
| Linux Tk GUI smoke | **Passed** under Xvfb: load, file selection, failure/retry, success notice, final result in exported log; no final snapshot line |
| Linux v1.0.0 AppImage | **Passed** on Ubuntu 22.04.5 / glibc 2.35: package extracted, bundled `pkgextract --help` passed, and GUI stayed open for 8 seconds under Xvfb with a restricted `PATH` |
| Extraction Log progress records | **Passed**: regression tests verified elapsed-only periodic lines, no final snapshot, engine-message forwarding, and explicit success/failure/cancel results |
| Real PS4 PKG extraction | **NOT TESTED**: no suitable authorized PKG fixture was available; synthetic CLI fixtures cover the runner only |
| macOS Intel/Apple Silicon packages | **NOT TESTED** in this Windows environment; macOS remains experimental |
| GitHub Actions | Workflow configuration is present, but CI was not run from this workspace |
| README screenshot | **Passed**: current v1.0.0 interface captured with three clearly labeled sample packages; the image does not imply a real extraction |

Windows builds are unsigned and can prompt SmartScreen. The refreshed local AppImage was built from the same updated source and smoke-tested under Ubuntu 22.04.5 / glibc 2.35; systems below this glibc baseline, Alpine/musl, and ARM Linux were not tested. GitHub Actions was not run from this workspace. macOS Gatekeeper and notarization were not validated. Automated extraction tests use synthetic data and do not establish compatibility with every real package.

## Reproduce on Windows

```powershell
python -m unittest discover -s tests -v
python tools/gui_smoke.py
python -m compileall -q src tests tools run.py build.py
build_windows.bat
```
