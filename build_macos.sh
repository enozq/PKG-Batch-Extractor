#!/usr/bin/env sh
set -eu
if [ "$(uname -s)" != "Darwin" ]; then
  echo "Use build_linux.sh for Linux or build_windows.bat for Windows" >&2
  exit 1
fi
cd "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v cargo-about >/dev/null 2>&1; then
  cargo install cargo-about --version 0.9.2 --locked --features cli
fi
build_root=$(mktemp -d)
trap 'rm -rf "$build_root"' EXIT HUP INT TERM
git -c core.autocrlf=false clone --depth 1 --branch v0.0.1 https://github.com/paulomanrique/ps4-pkg-extractor.git "$build_root/pkgextract-source"
test "$(git -C "$build_root/pkgextract-source" rev-parse HEAD)" = f830abb76ef1cbb32c2f67c842a86187fa7f2d7c
cp "$PWD/packaging/pkgextract-Cargo.lock" "$build_root/pkgextract-source/Cargo.lock"
cargo build --release --locked --manifest-path "$build_root/pkgextract-source/Cargo.toml"
export PKG_BATCH_EXTRACTOR_ENGINE="$build_root/pkgextract-source/target/release/pkgextract"
export PKG_BATCH_EXTRACTOR_ENGINE_LICENSE="$build_root/pkgextract-source/LICENSE"
export PKG_BATCH_EXTRACTOR_ENGINE_LOCK="$build_root/pkgextract-source/Cargo.lock"
cargo about generate "$PWD/packaging/rust-third-party.hbs" --config "$PWD/packaging/cargo-about.toml" --output-file "$build_root/pkgextract-source/pkgextract-RUST-THIRD-PARTY.md" --locked --manifest-path "$build_root/pkgextract-source/Cargo.toml" --fail
export PKG_BATCH_EXTRACTOR_RUST_NOTICES="$build_root/pkgextract-source/pkgextract-RUST-THIRD-PARTY.md"
python3 -m pip install -r requirements-build.txt
python3 build.py
