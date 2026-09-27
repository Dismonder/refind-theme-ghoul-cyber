#!/usr/bin/env python3
"""Build every release asset of Ghoul Cyber into release/<version>/.

    python3 tools/make_release.py --version v2.0.0

Produces:
  refind-theme-ghoul-cyber-<version>.zip   installer + all themes (git archive)
  ghoul-cyber-<version>-<theme>-<res>.zip  ready-made theme for manual install, one per theme
                                           and resolution (4k, 1440p, 1080p)
  SHA256SUMS.txt

Ready-made packages are built for nobody's PC in particular: no hardware rows on
the background and the default tile numbering. The installer builds the personal
version (your hardware, your systems, your settings) on the target machine.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESOLUTIONS = {"4k": (3840, 2160), "1440p": (2560, 1440), "1080p": (1920, 1080)}

INSTALL_TXT = """Ghoul Cyber {version} - {theme} - {res} ({width}x{height})
================================================================

Recommended: use the installer instead (refind-theme-ghoul-cyber-{version}.zip).
It builds the theme for your own PC - your hardware on the background, your
systems numbered in order, your settings - and installs rEFInd if it is missing.

Manual install (this package):
 1. Copy the folder "ghoul-cyber" to the EFI partition as
      EFI/refind/themes/ghoul-cyber
    (Linux: usually /boot/efi/EFI/refind or /boot/EFI/refind.
     Windows: open an administrator terminal, "mountvol S: /S", then S:\\EFI\\refind)
 2. Add this line at the end of EFI/refind/refind.conf:
      include themes/ghoul-cyber/theme.conf
 3. Reboot.

Zalecane: użyj instalatora (refind-theme-ghoul-cyber-{version}.zip) - buduje
motyw pod Twój komputer i sam instaluje rEFInd, jeśli go brakuje.

Instalacja ręczna (ta paczka):
 1. Skopiuj folder "ghoul-cyber" na partycję EFI jako EFI/refind/themes/ghoul-cyber
 2. Dopisz na końcu EFI/refind/refind.conf linię:
      include themes/ghoul-cyber/theme.conf
 3. Uruchom komputer ponownie.
"""


def load_builder():
    spec = importlib.util.spec_from_file_location("build_and_deploy_theme", REPO / "build_and_deploy_theme.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_package(theme: str, res: str, version: str, out_dir: str) -> tuple[str, int]:
    """Build one theme at one resolution and zip it. Runs in a worker process."""
    b = load_builder()
    width, height = RESOLUTIONS[res]
    options = b.default_options()
    options["layout.resolution"] = f"{width}x{height}"
    options["hud.hardware"] = False                  # nobody's hardware on a shared package
    options["cards.order"] = b.NUMBERED_CARDS        # stable numbering, no detection on the build machine
    skin = None if theme == b.THEME_NAME else b.load_skin(theme)
    fan_art = bool(skin and json.loads((skin.art.parent / "theme.json").read_text(encoding="utf-8")).get("fan_art"))
    target = Path(out_dir) / f"ghoul-cyber-{version}-{theme}-{res}.zip"
    with tempfile.TemporaryDirectory(prefix="ghoul-release-") as raw:
        built = Path(raw) / b.THEME_NAME
        b.build_theme(REPO, built, b.Resolution(width, height), b.HardwareInfo(), skin=skin, options=options)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(built.rglob("*")):
                if path.is_file():
                    archive.write(path, f"ghoul-cyber/{path.relative_to(built).as_posix()}")
            archive.writestr("INSTALL.txt", INSTALL_TXT.format(
                version=version, theme=theme, res=res, width=width, height=height))
            if fan_art:
                archive.write(REPO / "themes" / "FAN-ART.md", "FAN-ART.md")
            archive.write(REPO / "LICENSE", "LICENSE")
    return target.name, target.stat().st_size


def source_archive(version: str, out_dir: Path) -> Path:
    target = out_dir / f"refind-theme-ghoul-cyber-{version}.zip"
    subprocess.run(["git", "-C", str(REPO), "archive", "--format=zip",
                    f"--prefix=refind-theme-ghoul-cyber-{version}/", "-o", str(target), "HEAD"], check=True)
    return target


def git_version() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "describe", "--tags", "--always"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "dev"


def main(argv: list[str] | None = None) -> int:
    b = load_builder()
    themes_all = [b.THEME_NAME, *b.list_skins()]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default=None, help="release version, e.g. v2.0.0 (default: git describe)")
    parser.add_argument("--out", type=Path, default=REPO / "release")
    parser.add_argument("--themes", nargs="*", default=themes_all, help="default: every theme")
    parser.add_argument("--resolutions", nargs="*", default=list(RESOLUTIONS), choices=list(RESOLUTIONS))
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--no-prebuilt", action="store_true", help="only the source archive")
    args = parser.parse_args(argv)

    version = args.version or git_version()
    unknown = sorted(set(args.themes) - set(themes_all))
    if unknown:
        parser.error(f"unknown themes: {', '.join(unknown)}")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("warning: uncommitted changes are NOT in the source archive (git archive uses HEAD)")

    out_dir = args.out / version
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*"):
        old.unlink()
    print(f"source archive: {source_archive(version, out_dir).name}")

    failures = []
    if not args.no_prebuilt:
        jobs = [(t, r) for t in args.themes for r in args.resolutions]
        print(f"building {len(jobs)} ready-made packages with {args.jobs} workers...")
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(build_package, t, r, version, str(out_dir)): (t, r) for t, r in jobs}
            for done, future in enumerate(as_completed(futures), 1):
                theme, res = futures[future]
                try:
                    name, size = future.result()
                    print(f"  [{done}/{len(jobs)}] {name}  {size / 1_000_000:.1f} MB")
                except Exception as exc:  # noqa: BLE001 - report every failed package, stop at the end
                    failures.append(f"{theme} {res}: {exc}")
                    print(f"  [{done}/{len(jobs)}] FAILED {theme} {res}: {exc}")

    sums = []
    for path in sorted(p for p in out_dir.iterdir() if p.suffix == ".zip"):
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (out_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    total = sum(p.stat().st_size for p in out_dir.iterdir())
    print(f"{len(sums)} archives + SHA256SUMS.txt in {out_dir} ({total / 1_000_000:.0f} MB)")
    if failures:
        print("FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
