# Bundled and optional third-party components

Packaged desktop builds include `pkgextract` from `paulomanrique/ps4-pkg-extractor` tag `v0.0.1`, pinned to commit `f830abb76ef1cbb32c2f67c842a86187fa7f2d7c`. Its upstream repository identifies The Unlicense as its license. It is built from source per target OS and architecture and shipped as a separate executable component together with its upstream license and the reviewed lockfile in `packaging/pkgextract-Cargo.lock`. That lockfile updates vulnerable transitive crates with compatible patched releases where available. RustSec still reports the upstream `rsa` Marvin timing advisory; the dependency performs RSA private-key decryption with fixed key material embedded in the upstream source, and no patched `rsa` release is available. The advisory describes recovery through timing visible over a network and states local use on a non-compromised computer is fine; this desktop application processes user-selected PKGs locally and exposes no remote decryption service ([RustSec RUSTSEC-2023-0071](https://rustsec.org/advisories/RUSTSEC-2023-0071.html)). The fixed keys are part of the openly distributed upstream extractor, not user credentials. Its direct `orbis-pkg-util` library dependency declares MIT OR Apache-2.0. The app itself remains MIT-licensed. No PKG/game files or user credentials are redistributed.

- [paulomanrique/ps4-pkg-extractor](https://github.com/paulomanrique/ps4-pkg-extractor/tree/f830abb76ef1cbb32c2f67c842a86187fa7f2d7c) — The Unlicense — `pkgextract INPUT.pkg -o OUTPUT_DIR`. The packaging workflow verifies this source revision and builds it with Cargo for each target platform.
- [videobitva/orbis](https://github.com/videobitva/orbis) — the `orbis-pkg-util` direct dependency declares Apache-2.0 OR MIT; see its upstream `LICENSE-APACHE` and `LICENSE-MIT` files.
- [maxton/LibOrbisPkg](https://github.com/maxton/LibOrbisPkg) — LGPL-3.0 — `PkgTool[.Core] pkg_extract INPUT.pkg OUTPUT_DIR`. `.dll` launch via `dotnet` is supported but depends on matching runtime and accompanying libraries. Native Linux / macOS and Windows variants are distributed independently by upstream.

Runtime components included in packaged builds:
- `tkinterdnd2` — MIT; it supplies the Python drag-and-drop wrapper and platform-specific TkDND files.
- TkDND — upstream `license.terms`; its copyright and license text must accompany distributed copies.
- Python — the matching interpreter's `LICENSE.txt`/`LICENSE`, copied by the build into the package.
- Tcl and Tk — upstream permissive `license.terms`, copied into the package.
- PyInstaller embeds its bootloader and runtime hooks. Its bootloader exception permits generated bundles under the application's chosen license; the PyInstaller `COPYING.txt` (including the runtime-hook license terms) is shipped for reference.

The build generates `pkgextract-RUST-THIRD-PARTY.md` with pinned cargo-about 0.9.2 from the complete locked Cargo graph and carries it alongside `Cargo.lock` and the engine's Unlicense. The report contains each resolved Rust license text and its crates; the engine's missing Cargo manifest license field is clarified only against the pinned upstream `LICENSE` file and its SHA-256. A build fails if notice generation fails. Do not treat this document as legal advice.

Build tools (not bundled as application components):
- PyInstaller is used to produce executables. Its bootloader exception permits distribution of generated bundles under the app's license, subject to bundled dependency licenses.

Our application source is MIT licensed, which does not change third-party terms. Upstream releases and architecture support may change. Attribution does not imply upstream endorsement.
