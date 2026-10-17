# Changelog

## 1.0.0 — Stable Windows and Linux targets (2026-10-16)

- Declared Windows 10/11 x64 and Linux x86-64 as official targets; macOS builds remain experimental.
- Replaced the bouncing indeterminate animation with a stable, left-to-right determinate bar that advances by packages processed. No within-package percentage or ETA is invented.
- Updated the app and project metadata to version 1.0.0 and refreshed the GitHub-ready README and interface screenshot.
- Documented offline portable package requirements and Linux AppImage compatibility limits.
- Added regressions for package-count progress and current release documentation.

## 0.3.1 — UI cleanup and responsiveness (2026-10-16)


- Removed the small descriptive subtitle underneath **PKG Batch Extractor**, as requested; tightened header spacing and updated the screenshot.
- Switched the package progress bar to track processed package count rather than displaying an indefinite spinner throughout the entire batch.
- Capped GUI queue event handling to 150 notifications per event-loop tick so large engine logs cannot monopolize the main thread.
- Replaced repeated log-history slicing with a fixed-size deque and chunk-trimmed the visible log widget for lower overhead.
- Debounced output-directory changes to avoid rebuilding the whole PKG list for every typed character.
- Fixed stale failed-job retry state after clearing or removing PKGs; guarded a runner-start race.
- Added Ctrl/Cmd+O and Ctrl/Cmd+Shift+O file/folder shortcuts.
- Added 6 headless GUI logic regressions (35 automated tests total) and strengthened the real Tk smoke checks.
- Linux Tk virtual-display test and 35 tests passed; real PS4 PKG, Windows/macOS runtimes, and binary builds remain unverified.

## 0.3.0 — Safer extraction and retries (2026-10-16)

- Fixed compatibility with CLI engines that refuse pre-existing output directories: commands now receive a nonexistent staging `payload/` target; only successful output is published.
- Added a **Retry failed** action and **Save log** action in the GUI.
- Improved cancellation of child process trees with POSIX process groups and Windows `taskkill /T`, including late cancellation checks.
- Bounded subprocess output notifications to protect UI responsiveness when CLIs print thousands of lines; log export retains the most recent 10,000 messages.
- Added collision avoidance for dangling symlink output paths.
- Added nine automated test cases (29 total) including POSIX child-process cancellation, output collision races, non-existent staging target, unicode paths, empty output, excessive logs, missing inputs, and error preservation.
- Ran actual Tk GUI smoke in Linux virtual display, including deliberate failure, retry and log export.
- Refreshed GUI screenshot, docs and version numbers; maintained Windows/Linux/macOS build recipes.
- Linux PyInstaller package build could not be completed locally because dependencies were not installed and the environment had no package-index access. Windows/macOS builds and real PKG extraction remain unverified.


## 0.2.0 — Cross-platform source preview (2026-10-15)

- Added platform-independent launch and build scripts for Windows, Linux, and macOS.
- Added PyInstaller `.exe`, Linux executable, and macOS `.app` build configurations.
- Added GitHub Actions matrix for Windows x64, Linux x64, macOS x64 and macOS arm64 artifacts.
- Extended CI tests to Windows, Linux and macOS; fake-engine end-to-end tests now run across platforms.
- Fixed engine discovery to prioritize native platform binaries, with optional `PkgTool.Core.dll` + .NET support.
- Added macOS app-bundle-relative `tools/` discovery, macOS configuration directory, macOS fonts/shortcut, and Unix engine picker.
- Added resilient TkDnD fallback for native library loading failures.
- 20 automated tests pass in local Linux environment. Real PKG / other-platform binaries remain unverified.

## 0.1.0 — First source preview (2026-10-15)

- Created dark-themed desktop GUI with batch file/folder selection.
- Added optional native drag-and-drop integration, if TkinterDnD2 is installed.
- Added user-supplied `pkgextract` and `PkgTool` engine adapters.
- Added a sequential extraction queue, readable log, and cancel button.
- Added collision-safe output folders and staging-to-final publication.
- Added unit/integration tests using a fake extractor, CI test matrix, and Windows build workflow.

