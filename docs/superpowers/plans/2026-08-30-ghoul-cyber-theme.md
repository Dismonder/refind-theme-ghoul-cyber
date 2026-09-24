# Ghoul Cyber rEFInd Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować i zweryfikować samodzielny skrypt `build_and_deploy_theme.py`, który generuje motyw rEFInd ghoul-cyber w 4K oraz bezpiecznie wdraża go i przypisuje ikony trzem systemom po uruchomieniu na CachyOS.

**Architecture:** Jeden publiczny skrypt zawiera czyste, testowalne funkcje grafiki, telemetrii, parsowania UEFI i deployu. Build powstaje w stagingu, jest walidowany, a faza Linuksa przekazuje zweryfikowany plan do wąskiej operacji uprzywilejowanej; konfiguracja rEFInd jest aktywowana dopiero po udanym skopiowaniu motywu i ikon loaderów.

**Tech Stack:** Python 3.10+, Pillow, `argparse`, `dataclasses`, `pathlib`, `subprocess`, `unittest`, PowerShell/CIM na Windows oraz narzędzia UEFI/util-linux na Linuksie.

**Spec:** `docs/superpowers/specs/2026-08-30-ghoul-cyber-theme-design.md`

## Global Constraints

- Domyślna rozdzielczość wynosi dokładnie 3840x2160; `--resolution` akceptuje wyłącznie poprawne proporcje 16:9.
- Publicznym artefaktem wykonawczym jest pojedynczy `build_and_deploy_theme.py`; testy znajdują się w `tests/test_build_and_deploy_theme.py`.
- Wejścia są dopasowywane po dokładnym rdzeniu nazwy i rozszerzeniach PNG/JPG/JPEG; brak lub konflikt jest błędem.
- HUD używa pozycji (70, 60), interlinii 32 px i kolorów `#CCCCCC`, `#DCDCDC` oraz `#FF003C`.
- Rozmiary wyjściowe: OS 128x128, tools 48x48, selection_big 144x144, selection_small 56x56.
- `theme.conf` zachowuje treść zatwierdzoną w specyfikacji.
- Na Windows domyślne uruchomienie jest build-only; na Linuksie domyślnie następuje build, przypisanie ikon, deploy i aktywacja.
- Żadna operacja nie usuwa loadera EFI, wpisu NVRAM, partycji, obcego motywu ani nieznanego pliku.
- Repozytorium Git nie istnieje. Nie wykonywać commitów; po każdym zadaniu uruchomić wskazane testy, `python -m py_compile` oraz inspekcję zmienionych ścieżek.
- Wszystkie edycje wykonywać przez lokalne hunki `apply_patch`. Nie tworzyć plików tymczasowych w katalogu głównym projektu.

## File Map

- Create: `build_and_deploy_theme.py` — jedyny skrypt produkcyjny: CLI, grafika, detekcja, build, UEFI i deploy.
- Create: `tests/__init__.py` — umożliwia adresowanie pojedynczych testów przez `unittest`.
- Create: `tests/test_build_and_deploy_theme.py` — testy jednostkowe i integracyjne na katalogach tymczasowych.
- Read: `docs/superpowers/specs/2026-08-30-ghoul-cyber-theme-design.md` — źródło wymagań.
- Generate while verifying: `dist/ghoul-cyber/**` — wyłącznie pliki wynikowe skryptu.

---

### Task 1: Core contracts, resolution parsing, and CLI defaults

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_build_and_deploy_theme.py`
- Create: `build_and_deploy_theme.py`

**Interfaces:**
- Produces: `Resolution(width: int, height: int)`, `HardwareOverrides`, `HardwareInfo`, `BootEntry`, `BootTarget`, `DeploymentPlan`, `ThemeBuild`, `ThemeError`, `parse_resolution(value: str) -> Resolution`, `create_parser(script_dir: Path) -> argparse.ArgumentParser`.
- Consumes: no production interfaces.

- [ ] **Step 1: Write the first failing contract tests**

Create an empty `tests/__init__.py` and start `tests/test_build_and_deploy_theme.py` with a loader that turns a missing production module into an assertion failure, then add literal expectations:

```python
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBJECT_PATH = ROOT / "build_and_deploy_theme.py"


def load_subject():
    if not SUBJECT_PATH.is_file():
        raise AssertionError(f"missing production script: {SUBJECT_PATH}")
    spec = importlib.util.spec_from_file_location("build_and_deploy_theme", SUBJECT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CoreContractTests(unittest.TestCase):
    def test_parse_resolution_accepts_4k(self):
        subject = load_subject()
        self.assertEqual(subject.parse_resolution("3840x2160"), subject.Resolution(3840, 2160))

    def test_parse_resolution_rejects_non_16_by_9(self):
        subject = load_subject()
        with self.assertRaisesRegex(ValueError, "16:9"):
            subject.parse_resolution("1920x1200")

    def test_parser_defaults_to_4k_and_platform_mode(self):
        subject = load_subject()
        args = subject.create_parser(ROOT).parse_args([])
        self.assertEqual(args.resolution, subject.Resolution(3840, 2160))
        self.assertEqual(args.source_dir, ROOT)
        self.assertEqual(args.output_dir, ROOT / "dist" / "ghoul-cyber")
        self.assertFalse(args.build_only)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.CoreContractTests -v
```

Expected: three failures whose first cause is `missing production script`. A syntax/import error in the test does not satisfy RED and must be corrected before continuing.

- [ ] **Step 3: Implement the minimal contracts and parser**

Create `build_and_deploy_theme.py` with a shebang, module docstring, standard-library imports, immutable data contracts, and parser:

```python
#!/usr/bin/env python3
"""Build and optionally deploy the ghoul-cyber rEFInd theme."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Sequence


class ThemeError(RuntimeError):
    """User-facing build or deployment failure."""


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int


@dataclass(frozen=True)
class HardwareOverrides:
    cpu: str | None = None
    ram: str | None = None
    gpu: str | None = None
    nvme: str | None = None
    uefi_version: str = "2.9"
    secure_boot: str = "auto"


@dataclass(frozen=True)
class HardwareInfo:
    cpu: str = "UNKNOWN"
    ram: str = "UNKNOWN"
    gpu: str = "UNKNOWN"
    nvme: str = "UNKNOWN"
    uefi_version: str = "2.9"
    secure_boot: str = "OFF"


@dataclass(frozen=True)
class BootEntry:
    bootnum: str
    label: str
    partuuid: str
    loader_path: str
    device: str = ""
    fs_label: str = ""
    part_label: str = ""
    size: str = ""
    mount_points: tuple[str, ...] = ()


@dataclass(frozen=True)
class BootTarget:
    role: str
    source_icon: Path
    device: str
    partuuid: str
    loader_path: str
    mount_point: Path | None = None


@dataclass(frozen=True)
class DeploymentPlan:
    theme_source: Path
    refind_dir: Path
    targets: tuple[BootTarget, ...]
    invoking_uid: int | None = None
    invoking_gid: int | None = None


@dataclass(frozen=True)
class ThemeBuild:
    output_dir: Path
    resolution: Resolution
    files: tuple[Path, ...]


def parse_resolution(value: str) -> Resolution:
    match = re.fullmatch(r"([1-9]\d{2,4})[xX]([1-9]\d{2,4})", value.strip())
    if not match:
        raise ValueError("resolution must use WIDTHxHEIGHT")
    width, height = (int(part) for part in match.groups())
    if width * 9 != height * 16:
        raise ValueError("resolution must have a 16:9 aspect ratio")
    return Resolution(width, height)


def create_parser(script_dir: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=parse_resolution, default=Resolution(3840, 2160))
    parser.add_argument("--source-dir", type=Path, default=script_dir)
    parser.add_argument("--output-dir", type=Path, default=script_dir / "dist" / "ghoul-cyber")
    parser.add_argument("--refind-dir", type=Path)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--cpu")
    parser.add_argument("--ram")
    parser.add_argument("--gpu")
    parser.add_argument("--nvme")
    parser.add_argument("--uefi-version", default="2.9")
    parser.add_argument("--secure-boot", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    return parser
```

Keep deployment-plan serialization out of this task; add it with the privileged workflow in Task 8.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.CoreContractTests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: 3 tests pass; both files compile without output.

- [ ] **Step 5: Review this task**

Run `rg -n "class |def |3840|build-only" build_and_deploy_theme.py tests/test_build_and_deploy_theme.py` and verify only the listed contracts and tests exist.

---

### Task 2: Asset discovery, alpha cleanup, autocrop, and resizing

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: `ThemeError`.
- Produces: `ASSET_STEMS: tuple[str, ...]`, `discover_assets(source_dir: Path) -> dict[str, Path]`, `open_rgba(path: Path, *, selection_frame: bool = False) -> Image.Image`, `meaningful_bbox(image: Image.Image) -> tuple[int, int, int, int]`, `crop_square(image: Image.Image) -> Image.Image`, `resize_asset(path: Path, size: int, *, selection_frame: bool = False) -> Image.Image`.

- [ ] **Step 1: Add failing synthetic-image tests**

Import `tempfile` and Pillow in the test module, then add:

```python
import tempfile
from PIL import Image, ImageDraw


class AssetPipelineTests(unittest.TestCase):
    def test_discovery_uses_exact_stems_and_rejects_conflicts(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for stem in subject.ASSET_STEMS:
                Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(root / f"{stem}.png")
            Image.new("RGBA", (20, 20)).save(root / "background_overlay.png")
            found = subject.discover_assets(root)
            self.assertEqual(found["background"].name, "background.png")
            Image.new("RGB", (20, 20), "white").save(root / "background.jpg")
            with self.assertRaisesRegex(subject.ThemeError, "background.*multiple"):
                subject.discover_assets(root)

    def test_transparent_noise_does_not_expand_crop(self):
        subject = load_subject()
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((20, 15, 79, 74), fill=(10, 10, 10, 255))
        image.putpixel((0, 0), (255, 255, 255, 255))
        cropped = subject.crop_square(image)
        self.assertEqual(cropped.size, (60, 60))

    def test_opaque_white_jpeg_border_becomes_transparent(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "card.jpg"
            image = Image.new("RGB", (100, 100), "white")
            ImageDraw.Draw(image).rectangle((20, 20, 79, 79), fill="black")
            image.save(path, quality=100, subsampling=0)
            output = subject.resize_asset(path, 128)
            self.assertEqual(output.mode, "RGBA")
            self.assertEqual(output.size, (128, 128))
            self.assertLess(output.getpixel((0, 0))[3], 32)

    def test_selection_frame_black_key_keeps_center_transparent(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "selection_box.jpg"
            image = Image.new("RGB", (100, 100), "black")
            ImageDraw.Draw(image).rectangle((10, 10, 89, 89), outline="red", width=8)
            image.save(path, quality=100, subsampling=0)
            output = subject.resize_asset(path, 144, selection_frame=True)
            self.assertLess(output.getpixel((72, 72))[3], 16)
            self.assertGreater(max(pixel[0] for pixel in output.getdata()), 160)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.AssetPipelineTests -v
```

Expected: failures identify missing `ASSET_STEMS` or `discover_assets`; they must not be Pillow fixture errors.

- [ ] **Step 3: Implement discovery and image normalization**

Add guarded Pillow imports near the production imports:

```python
try:
    from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
except ImportError as exc:
    Image = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None

ASSET_STEMS = (
    "background",
    "selection_box",
    "selection_item_windev",
    "selection_item_wingame",
    "selection_item_linux",
    "bios",
    "power",
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
```

Implement exact-stem discovery and the alpha pipeline. The occupancy threshold is what prevents one noisy edge pixel from expanding the crop:

```python
def discover_assets(source_dir: Path) -> dict[str, Path]:
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise ThemeError(f"source directory does not exist: {source_dir}")
    by_stem: dict[str, list[Path]] = {stem: [] for stem in ASSET_STEMS}
    for path in source_dir.iterdir():
        key = path.stem.casefold()
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES and key in by_stem:
            by_stem[key].append(path)
    for stem, matches in by_stem.items():
        if not matches:
            raise ThemeError(f"{stem}: missing PNG/JPG/JPEG asset in {source_dir}")
        if len(matches) > 1:
            names = ", ".join(sorted(path.name for path in matches))
            raise ThemeError(f"{stem}: multiple matching assets: {names}")
    return {stem: paths[0] for stem, paths in by_stem.items()}


def _clear_edge_white(image):
    rgba = image.copy()
    pixels = rgba.load()
    width, height = rgba.size
    stack = [(x, y) for x in range(width) for y in (0, height - 1)]
    stack += [(x, y) for y in range(height) for x in (0, width - 1)]
    seen: set[tuple[int, int]] = set()
    while stack:
        x, y = stack.pop()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        red, green, blue, alpha = pixels[x, y]
        if alpha == 0 or min(red, green, blue) < 235:
            continue
        pixels[x, y] = (red, green, blue, 0)
        if x:
            stack.append((x - 1, y))
        if x + 1 < width:
            stack.append((x + 1, y))
        if y:
            stack.append((x, y - 1))
        if y + 1 < height:
            stack.append((x, y + 1))
    return rgba


def open_rgba(path: Path, *, selection_frame: bool = False):
    with Image.open(path) as source:
        source_format = source.format
        rgba = ImageOps.exif_transpose(source).convert("RGBA")
    if source_format in {"JPEG", "JPG"}:
        rgba = _clear_edge_white(rgba)
    if selection_frame and rgba.getchannel("A").getextrema() == (255, 255):
        luminance = ImageOps.grayscale(rgba)
        alpha = luminance.point(lambda value: 0 if value <= 6 else min(255, (value - 6) * 10))
        rgba.putalpha(alpha)
    return rgba


def meaningful_bbox(image) -> tuple[int, int, int, int]:
    alpha = image.getchannel("A")
    width, height = image.size
    rows = [sum(alpha.getpixel((x, y)) > 8 for x in range(width)) for y in range(height)]
    cols = [sum(alpha.getpixel((x, y)) > 8 for y in range(height)) for x in range(width)]
    min_row_pixels = max(2, width // 200)
    min_col_pixels = max(2, height // 200)
    active_rows = [index for index, count in enumerate(rows) if count >= min_row_pixels]
    active_cols = [index for index, count in enumerate(cols) if count >= min_col_pixels]
    if not active_rows or not active_cols:
        raise ThemeError("asset has no visible content after alpha cleanup")
    return active_cols[0], active_rows[0], active_cols[-1] + 1, active_rows[-1] + 1


def crop_square(image):
    left, top, right, bottom = meaningful_bbox(image)
    content_width, content_height = right - left, bottom - top
    side = max(content_width, content_height)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    square_left = round(center_x - side / 2)
    square_top = round(center_y - side / 2)
    return image.crop((square_left, square_top, square_left + side, square_top + side))


def resize_asset(path: Path, size: int, *, selection_frame: bool = False):
    image = crop_square(open_rgba(path, selection_frame=selection_frame))
    return image.resize((size, size), Image.Resampling.LANCZOS)
```

If the JPEG corner-alpha assertion reveals a fully black square after cropping, preserve transparent padding by expanding the crop onto an RGBA square rather than clamping it; do not weaken the test.

- [ ] **Step 4: Verify GREEN and existing contracts**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.AssetPipelineTests -v
python -m unittest tests.test_build_and_deploy_theme.CoreContractTests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: 7 tests pass in total.

- [ ] **Step 5: Review this task**

Run `rg -n "ASSET_STEMS|discover_assets|open_rgba|meaningful_bbox|crop_square|resize_asset" build_and_deploy_theme.py tests/test_build_and_deploy_theme.py` and inspect only those hunks.

---

### Task 3: Fonts, procedural reboot icon, HUD, and navigation

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: `Resolution`, `HardwareInfo` and Pillow imports.
- Produces: `find_font(explicit: Path | None, size: int) -> ImageFont.FreeTypeFont`, `render_reboot_icon(size: int = 48) -> Image.Image`, `ellipsize(draw, text: str, font, max_width: int) -> str`, `render_background(source: Path, resolution: Resolution, hardware: HardwareInfo, font_path: Path | None = None) -> Image.Image`.

- [ ] **Step 1: Add failing visual-behavior tests**

Add a helper that locates an installed test font and tests observable pixels:

```python
class RenderingTests(unittest.TestCase):
    def test_reboot_icon_contains_alpha_white_and_cyber_red(self):
        subject = load_subject()
        icon = subject.render_reboot_icon()
        pixels = list(icon.getdata())
        self.assertEqual(icon.size, (48, 48))
        self.assertEqual(icon.mode, "RGBA")
        self.assertTrue(any(alpha == 0 for _, _, _, alpha in pixels))
        self.assertTrue(any(red > 220 and green > 220 and blue > 220 and alpha > 180
                            for red, green, blue, alpha in pixels))
        self.assertTrue(any(red > 150 and green < 80 and blue < 100 and alpha > 10
                            for red, green, blue, alpha in pixels))

    def test_background_is_exact_size_with_red_enter_and_white_cursor(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "background.png"
            Image.new("RGB", (320, 180), "black").save(path)
            hardware = subject.HardwareInfo(
                cpu="TEST CPU", ram="32 GB DDR5 6000 MT/s", gpu="TEST GPU",
                nvme="2 TB", uefi_version="2.9", secure_boot="OFF",
            )
            output = subject.render_background(path, subject.Resolution(1920, 1080), hardware)
            pixels = list(output.convert("RGB").getdata())
            self.assertEqual(output.size, (1920, 1080))
            self.assertEqual(output.getpixel((0, 0))[:3], (0, 0, 0))
            self.assertTrue(any(red > 220 and green < 40 and blue < 90 for red, green, blue in pixels))
            cursor_region = output.crop((70, 60 + 5 * 32, 130, 60 + 6 * 32)).convert("RGB")
            self.assertTrue(any(min(pixel) > 230 for pixel in cursor_region.getdata()))
```

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_build_and_deploy_theme.RenderingTests -v`.

Expected: failures name missing `render_reboot_icon` or `render_background`.

- [ ] **Step 3: Implement deterministic font selection and rendering**

Search explicit font first, then these exact platform candidates, then ask Pillow for DejaVu Sans Mono:

```python
FONT_CANDIDATES = (
    Path("/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path(r"C:\Windows\Fonts\CascadiaMono.ttf"),
    Path(r"C:\Windows\Fonts\consola.ttf"),
)


def find_font(explicit: Path | None, size: int):
    candidates = ((explicit,) if explicit else ()) + FONT_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    try:
        return ImageFont.truetype("DejaVuSansMono.ttf", size)
    except OSError as exc:
        raise ThemeError("no Unicode monospace TTF/OTF font found") from exc
```

Render reboot at 8x scale, blur a red glow layer, draw a white arc and triangular arrowhead, composite, then downsample with LANCZOS. Render the background with `ImageOps.fit`, six HUD rows, a drawn rectangle after the final prompt, and measured navigation segments:

```python
NAV_LEFT = "_SELECT OS    [ ↑ ][ ↓ ] NAVIGATE    [ "
NAV_ENTER = "ENTER"
NAV_RIGHT = " ] SELECT    [ E ] EDIT BOOT    [ TAB ] INFO"


def render_reboot_icon(size: int = 48):
    scale = 8
    canvas_size = size * scale
    glow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    white = Image.new("RGBA", glow.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    white_draw = ImageDraw.Draw(white)
    box = (88, 88, canvas_size - 88, canvas_size - 88)
    glow_draw.arc(box, 35, 325, fill=(255, 0, 60, 220), width=44)
    glow_draw.polygon(((302, 55), (365, 100), (287, 135)), fill=(255, 0, 60, 220))
    glow = glow.filter(ImageFilter.GaussianBlur(26))
    white_draw.arc(box, 35, 325, fill=(245, 245, 245, 255), width=24)
    white_draw.polygon(((302, 55), (365, 100), (287, 135)), fill=(245, 245, 245, 255))
    return Image.alpha_composite(glow, white).resize((size, size), Image.Resampling.LANCZOS)


def ellipsize(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    shortened = text
    while shortened and draw.textlength(shortened + suffix, font=font) > max_width:
        shortened = shortened[:-1]
    return shortened + suffix


def render_background(source: Path, resolution: Resolution, hardware: HardwareInfo,
                      font_path: Path | None = None):
    with Image.open(source) as image:
        base = ImageOps.fit(
            ImageOps.exif_transpose(image).convert("RGBA"),
            (resolution.width, resolution.height),
            Image.Resampling.LANCZOS,
        )
    canvas = Image.new("RGBA", base.size, (0, 0, 0, 255))
    canvas.alpha_composite(base)
    canvas.putpixel((0, 0), (0, 0, 0, 255))
    draw = ImageDraw.Draw(canvas)
    hud_font = find_font(font_path, 22)
    lines = (
        f"> UEFI {hardware.uefi_version} ] Secure Boot: {hardware.secure_boot}",
        f"> CPU: {hardware.cpu}",
        f"> RAM: {hardware.ram}",
        f"> GPU: {hardware.gpu}",
        f"> NVMe: {hardware.nvme} -- OK",
        ">",
    )
    for index, line in enumerate(lines):
        draw.text((70, 60 + index * 32), ellipsize(draw, line, hud_font, resolution.width // 2),
                  font=hud_font, fill="#CCCCCC")
    prompt_width = draw.textlength(">", font=hud_font)
    draw.rectangle((76 + prompt_width, 60 + 5 * 32 + 4,
                    76 + prompt_width + 13, 60 + 5 * 32 + 25), fill="white")
    nav_font = find_font(font_path, 20)
    while nav_font.size > 14:
        total = sum(draw.textlength(segment, font=nav_font)
                    for segment in (NAV_LEFT, NAV_ENTER, NAV_RIGHT))
        if total <= resolution.width - 140:
            break
        nav_font = find_font(font_path, nav_font.size - 1)
    x = (resolution.width - total) / 2
    y = resolution.height - 70
    for segment, color in ((NAV_LEFT, "#DCDCDC"), (NAV_ENTER, "#FF003C"),
                           (NAV_RIGHT, "#DCDCDC")):
        draw.text((x, y), segment, font=nav_font, fill=color)
        x += draw.textlength(segment, font=nav_font)
    return canvas
```

Adjust only fixed arc coordinates if the 48x48 visual check shows clipping; keep the pixel-contract tests unchanged.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.RenderingTests -v
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: all tests pass and no resource warnings are emitted.

- [ ] **Step 5: Review this task**

Confirm with `rg -n "FONT_CANDIDATES|render_reboot_icon|NAV_LEFT|render_background" build_and_deploy_theme.py` that `ENTER` is the only red text segment and the cursor is a rectangle, not a font glyph.

---

### Task 4: Cross-platform hardware telemetry and overrides

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: `HardwareInfo`, `HardwareOverrides`, `ThemeError`.
- Produces: `run_command(argv: Sequence[str], *, check: bool = False) -> subprocess.CompletedProcess[str]`, `parse_windows_cim(payload: str) -> HardwareInfo`, `parse_linux_telemetry(outputs: Mapping[str, str], files: Mapping[str, str]) -> HardwareInfo`, `apply_hardware_overrides(info: HardwareInfo, overrides: HardwareOverrides) -> HardwareInfo`, `detect_hardware(system: str, overrides: HardwareOverrides, runner=run_command) -> HardwareInfo`.

- [ ] **Step 1: Add failing pure-parser tests**

Use literal fixture data rather than the current machine:

```python
class HardwareTelemetryTests(unittest.TestCase):
    def test_windows_cim_payload_is_normalized(self):
        subject = load_subject()
        payload = json.dumps({
            "Cpu": "AMD Ryzen 9 9950X3D 16-Core Processor",
            "Memory": [{"Capacity": 34359738368, "SMBIOSMemoryType": 34, "Speed": 6000},
                       {"Capacity": 34359738368, "SMBIOSMemoryType": 34, "Speed": 6000}],
            "Gpu": [{"Name": "NVIDIA GeForce RTX 5090"}],
            "Disk": [{"Model": "NVMe TEST", "Size": 4000787030016, "InterfaceType": "SCSI"}],
            "SecureBoot": False,
        })
        info = subject.parse_windows_cim(payload)
        self.assertEqual(info.cpu, "AMD Ryzen 9 9950X3D 16-Core Processor")
        self.assertEqual(info.ram, "64 GB DDR5 6000 MT/s")
        self.assertEqual(info.gpu, "NVIDIA GeForce RTX 5090")
        self.assertEqual(info.nvme, "4 TB")
        self.assertEqual(info.secure_boot, "OFF")

    def test_linux_fixture_uses_proc_and_command_fallbacks(self):
        subject = load_subject()
        info = subject.parse_linux_telemetry(
            {
                "lscpu": "Model name: Intel(R) Core(TM) Ultra 9 285K\n",
                "lspci": "01:00.0 VGA compatible controller: NVIDIA Corporation Test GPU\n",
                "lsblk": '{"blockdevices":[{"name":"nvme0n1","type":"disk","size":2000398934016}]}',
                "dmidecode": "Type: DDR5\nConfigured Memory Speed: 6400 MT/s\n",
                "mokutil": "SecureBoot disabled\n",
            },
            {"/proc/meminfo": "MemTotal:       65792000 kB\n"},
        )
        self.assertEqual(info.cpu, "Intel(R) Core(TM) Ultra 9 285K")
        self.assertEqual(info.ram, "63 GB DDR5 6400 MT/s")
        self.assertEqual(info.nvme, "2 TB")
        self.assertEqual(info.secure_boot, "OFF")

    def test_explicit_overrides_win_over_detection(self):
        subject = load_subject()
        base = subject.HardwareInfo(cpu="detected", ram="detected", gpu="detected", nvme="detected")
        result = subject.apply_hardware_overrides(
            base,
            subject.HardwareOverrides(cpu="override cpu", secure_boot="on", uefi_version="2.10"),
        )
        self.assertEqual(result.cpu, "override cpu")
        self.assertEqual(result.ram, "detected")
        self.assertEqual(result.secure_boot, "ON")
        self.assertEqual(result.uefi_version, "2.10")
```

Add `import json` to the test module.

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_build_and_deploy_theme.HardwareTelemetryTests -v`.

Expected: missing parser functions; fixture JSON itself must parse.

- [ ] **Step 3: Implement parsers and the detector boundary**

Implement decimal storage formatting, SMBIOS type mapping (`34 -> DDR5`), list/singleton normalization for CIM, and command fallbacks. Keep all external calls behind `run_command`:

```python
def run_command(argv: Sequence[str], *, check: bool = False):
    return subprocess.run(
        list(argv), text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=check,
    )


def _storage_size(value: int) -> str:
    for unit, divisor in (("TB", 10**12), ("GB", 10**9)):
        if value >= divisor:
            rounded = round(value / divisor)
            return f"{rounded} {unit}"
    return f"{round(value / 10**6)} MB"


def apply_hardware_overrides(info: HardwareInfo, overrides: HardwareOverrides) -> HardwareInfo:
    secure_boot = info.secure_boot if overrides.secure_boot == "auto" else overrides.secure_boot.upper()
    return dataclasses.replace(
        info,
        cpu=overrides.cpu or info.cpu,
        ram=overrides.ram or info.ram,
        gpu=overrides.gpu or info.gpu,
        nvme=overrides.nvme or info.nvme,
        uefi_version=overrides.uefi_version,
        secure_boot=secure_boot,
    )
```

For Windows, execute one `powershell -NoProfile -NonInteractive -Command` script that returns compressed JSON for CPU, memory, GPUs, disks and Secure Boot. For Linux, capture each optional command independently and read `/proc/meminfo` plus `/sys/firmware/efi/efivars/SecureBoot-*` only when present. Every parser returns `UNKNOWN` for an unavailable field instead of raising.

The public detector must branch only on the explicit `system` argument so tests can exercise either platform:

```python
def detect_hardware(system: str, overrides: HardwareOverrides, runner=run_command) -> HardwareInfo:
    normalized = system.casefold()
    if normalized == "windows":
        result = runner(("powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_CIM_SCRIPT))
        detected = parse_windows_cim(result.stdout) if result.returncode == 0 else HardwareInfo()
    elif normalized == "linux":
        outputs = collect_linux_outputs(runner)
        files = collect_linux_files()
        detected = parse_linux_telemetry(outputs, files)
    else:
        detected = HardwareInfo(cpu=platform.processor() or "UNKNOWN")
    return apply_hardware_overrides(detected, overrides)
```

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.HardwareTelemetryTests -v
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: all tests pass without invoking PowerShell, `dmidecode` or `sudo` because parser tests use literals.

- [ ] **Step 5: Smoke-test current-host detection without exposing full command output**

Run:

```powershell
python -c "import build_and_deploy_theme as m; print(m.detect_hardware('Windows', m.HardwareOverrides()))"
```

Expected: one `HardwareInfo(...)` line. Inspect only that it contains no exception or credential material.

---

### Task 5: Complete staged build, exact configuration, manifest, and validation

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: `discover_assets`, `resize_asset`, `render_reboot_icon`, `render_background`, `HardwareInfo`, `Resolution`, `ThemeBuild`.
- Produces: `THEME_CONF: str`, `OWNED_RELATIVE_PATHS: tuple[PurePosixPath, ...]`, `sha256_file(path: Path) -> str`, `validate_theme(root: Path, resolution: Resolution) -> tuple[Path, ...]`, `publish_owned_theme(staging: Path, output: Path) -> tuple[Path, ...]`, `build_theme(source_dir: Path, output_dir: Path, resolution: Resolution, hardware: HardwareInfo, font_path: Path | None = None) -> ThemeBuild`.

- [ ] **Step 1: Add a failing end-to-end build test with synthetic assets**

Add this fixture helper and integration test:

```python
def write_synthetic_assets(root: Path):
    Image.new("RGB", (320, 180), "black").save(root / "background.png")
    frame = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rectangle((8, 8, 111, 111), outline=(255, 0, 60, 255), width=8)
    frame.save(root / "selection_box.png")
    for stem in ("selection_item_windev", "selection_item_wingame",
                 "selection_item_linux", "bios", "power"):
        card = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(card).rectangle((15, 15, 104, 104), fill=(5, 5, 5, 255),
                                       outline=(240, 240, 240, 255), width=4)
        card.save(root / f"{stem}.png")


class ThemeBuildTests(unittest.TestCase):
    def test_build_creates_exact_tree_sizes_aliases_and_config(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            output = root / "dist" / "ghoul-cyber"
            source.mkdir()
            write_synthetic_assets(source)
            build = subject.build_theme(
                source, output, subject.Resolution(1920, 1080),
                subject.HardwareInfo(cpu="CPU", ram="RAM", gpu="GPU", nvme="1 TB"),
            )
            self.assertEqual(build.output_dir, output)
            expected_sizes = {
                "background.png": (1920, 1080),
                "selection_big.png": (144, 144),
                "selection_small.png": (56, 56),
                "icons/os_win_dev.png": (128, 128),
                "icons/os_win_game.png": (128, 128),
                "icons/os_cachyos.png": (128, 128),
                "icons/tool_firmware.png": (48, 48),
                "icons/tool_shutdown.png": (48, 48),
                "icons/tool_reboot.png": (48, 48),
                "icons/func_firmware.png": (48, 48),
                "icons/func_shutdown.png": (48, 48),
                "icons/func_reset.png": (48, 48),
            }
            for relative, size in expected_sizes.items():
                with Image.open(output / relative) as image:
                    self.assertEqual(image.size, size, relative)
                    self.assertEqual(image.mode, "RGBA", relative)
                    image.verify()
            self.assertEqual((output / "theme.conf").read_text(encoding="utf-8"),
                             subject.THEME_CONF)
            state = json.loads((output / "install-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["format_version"], 1)
            self.assertEqual(state["resolution"], "1920x1080")
            self.assertEqual(state["assignments"], {})
```

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_build_and_deploy_theme.ThemeBuildTests -v`.

Expected: missing `build_theme` or `THEME_CONF`.

- [ ] **Step 3: Implement exact output mapping and staging**

Define the exact configuration and source/output map:

```python
THEME_CONF = """banner themes/ghoul-cyber/background.png
banner_scale fillscreen

selection_big themes/ghoul-cyber/selection_big.png
selection_small themes/ghoul-cyber/selection_small.png

big_icon_size 128
small_icon_size 48

icons_dir themes/ghoul-cyber/icons

hideui hints,arrows,badges,label
showtools firmware, reboot, shutdown
timeout 10
"""

ASSET_OUTPUTS = {
    "selection_item_windev": ("icons/os_win_dev.png", 128, False),
    "selection_item_wingame": ("icons/os_win_game.png", 128, False),
    "selection_item_linux": ("icons/os_cachyos.png", 128, False),
    "bios": ("icons/tool_firmware.png", 48, False),
    "power": ("icons/tool_shutdown.png", 48, False),
    "selection_box_big": ("selection_big.png", 144, True),
    "selection_box_small": ("selection_small.png", 56, True),
}
ALIAS_OUTPUTS = {
    "icons/func_firmware.png": "icons/tool_firmware.png",
    "icons/func_shutdown.png": "icons/tool_shutdown.png",
    "icons/func_reset.png": "icons/tool_reboot.png",
}
```

Use `tempfile.TemporaryDirectory(prefix="ghoul-cyber-build-")` outside the project root for staging. Save every PNG as RGBA, write UTF-8 LF config, compute hashes after reopening images with `verify()`, write sorted/indented `install-state.json`, then publish only paths listed in `OWNED_RELATIVE_PATHS`. Each file is copied to a same-directory `.tmp` and replaced with `os.replace`; unknown output files remain untouched.

`build_theme` must remove the external temporary directory in `finally`, even after validation failure.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.ThemeBuildTests -v
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: all tests pass; temporary build folders do not appear under the workspace root.

- [ ] **Step 5: Mutation review**

Temporarily reason through these mutations without editing production code: selection_small changed to 64, `func_reset` copied from shutdown, background mode changed to RGB, config loses its final newline. Confirm at least one literal assertion fails for each mutation; add a focused test only if one mutation is not caught.

---

### Task 6: UEFI parsing and deterministic role assignment

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: `BootEntry`, `BootTarget`, `ThemeError`.
- Produces: `parse_efibootmgr(text: str) -> list[BootEntry]`, `parse_lsblk(text: str) -> dict[str, Mapping[str, object]]`, `enrich_boot_entries(entries: Iterable[BootEntry], devices: Mapping[str, Mapping[str, object]]) -> list[BootEntry]`, `assign_boot_roles(entries: Sequence[BootEntry], *, choose_dev: Callable[[Sequence[BootEntry]], int] | None, non_interactive: bool, previous: Mapping[str, object] | None = None) -> dict[str, BootEntry]`, `icon_path_for_loader(loader_path: str) -> str`, `find_cachyos_kernel(boot_dir: Path) -> Path | None`.

- [ ] **Step 1: Add failing parser and assignment tests**

Use this controlled fixture:

```python
EFIBOOTMGR_FIXTURE = """BootCurrent: 0007
BootOrder: 0007,0001,0002
Boot0001* Windows DEV HD(1,GPT,11111111-1111-1111-1111-111111111111,0x800,0x32000)/\\File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
Boot0002* Windows Boot Manager HD(1,GPT,22222222-2222-2222-2222-222222222222,0x800,0x32000)/\\File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
Boot0007* CachyOS HD(1,GPT,77777777-7777-7777-7777-777777777777,0x800,0x32000)/\\File(\\EFI\\CachyOS\\grubx64.efi)
"""

LSBLK_FIXTURE = """{
  "blockdevices": [
    {"path":"/dev/nvme0n1","type":"disk","children":[
      {"path":"/dev/nvme0n1p1","partuuid":"11111111-1111-1111-1111-111111111111","label":"WIN_DEV","partlabel":"DEV_ESP","size":"260M","mountpoints":[]},
      {"path":"/dev/nvme0n1p2","partuuid":"77777777-7777-7777-7777-777777777777","label":"CACHY","partlabel":"CachyOS","size":"1G","mountpoints":["/boot"]}
    ]},
    {"path":"/dev/nvme1n1","type":"disk","children":[
      {"path":"/dev/nvme1n1p1","partuuid":"22222222-2222-2222-2222-222222222222","label":"WIN_GAME","partlabel":"GAMING_ESP","size":"260M","mountpoints":[]}
    ]}
  ]
}"""


class UefiAssignmentTests(unittest.TestCase):
    def test_parses_and_enriches_three_boot_entries(self):
        subject = load_subject()
        parsed = subject.parse_efibootmgr(EFIBOOTMGR_FIXTURE)
        enriched = subject.enrich_boot_entries(parsed, subject.parse_lsblk(LSBLK_FIXTURE))
        roles = subject.assign_boot_roles(enriched, choose_dev=None, non_interactive=True)
        self.assertEqual(roles["win_dev"].partuuid, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(roles["win_game"].partuuid, "22222222-2222-2222-2222-222222222222")
        self.assertEqual(roles["cachyos"].bootnum, "0007")

    def test_ambiguous_windows_requires_choice_or_fails_noninteractive(self):
        subject = load_subject()
        entries = [
            subject.BootEntry("0001", "Windows Boot Manager", "a", "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"),
            subject.BootEntry("0002", "Windows Boot Manager", "b", "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"),
            subject.BootEntry("0003", "CachyOS", "c", "\\EFI\\CachyOS\\grubx64.efi"),
        ]
        with self.assertRaisesRegex(subject.ThemeError, "ambiguous"):
            subject.assign_boot_roles(entries, choose_dev=None, non_interactive=True)
        roles = subject.assign_boot_roles(entries, choose_dev=lambda options: 1, non_interactive=False)
        self.assertEqual(roles["win_dev"].bootnum, "0002")
        self.assertEqual(roles["win_game"].bootnum, "0001")

    def test_loader_icon_uses_same_directory_and_png_stem(self):
        subject = load_subject()
        self.assertEqual(
            subject.icon_path_for_loader("\\EFI\\Microsoft\\Boot\\bootmgfw.efi"),
            "\\EFI\\Microsoft\\Boot\\bootmgfw.png",
        )
```

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_build_and_deploy_theme.UefiAssignmentTests -v`.

Expected: missing parser/assignment functions.

- [ ] **Step 3: Implement pure UEFI and lsblk parsers**

Parse one line at a time, normalize GUIDs to lowercase, preserve the original EFI path separator, and recursively flatten `children` in lsblk JSON:

```python
BOOT_LINE = re.compile(
    r"^Boot(?P<num>[0-9A-Fa-f]{4})\*?\s+(?P<label>.*?)\s+"
    r"HD\(\d+,GPT,(?P<guid>[0-9A-Fa-f-]+),[^)]*\).*?"
    r"\\File\((?P<path>[^)]+)\)"
)


def parse_efibootmgr(text: str) -> list[BootEntry]:
    entries = []
    for line in text.splitlines():
        match = BOOT_LINE.search(line)
        if match:
            entries.append(BootEntry(
                match.group("num").upper(),
                match.group("label").strip(),
                match.group("guid").lower(),
                match.group("path"),
            ))
    if not entries:
        raise ThemeError("efibootmgr did not expose any GPT file-loader entries")
    return entries


def icon_path_for_loader(loader_path: str) -> str:
    if not loader_path.casefold().endswith(".efi"):
        raise ThemeError(f"loader path is not an EFI file: {loader_path}")
    return loader_path[:-4] + ".png"
```

`assign_boot_roles` combines `label`, `fs_label`, `part_label` and `loader_path` case-insensitively. It excludes paths containing `refind` from CachyOS candidates, requires exactly two Windows candidates, reuses previous mappings only when both PARTUUID and path match, and calls `choose_dev` only when keyword scoring cannot distinguish DEV from GAME/GAMING.

`find_cachyos_kernel` returns the lexicographically last regular file matching `vmlinuz*cachy*`, or `None`. It never follows a symlink outside the resolved `/boot` directory.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.UefiAssignmentTests -v
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: all tests pass.

- [ ] **Step 5: Review assignment safety**

Inspect `assign_boot_roles` and confirm it cannot silently map an ambiguous pair by list order. Confirm no call to `efibootmgr -c`, `efibootmgr -b` or any NVRAM-writing command exists.

---

### Task 7: rEFInd discovery, managed configuration, backups, and transaction rollback

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: `ThemeError`, `OWNED_RELATIVE_PATHS`, `DeploymentPlan`.
- Produces: `find_refind_dir(explicit: Path | None, candidates: Iterable[Path]) -> Path`, `update_managed_config(raw: bytes) -> bytes`, `FileTransaction` with `copy_file(source: Path, target: Path, permanent_backup: Path | None = None)`, `write_bytes(target: Path, payload: bytes, permanent_backup: Path | None = None)`, `commit()` and `rollback()`, `copy_owned_theme(source: Path, refind_dir: Path, transaction: FileTransaction) -> Path`.

- [ ] **Step 1: Add failing config and rollback tests**

```python
class DeploymentPrimitiveTests(unittest.TestCase):
    def test_refind_candidate_requires_config_and_binary(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            invalid = root / "invalid"
            valid = root / "EFI" / "refind"
            invalid.mkdir()
            valid.mkdir(parents=True)
            (valid / "refind.conf").write_text("timeout 5\r\n", encoding="utf-8")
            (valid / "refind_x64.efi").write_bytes(b"MZ")
            self.assertEqual(subject.find_refind_dir(None, (invalid, valid)), valid.resolve())

    def test_managed_block_is_last_idempotent_and_preserves_crlf_bom(self):
        subject = load_subject()
        original = b"\xef\xbb\xbftimeout 5\r\n"
        once = subject.update_managed_config(original)
        twice = subject.update_managed_config(once)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(once.endswith(
            b"# BEGIN ghoul-cyber managed theme\r\n"
            b"include themes/ghoul-cyber/theme.conf\r\n"
            b"# END ghoul-cyber managed theme\r\n"
        ))

    def test_transaction_restores_replaced_file_and_removes_created_file(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            source.write_bytes(b"new")
            replaced = root / "replaced"
            replaced.write_bytes(b"old")
            created = root / "created"
            transaction = subject.FileTransaction()
            transaction.copy_file(source, replaced)
            transaction.copy_file(source, created)
            transaction.rollback()
            self.assertEqual(replaced.read_bytes(), b"old")
            self.assertFalse(created.exists())
```

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_build_and_deploy_theme.DeploymentPrimitiveTests -v`.

Expected: missing discovery/config/transaction symbols.

- [ ] **Step 3: Implement path validation and byte-preserving managed block**

Use these exact markers:

```python
MANAGED_BEGIN = "# BEGIN ghoul-cyber managed theme"
MANAGED_INCLUDE = "include themes/ghoul-cyber/theme.conf"
MANAGED_END = "# END ghoul-cyber managed theme"


def update_managed_config(raw: bytes) -> bytes:
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):].decode("utf-8")
    newline = "\r\n" if "\r\n" in body else "\n"
    pattern = re.compile(
        rf"(?ms)^[ \t]*{re.escape(MANAGED_BEGIN)}\r?\n.*?"
        rf"^[ \t]*{re.escape(MANAGED_END)}[ \t]*(?:\r?\n)?"
    )
    body = pattern.sub("", body).rstrip("\r\n")
    block = newline.join((MANAGED_BEGIN, MANAGED_INCLUDE, MANAGED_END))
    updated = (body + newline * 2 + block + newline) if body else (block + newline)
    return bom + updated.encode("utf-8")
```

`find_refind_dir` resolves candidates and accepts only a directory containing both `refind.conf` and at least one regular `refind_*.efi`. Explicit invalid input raises immediately rather than falling through to another path.

Implement `FileTransaction` with a private temporary backup directory from `tempfile.TemporaryDirectory(prefix="ghoul-cyber-rollback-")`. Before replacing an existing file, copy its bytes and mode to that directory. Record newly created targets separately. `rollback` restores replacements in reverse order and removes only recorded created files; `commit` deletes temporary rollback data. A requested permanent backup is copied once and never overwritten.

`copy_owned_theme` validates that each resolved source stays under the build root and each destination stays under `refind_dir/themes/ghoul-cyber` before passing it to the transaction.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.DeploymentPrimitiveTests -v
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: all tests pass and no rollback directory remains after the test process.

- [ ] **Step 5: Review destructive-operation boundaries**

Search:

```powershell
rg -n "unlink|rmtree|remove|replace|copy_file|rollback" build_and_deploy_theme.py
```

Verify every deletion targets only a path recorded as created by the current transaction or an internal same-directory temporary file. There must be no recursive deletion of the workspace, ESP, theme root, `/boot`, `/efi` or a computed parent.

---

### Task 8: Linux dependency bootstrap, loader icon deployment, sudo handoff, and CLI orchestration

**Files:**
- Modify: `tests/test_build_and_deploy_theme.py`
- Modify: `build_and_deploy_theme.py`

**Interfaces:**
- Consumes: every interface from Tasks 1–7.
- Produces: `missing_linux_dependencies(which: Callable[[str], str | None]) -> tuple[str, ...]`, `bootstrap_linux_dependencies(missing: Sequence[str], runner=run_command) -> None`, `deployment_plan_to_json(plan: DeploymentPlan) -> str`, `deployment_plan_from_json(payload: str) -> DeploymentPlan`, `ensure_volume_mounted(target: BootTarget, runner=run_command) -> tuple[Path, bool]`, `apply_deployment(plan: DeploymentPlan, *, runner=run_command) -> None`, `run_linux_deploy(build: ThemeBuild, args, runner=run_command) -> None`, `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Add failing dependency, fake-ESP, idempotence, and CLI tests**

```python
class LinuxWorkflowTests(unittest.TestCase):
    def test_missing_dependencies_map_to_cachyos_packages(self):
        subject = load_subject()
        present = {"lsblk": "/usr/bin/lsblk", "findmnt": "/usr/bin/findmnt"}
        missing = subject.missing_linux_dependencies(present.get)
        self.assertEqual(missing, ("efibootmgr",))
        self.assertEqual(subject.PACMAN_PACKAGES["efibootmgr"], "efibootmgr")

    def test_apply_deployment_copies_theme_icons_and_activates_last(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "dist" / "ghoul-cyber"
            refind = root / "esp" / "EFI" / "refind"
            win_dev = root / "dev-esp"
            win_game = root / "game-esp"
            cachy = root / "cachy-esp"
            for directory in (source / "icons", refind, win_dev, win_game, cachy):
                directory.mkdir(parents=True, exist_ok=True)
            (refind / "refind.conf").write_text("timeout 5\n", encoding="utf-8")
            (refind / "refind_x64.efi").write_bytes(b"MZ")
            (source / "theme.conf").write_text(subject.THEME_CONF, encoding="utf-8")
            for relative in subject.OWNED_RELATIVE_PATHS:
                path = source / Path(*relative.parts)
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"owned")
            targets = (
                subject.BootTarget("win_dev", source / "icons/os_win_dev.png", "/dev/a", "a",
                                   "\\EFI\\Microsoft\\Boot\\bootmgfw.efi", win_dev),
                subject.BootTarget("win_game", source / "icons/os_win_game.png", "/dev/b", "b",
                                   "\\EFI\\Microsoft\\Boot\\bootmgfw.efi", win_game),
                subject.BootTarget("cachyos", source / "icons/os_cachyos.png", "/dev/c", "c",
                                   "\\EFI\\CachyOS\\grubx64.efi", cachy),
            )
            for mount, loader in ((win_dev, targets[0].loader_path),
                                  (win_game, targets[1].loader_path),
                                  (cachy, targets[2].loader_path)):
                loader_file = mount / Path(*PureWindowsPath(loader).parts[1:])
                loader_file.parent.mkdir(parents=True, exist_ok=True)
                loader_file.write_bytes(b"MZ")
            plan = subject.DeploymentPlan(source, refind, targets)
            subject.apply_deployment(plan)
            subject.apply_deployment(plan)
            self.assertEqual(
                (win_dev / "EFI/Microsoft/Boot/bootmgfw.png").read_bytes(),
                (source / "icons/os_win_dev.png").read_bytes(),
            )
            config = (refind / "refind.conf").read_text(encoding="utf-8")
            self.assertEqual(config.count(subject.MANAGED_BEGIN), 1)
            self.assertTrue(config.rstrip().endswith(subject.MANAGED_END))

    def test_main_defaults_to_build_only_on_windows(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_synthetic_assets(root)
            exit_code = subject.main([
                "--source-dir", str(root),
                "--output-dir", str(root / "out"),
                "--resolution", "1920x1080",
                "--cpu", "CPU", "--ram", "RAM", "--gpu", "GPU", "--nvme", "1 TB",
                "--secure-boot", "off",
                "--build-only",
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "out" / "background.png").is_file())
```

Add `from pathlib import PureWindowsPath` to the test imports. In the fake-ESP test, `OWNED_RELATIVE_PATHS` includes config/JSON and PNG outputs only; create valid PNGs with Pillow rather than `b"owned"` for any path validated as an image.

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_build_and_deploy_theme.LinuxWorkflowTests -v`.

Expected: missing Linux workflow symbols. The test must not invoke real `sudo`, mounts, package managers or ESPs.

- [ ] **Step 3: Implement dependency bootstrap and serializable privileged plan**

Define mandatory commands and CachyOS package mapping:

```python
PACMAN_PACKAGES = {
    "Pillow": "python-pillow",
    "efibootmgr": "efibootmgr",
    "lsblk": "util-linux",
    "findmnt": "util-linux",
    "font": "ttf-dejavu",
}


def missing_linux_dependencies(which: Callable[[str], str | None]) -> tuple[str, ...]:
    return tuple(name for name in ("efibootmgr", "lsblk", "findmnt") if which(name) is None)
```

`bootstrap_linux_dependencies` checks `/etc/os-release` for CachyOS/Arch, deduplicates package names, runs exactly `sudo pacman -S --needed --noconfirm ...`, and raises `ThemeError` with the command and exit code on failure. If Pillow was missing at process startup, restart once with `os.execv(sys.executable, [sys.executable, *sys.argv])` after installation. Never run package installation from module import or during tests.

Serialize plans as JSON with resolved absolute paths, but validate on read:

- `theme_source` must pass `validate_theme`;
- `refind_dir` must pass `find_refind_dir` as an explicit candidate;
- roles must be exactly `win_dev`, `win_game` and `cachyos`;
- loader paths must be absolute EFI-style paths, end in `.efi`, and contain neither `..` nor NUL;
- source icons must resolve inside `theme_source/icons`;
- each device must equal the enriched `lsblk` device associated with its PARTUUID.

- [ ] **Step 4: Implement mounting and transactional deployment**

`ensure_volume_mounted` returns an existing mount point with `mounted_by_us=False`. Otherwise it validates an absolute `/dev/...` path, creates a private directory under `/run/ghoul-cyber/<bootnum-or-guid>`, runs `mount -- <device> <directory>` through the injected runner, and returns `mounted_by_us=True`.

`apply_deployment` performs this exact order inside one `FileTransaction`:

1. Revalidate source theme and rEFInd directory.
2. Resolve or mount all three loader volumes.
3. Verify each loader regular file exists below its mount root.
4. Copy owned theme files to `refind_dir/themes/ghoul-cyber`.
5. Copy each role icon to `icon_path_for_loader`, making a permanent `.ghoul-cyber.bak` only when a pre-existing icon has no backup.
6. Update deployed `install-state.json` with role, PARTUUID, loader path and SHA-256.
7. Write the timestamped permanent backup of `refind.conf`.
8. Write `update_managed_config(raw)` as the final mutation.
9. Commit the transaction.
10. In `finally`, unmount only mount points returned with `mounted_by_us=True` and remove only those now-empty private mount directories.

Any exception before commit calls `rollback()` and is re-raised as `ThemeError` with the current stage.

- [ ] **Step 5: Implement CLI orchestration and sudo handoff**

`main` performs:

```python
def main(argv: Sequence[str] | None = None) -> int:
    script_dir = Path(__file__).resolve().parent
    parser = create_parser(script_dir)
    args = parser.parse_args(argv)
    try:
        ensure_pillow_or_bootstrap(args)
        overrides = HardwareOverrides(
            cpu=args.cpu, ram=args.ram, gpu=args.gpu, nvme=args.nvme,
            uefi_version=args.uefi_version, secure_boot=args.secure_boot,
        )
        hardware = detect_hardware(platform.system(), overrides)
        build = build_theme(
            args.source_dir, args.output_dir, args.resolution, hardware, args.font,
        )
        should_deploy = platform.system().casefold() == "linux" and not args.build_only
        if should_deploy:
            run_linux_deploy(build, args)
        print(f"ghoul-cyber ready: {build.output_dir}")
        return 0
    except (ThemeError, ValueError) as exc:
        print(f"ghoul-cyber: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

`run_linux_deploy` installs missing mandatory tools, runs `efibootmgr -v` and `lsblk -J -b -o PATH,TYPE,PARTUUID,LABEL,PARTLABEL,SIZE,MOUNTPOINTS`, resolves roles, prompts only for the DEV choice when needed, builds a plan in a system temporary file, and invokes:

```text
sudo -- <current-python> <absolute-script> --_apply-plan <absolute-plan-file>
```

The internal parser mode accepts only `--_apply-plan`, performs all validation again as root, deletes no caller-owned files, and returns the helper exit code. `--dry-run` prints sanitized role/PARTUUID/path mappings and does not create the plan file or call sudo.

- [ ] **Step 6: Verify GREEN for workflow and the full suite**

Run:

```powershell
python -m unittest tests.test_build_and_deploy_theme.LinuxWorkflowTests -v
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
python build_and_deploy_theme.py --help
```

Expected: all tests pass; help reports 3840x2160 semantics and public flags; no sudo prompt occurs on Windows.

- [ ] **Step 7: Review this task**

Run:

```powershell
rg -n "sudo|pacman|mount|umount|_apply-plan|efibootmgr" build_and_deploy_theme.py
rg -n "efibootmgr\s+-(c|b)|rm\s+-rf|rmtree|reset --hard|clean -fd" build_and_deploy_theme.py
```

Expected: the second search returns no matches. Confirm every external command is an argument list, never a shell-built string.

---

### Task 9: Real-asset 4K build, visual QA, and final requirement audit

**Files:**
- Modify only if verification reveals a tested defect: `build_and_deploy_theme.py` and `tests/test_build_and_deploy_theme.py`
- Generate: `dist/ghoul-cyber/**`

**Interfaces:**
- Consumes: completed public CLI.
- Produces: validated 4K distribution and verification evidence.

- [ ] **Step 1: Run the full automated verification fresh**

```powershell
python -m unittest discover -s tests -v
python -m py_compile build_and_deploy_theme.py tests/test_build_and_deploy_theme.py
```

Expected: zero failures/errors and exit code 0 for both commands.

- [ ] **Step 2: Build the actual workspace assets in default 4K**

```powershell
python build_and_deploy_theme.py --build-only
```

Expected: exit code 0 and `ghoul-cyber ready` naming the absolute output directory.

- [ ] **Step 3: Validate generated files independently**

Run a read-only Pillow/JSON audit:

```powershell
python -c "from pathlib import Path; from PIL import Image; import json; root=Path('dist/ghoul-cyber'); expected={'background.png':(3840,2160),'selection_big.png':(144,144),'selection_small.png':(56,56),'icons/os_win_dev.png':(128,128),'icons/os_win_game.png':(128,128),'icons/os_cachyos.png':(128,128),'icons/tool_firmware.png':(48,48),'icons/tool_shutdown.png':(48,48),'icons/tool_reboot.png':(48,48),'icons/func_firmware.png':(48,48),'icons/func_shutdown.png':(48,48),'icons/func_reset.png':(48,48)}; [(lambda im,p,s:(im.verify(), print(p, s, im.mode)))(Image.open(root/p),p,s) for p,s in expected.items() if Image.open(root/p).size==s]; state=json.loads((root/'install-state.json').read_text(encoding='utf-8')); assert state['resolution']=='3840x2160'; assert (root/'theme.conf').read_text(encoding='utf-8').endswith('timeout 10\n')"
```

Expected: one line per expected image, no assertion failure, all modes RGBA.

- [ ] **Step 4: Perform visual inspection**

Open `dist/ghoul-cyber/background.png`, `selection_big.png`, `selection_small.png`, all three OS icons, all three tool icons, and verify:

- HUD is at the upper-left with no collision or clipped hardware strings.
- The navigation is centered at y = 2090 and only ENTER is red.
- Tokyo Ghoul artwork remains visible after 16:9 fit.
- OS cards remain legible at 128x128 without white exterior borders.
- Selection centers and exteriors are transparent; glow is not clipped.
- Reboot is recognizably a circular arrow with white core and subtle red glow.

If a defect appears, write one failing regression test that detects that defect, run it to observe RED, patch only the responsible function, and rerun Steps 1–4.

- [ ] **Step 5: Check workspace hygiene and text integrity**

```powershell
rg -n "TBD|TODO|FIXME|<<<<<<<|=======|>>>>>>>|[ \t]+$" build_and_deploy_theme.py tests docs/superpowers
rg --files | Sort-Object
```

Expected: no markers or trailing whitespace; no `temp.*`, `*.bak`, `test2.*` or debug artifacts in the project root. Backups are runtime behavior only and must not appear in the Windows build.

- [ ] **Step 6: Audit every specification section**

Check the spec headings in order and map them to evidence:

- environment/dependencies and CLI: `--help` plus Task 8 tests;
- asset discovery/autocrop: Task 2 tests;
- procedural reboot and HUD/navigation: Task 3 tests plus visual QA;
- telemetry: Task 4 fixtures and current-host smoke test;
- output/config/manifest: Task 5 integration test and independent audit;
- UEFI assignment: Task 6 fixtures;
- deploy/activation/rollback: Tasks 7–8 fake-ESP tests;
- real 4K build: Steps 2–4 of this task.

Record any unverified Linux-only behavior explicitly in the final report: the fake-ESP path is verified on Windows, but a real CachyOS ESP deploy can only be confirmed when the user runs the finished script on that machine.

- [ ] **Step 7: Final review without Git**

Because the directory is not a Git repository, list only actual changed source/document paths and generated output. Compute SHA-256 for `build_and_deploy_theme.py` and the 4K `background.png`, and report the exact test/build commands and results. Do not claim real ESP deployment was executed on Windows.
