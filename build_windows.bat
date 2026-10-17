@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%~dp0build-venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0..\build-venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Python 3.11 build environment not found: "%PYTHON%"
  echo Create it with: py -3.11 -m venv build-venv
  exit /b 1
)

set "CARGO=%USERPROFILE%\.cargo\bin\cargo.exe"
if not exist "%CARGO%" (
  for /f "delims=" %%I in ('where cargo.exe 2^>nul') do if not defined CARGO_FOUND set "CARGO_FOUND=%%I"
  if defined CARGO_FOUND set "CARGO=%CARGO_FOUND%"
)

if not exist "%CARGO%" (
  echo Rust Cargo was not found. Install Rust or add cargo.exe to PATH.
  exit /b 1
)
for %%I in ("%CARGO%") do set "CARGO_DIR=%%~dpI"
set "PATH=%CARGO_DIR%;%PATH%"
where cargo-about.exe >nul 2>nul
if errorlevel 1 (
  echo Installing pinned cargo-about license audit tool...
  "%CARGO%" install cargo-about --version 0.9.2 --locked --features cli
  if errorlevel 1 exit /b 1
)

set "GIT=C:\Program Files\Git\cmd\git.exe"
if not exist "%GIT%" (
  set "GIT="
  for /f "delims=" %%I in ('where git.exe 2^>nul') do if not defined GIT set "GIT=%%I"
)
if not defined GIT (
  echo Git was not found. Install Git or add git.exe to PATH.
  exit /b 1
)

"%PYTHON%" -c "import PyInstaller, tkinterdnd2" >nul 2>nul
if errorlevel 1 (
  echo Installing build dependencies into build-venv...
  "%PYTHON%" -m pip install -r requirements-build.txt
  if errorlevel 1 exit /b 1
)

if not exist ".tmp" mkdir ".tmp"
if errorlevel 1 exit /b 1
:choose_build_root
set "PKG_BUILD_ROOT=%~dp0.tmp\pkgextract-build-%RANDOM%"
if exist "%PKG_BUILD_ROOT%" goto choose_build_root
mkdir "%PKG_BUILD_ROOT%"
if errorlevel 1 exit /b 1

"%GIT%" -c core.autocrlf=false clone --depth 1 --branch v0.0.1 https://github.com/paulomanrique/ps4-pkg-extractor.git "%PKG_BUILD_ROOT%\source"
if errorlevel 1 goto error
set "PKG_BUILD_REVISION="
for /f %%i in ('""%GIT%" -C "%PKG_BUILD_ROOT%\source" rev-parse HEAD"') do set "PKG_BUILD_REVISION=%%i"
if not "%PKG_BUILD_REVISION%"=="f830abb76ef1cbb32c2f67c842a86187fa7f2d7c" (
  echo Unexpected pkgextract source revision: %PKG_BUILD_REVISION%
  goto error
)

rem Keep compiler diagnostics reproducible without embedding the builder's user path.
set "RUSTFLAGS=-C target-feature=+crt-static --remap-path-prefix=%USERPROFILE%=<USER>"
"%CARGO%" build --release --locked --manifest-path "%PKG_BUILD_ROOT%\source\Cargo.toml"
if errorlevel 1 goto error

set "PKG_BATCH_EXTRACTOR_ENGINE=%PKG_BUILD_ROOT%\source\target\release\pkgextract.exe"
set "PKG_BATCH_EXTRACTOR_ENGINE_LICENSE=%PKG_BUILD_ROOT%\source\LICENSE"
set "PKG_BATCH_EXTRACTOR_ENGINE_LOCK=%PKG_BUILD_ROOT%\source\Cargo.lock"
set "PKG_WINDOWS_DIST=%PKG_BUILD_ROOT%\windows-dist"
set "PKG_BATCH_EXTRACTOR_DIST_DIR=%PKG_WINDOWS_DIST%"
cargo about generate "%~dp0packaging\rust-third-party.hbs" --config "%~dp0packaging\cargo-about.toml" --output-file "%PKG_BUILD_ROOT%\source\pkgextract-RUST-THIRD-PARTY.md" --locked --manifest-path "%PKG_BUILD_ROOT%\source\Cargo.toml" --fail
if errorlevel 1 goto error
set "PKG_BATCH_EXTRACTOR_RUST_NOTICES=%PKG_BUILD_ROOT%\source\pkgextract-RUST-THIRD-PARTY.md"
"%PYTHON%" build.py
if errorlevel 1 goto error

if not exist "%PKG_WINDOWS_DIST%\tools\pkgextract.exe" (
  echo Windows PKG engine was not produced in the clean staging directory.
  goto error
)
if exist "%PKG_WINDOWS_DIST%\tools\pkgextract" (
  echo Unexpected non-Windows PKG engine found in Windows staging directory.
  goto error
)
powershell.exe -NoProfile -NonInteractive -Command "Compress-Archive -Force -Path '%PKG_WINDOWS_DIST%\*' -DestinationPath '%PKG_BUILD_ROOT%\PKG-Batch-Extractor-Windows-x64.zip'"
if errorlevel 1 goto error
copy /y "%PKG_WINDOWS_DIST%\PKG-Batch-Extractor.exe" "dist\PKG-Batch-Extractor.exe" >nul
if errorlevel 1 goto error
copy /y "%PKG_BUILD_ROOT%\PKG-Batch-Extractor-Windows-x64.zip" "dist\PKG-Batch-Extractor-Windows-x64.zip" >nul
if errorlevel 1 goto error

rmdir /s /q "%PKG_BUILD_ROOT%"
echo Built: dist\PKG-Batch-Extractor.exe
echo Portable package: dist\PKG-Batch-Extractor-Windows-x64.zip
exit /b 0

:error
if exist "%PKG_BUILD_ROOT%" rmdir /s /q "%PKG_BUILD_ROOT%"
echo Build failed. Check errors above.
exit /b 1
