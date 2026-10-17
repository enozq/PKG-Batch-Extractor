#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
APPIMAGETOOL=${APPIMAGETOOL:-appimagetool}
command -v "$APPIMAGETOOL" >/dev/null 2>&1 || {
  echo "appimagetool is required (set APPIMAGETOOL to its executable path)." >&2
  exit 1
}
APPDIR="$ROOT/dist/PKG-Batch-Extractor.AppDir"
BUILD_IMAGE="$ROOT/dist/.PKG-Batch-Extractor-x86_64.$$.AppImage"
trap 'rm -f "$BUILD_IMAGE"' EXIT HUP INT TERM
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$APPDIR/usr/lib/pkg-batch-extractor/tools" "$APPDIR/usr/share/licenses/pkg-batch-extractor"
cp "$ROOT/dist/PKG-Batch-Extractor" "$APPDIR/usr/bin/PKG-Batch-Extractor"
cp "$ROOT/dist/tools/pkgextract" "$APPDIR/usr/lib/pkg-batch-extractor/tools/pkgextract"
cp "$ROOT/dist/THIRD_PARTY.md" "$ROOT/dist/LICENSE" "$APPDIR/usr/share/licenses/pkg-batch-extractor/"
mkdir -p "$APPDIR/usr/share/licenses/pkg-batch-extractor/licenses"
cp -R "$ROOT/dist/licenses/." "$APPDIR/usr/share/licenses/pkg-batch-extractor/licenses/"
cp "$ROOT/dist/pkgextract-LICENSE.txt" "$ROOT/dist/pkgextract-Cargo.lock" "$ROOT/dist/pkgextract-RUST-THIRD-PARTY.md" "$APPDIR/usr/share/licenses/pkg-batch-extractor/"
cp "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/pkg-batch-extractor.desktop" "$APPDIR/PKG-Batch-Extractor.desktop"
cp "$ROOT/packaging/pkg-batch-extractor.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/pkg-batch-extractor.svg"
cp "$ROOT/assets/app-icon.png" "$APPDIR/pkg-batch-extractor.png"
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/PKG-Batch-Extractor" "$APPDIR/usr/lib/pkg-batch-extractor/tools/pkgextract"
if [ -n "${APPIMAGETOOL_RUNTIME_FILE:-}" ]; then
  APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$APPIMAGETOOL" --runtime-file "$APPIMAGETOOL_RUNTIME_FILE" "$APPDIR" "$BUILD_IMAGE"
else
  APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$BUILD_IMAGE"
fi
mv -f "$BUILD_IMAGE" "$ROOT/dist/PKG-Batch-Extractor-x86_64.AppImage"
echo "Built: $ROOT/dist/PKG-Batch-Extractor-x86_64.AppImage"
