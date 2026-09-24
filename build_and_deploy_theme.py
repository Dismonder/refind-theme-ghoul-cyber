#!/usr/bin/env python3
"""Ghoul Cyber rEFInd Theme Builder & Deployer.

Author: Dismonder
Copyright: (c) 2026 Dismonder. All rights reserved.
License: Ghoul Cyber Protective License (GCPL-1.0) - see LICENSE
Notice: Permitted for personal, non-commercial use. Redistribution under
another name/initials or claiming authorship is strictly prohibited.

Build and, on Linux, deploy the ghoul-cyber rEFInd theme.

Run without arguments on CachyOS to build the 4K theme, discover rEFInd,
assign the DEV/GAMING/CachyOS cards, deploy the assets, and activate the
theme. On Windows, an argument-free run only builds dist/ghoul-cyber.
"""

from __future__ import annotations

__author__ = "Dismonder"
__copyright__ = "Copyright (c) 2026 Dismonder"
__license__ = "GCPL-1.0"
__version__ = "1.0.0"


import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterable, Mapping, Sequence

try:
    from PIL import (
        Image,
        ImageChops,
        ImageDraw,
        ImageEnhance,
        ImageFilter,
        ImageFont,
        ImageOps,
    )
except ImportError as exc:  # pragma: no cover - exercised on the target host
    Image = None
    ImageChops = None
    ImageDraw = None
    ImageEnhance = None
    ImageFilter = None
    ImageFont = None
    ImageOps = None
    PIL_IMPORT_ERROR: ImportError | None = exc
else:
    PIL_IMPORT_ERROR = None


THEME_NAME = "ghoul-cyber"
ASSET_STEMS = (
    "background",
    "selection_box",
    "selection_item_windev",
    "selection_item_wingame",
    "selection_item_linux",
    "bios",
    "power",
)
OPTIONAL_ASSET_STEMS = (
    "background_overlay",
    "background_effect",
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
# Icon geometry. Sized for a 3840x2160 OLED panel: rEFInd draws icons at
# exactly these pixel sizes, so the stock 128 px cards were fingernail-sized
# on 4K. Every source asset is >=1024 px, so nothing is upscaled.
# Dial these down (128 / 48 / 32) to return to the stock rEFInd geometry.
BIG_ICON_SIZE = 768
SMALL_ICON_SIZE = 240
BADGE_ICON_SIZE = BIG_ICON_SIZE // 4  # rEFInd draws drive badges at big/4
SELECTION_BIG_SIZE = round(BIG_ICON_SIZE * 1.125)
SELECTION_SMALL_SIZE = round(SMALL_ICON_SIZE * 1.125)

OS_ICON_NAMES = (
    "os_win", "os_win_dev", "os_win_game", "os_cachyos", "os_linux",
    "os_arch", "os_ubuntu", "os_debian", "os_fedora", "os_mac", "os_unknown",
)
TOOL_ICON_NAMES = (
    "tool_firmware", "tool_shutdown", "tool_reboot", "tool_shell",
    "tool_memtest", "tool_mok_tool", "tool_netboot", "tool_part",
    "tool_rescue", "tool_fwupdate", "func_firmware", "func_shutdown",
    "func_reset", "func_about", "func_exit", "func_hidden", "func_bootorder",
    "func_csr_rotate", "arrow_left", "arrow_right", "mouse",
)
BADGE_ICON_NAMES = (
    "vol_internal", "vol_external", "vol_optical", "vol_net", "vol_efi",
)

THEME_CONF = f"""banner themes/ghoul-cyber/background.png
banner_scale fillscreen

selection_big themes/ghoul-cyber/selection_big.png
selection_small themes/ghoul-cyber/selection_small.png

big_icon_size {BIG_ICON_SIZE}
small_icon_size {SMALL_ICON_SIZE}

icons_dir themes/ghoul-cyber/icons

hideui hints,arrows,badges,label
dont_scan_dirs EFI/ubuntu,EFI/refind,EFI/BOOT
dont_scan_files refind_x64.efi,BOOTX64.EFI,bootx64.efi
dont_scan_firmware "Shell", "EFI Internal Shell"
showtools firmware, reboot, shutdown, shell, memtest, gdisk, gptsync, netboot, mok_tool, fwupdate, apple_recovery, windows_recovery, csr_rotate, install

resolution 3840 2160
timeout 10

menuentry "Windows 11 Gaming" {{
    icon /EFI/refind/themes/ghoul-cyber/icons/os_win_game.png
    volume "af082e06-e080-47ed-b3e8-450398c9ec9e"
    loader \\EFI\\Microsoft\\Boot\\bootmgfw.efi
}}
"""
IMAGE_SIZES: dict[str, tuple[int, int]] = {
    "background.png": (0, 0),
    "selection_big.png": (SELECTION_BIG_SIZE, SELECTION_BIG_SIZE),
    "selection_small.png": (SELECTION_SMALL_SIZE, SELECTION_SMALL_SIZE),
    **{
        f"icons/{name}.png": (BIG_ICON_SIZE, BIG_ICON_SIZE)
        for name in OS_ICON_NAMES
    },
    **{
        f"icons/{name}.png": (SMALL_ICON_SIZE, SMALL_ICON_SIZE)
        for name in TOOL_ICON_NAMES
    },
    **{
        f"icons/{name}.png": (BADGE_ICON_SIZE, BADGE_ICON_SIZE)
        for name in BADGE_ICON_NAMES
    },
}
OWNED_RELATIVE_PATHS = tuple(
    PurePosixPath(path)
    for path in (*IMAGE_SIZES, "theme.conf", "install-state.json")
)
MANAGED_BEGIN = "# BEGIN ghoul-cyber managed theme"
MANAGED_INCLUDE = "include themes/ghoul-cyber/theme.conf"
MANAGED_END = "# END ghoul-cyber managed theme"
PACMAN_PACKAGES = {
    "Pillow": "python-pillow",
    "efibootmgr": "efibootmgr",
    "lsblk": "util-linux",
    "findmnt": "util-linux",
    "font": "ttf-dejavu",
}
FONT_CANDIDATES = (
    Path("/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf"),
    Path(r"C:\Windows\Fonts\CascadiaMono.ttf"),
    Path(r"C:\Windows\Fonts\CascadiaCode.ttf"),
    Path(r"C:\Windows\Fonts\consola.ttf"),
)
NAV_LEFT = "_SELECT OS    [ ↑ ][ ↓ ] NAVIGATE    [ "
NAV_ENTER = "ENTER"
NAV_RIGHT = " ] SELECT    [ E ] EDIT BOOT    [ TAB ] INFO"


class ThemeError(RuntimeError):
    """A user-facing build or deployment failure."""


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


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
    """Parse and validate a 16:9 WIDTHxHEIGHT resolution."""
    match = re.fullmatch(r"([1-9]\d{2,4})[xX]([1-9]\d{2,4})", value.strip())
    if not match:
        raise ValueError("resolution must use WIDTHxHEIGHT")
    width, height = (int(part) for part in match.groups())
    if width * 9 != height * 16:
        raise ValueError("resolution must have a 16:9 aspect ratio")
    return Resolution(width, height)


def create_parser(script_dir: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=Resolution(3840, 2160),
        help="target 16:9 resolution (default: 3840x2160)",
    )
    parser.add_argument("--source-dir", type=Path, default=script_dir)
    parser.add_argument(
        "--output-dir", type=Path, default=script_dir / "dist" / THEME_NAME
    )
    parser.add_argument("--refind-dir", type=Path)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--cpu")
    parser.add_argument("--ram")
    parser.add_argument("--gpu")
    parser.add_argument("--nvme")
    parser.add_argument("--uefi-version", default="2.9")
    parser.add_argument(
        "--secure-boot", choices=("auto", "on", "off"), default="auto"
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="build dist only; never modify an EFI System Partition",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and print the Linux deployment plan without applying it",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="fail instead of asking which Windows installation is DEV",
    )
    parser.add_argument("--_apply-plan", type=Path, help=argparse.SUPPRESS)
    return parser


def _require_pillow() -> None:
    if PIL_IMPORT_ERROR is not None:
        raise ThemeError(
            "Pillow is required. On CachyOS run: "
            "sudo pacman -S --needed python-pillow"
        ) from PIL_IMPORT_ERROR


def discover_assets(source_dir: Path) -> dict[str, Path]:
    """Resolve each required exact asset stem without arbitrary tie-breaking."""
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ThemeError(f"source directory does not exist: {source_dir}")
    all_stems = tuple(ASSET_STEMS) + tuple(OPTIONAL_ASSET_STEMS)
    by_stem: dict[str, list[Path]] = {stem: [] for stem in all_stems}
    for path in source_dir.iterdir():
        key = path.stem.casefold()
        if (
            path.is_file()
            and path.suffix.casefold() in IMAGE_SUFFIXES
            and key in by_stem
        ):
            by_stem[key].append(path)
    for stem, matches in by_stem.items():
        if not matches and stem in ASSET_STEMS:
            raise ThemeError(
                f"{stem}: missing PNG/JPG/JPEG asset in {source_dir}"
            )
        if len(matches) > 1:
            names = ", ".join(sorted(path.name for path in matches))
            raise ThemeError(f"{stem}: multiple matching assets: {names}")
    result = {stem: paths[0] for stem, paths in by_stem.items() if paths}
    return result


def _clear_edge_white(image):
    """Flood-clear bright pixels connected to an image edge."""
    rgba = image.copy()
    pixels = rgba.load()
    width, height = rgba.size
    stack = [(x, 0) for x in range(width)]
    stack.extend((x, height - 1) for x in range(width))
    stack.extend((0, y) for y in range(height))
    stack.extend((width - 1, y) for y in range(height))
    seen: set[tuple[int, int]] = set()
    while stack:
        x, y = stack.pop()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        red, green, blue, alpha = pixels[x, y]
        if alpha == 0 or min(red, green, blue) < 232:
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
    """Open an asset in corrected RGBA form and remove edge backgrounds."""
    _require_pillow()
    try:
        with Image.open(path) as source:
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
    except (OSError, ValueError) as exc:
        raise ThemeError(f"cannot open image {path}: {exc}") from exc

    if rgba.getchannel("A").getextrema() == (255, 255):
        rgba = _clear_edge_white(rgba)
    if selection_frame and rgba.getchannel("A").getextrema() == (255, 255):
        luminance = ImageOps.grayscale(rgba)
        alpha = luminance.point(
            lambda value: 0 if value <= 8 else min(255, (value - 8) * 9)
        )
        rgba.putalpha(alpha)
    return rgba


def meaningful_bbox(image) -> tuple[int, int, int, int]:
    """Find visible content while ignoring isolated edge-noise pixels."""
    alpha = image.getchannel("A")
    width, height = image.size
    alpha_bytes = alpha.load()
    rows = [
        sum(alpha_bytes[x, y] > 8 for x in range(width)) for y in range(height)
    ]
    cols = [
        sum(alpha_bytes[x, y] > 8 for y in range(height)) for x in range(width)
    ]
    min_row_pixels = max(2, width // 200)
    min_col_pixels = max(2, height // 200)
    active_rows = [
        index for index, count in enumerate(rows) if count >= min_row_pixels
    ]
    active_cols = [
        index for index, count in enumerate(cols) if count >= min_col_pixels
    ]
    if not active_rows or not active_cols:
        raise ThemeError("asset has no visible content after alpha cleanup")
    return (
        active_cols[0],
        active_rows[0],
        active_cols[-1] + 1,
        active_rows[-1] + 1,
    )


def crop_square(image):
    """Crop around meaningful content and expand the shorter axis to a square."""
    left, top, right, bottom = meaningful_bbox(image)
    content_width, content_height = right - left, bottom - top
    side = max(content_width, content_height)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    square_left = round(center_x - side / 2)
    square_top = round(center_y - side / 2)
    return image.crop(
        (square_left, square_top, square_left + side, square_top + side)
    )


def resize_asset(path: Path, size: int, *, selection_frame: bool = False):
    image = crop_square(open_rgba(path, selection_frame=selection_frame))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def find_font(explicit: Path | None, size: int):
    """Load a Unicode monospace TrueType/OpenType font."""
    _require_pillow()
    candidates = FONT_CANDIDATES
    if explicit is not None:
        candidates = (explicit.expanduser().resolve(),) + candidates
    for candidate in candidates:
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    try:
        return ImageFont.truetype("DejaVuSansMono.ttf", size)
    except OSError as exc:
        raise ThemeError(
            "no Unicode monospace TTF/OTF font found; install ttf-dejavu "
            "or pass --font"
        ) from exc


def is_monospace_font_available(explicit: Path | None = None) -> bool:
    """Return whether Pillow can load a suitable monospace font."""
    try:
        find_font(explicit, 12)
    except ThemeError:
        return False
    return True


def render_reboot_icon(size: int = SMALL_ICON_SIZE):
    """Draw a white circular restart arrow with a subtle blood-red glow."""
    _require_pillow()
    scale = _supersample(size)
    canvas_size = size * scale
    glow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    white = Image.new("RGBA", glow.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    white_draw = ImageDraw.Draw(white)
    unit = canvas_size / 384  # the shape was tuned on a 384 px canvas
    box = (88 * unit, 88 * unit, canvas_size - 88 * unit, canvas_size - 88 * unit)
    head = ((302 * unit, 55 * unit), (365 * unit, 100 * unit), (287 * unit, 135 * unit))
    glow_draw.arc(box, 35, 325, fill=(255, 0, 60, 220), width=max(1, round(44 * unit)))
    glow_draw.polygon(head, fill=(255, 0, 60, 220))
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, round(26 * unit))))
    white_draw.arc(
        box, 35, 325, fill=(245, 245, 245, 255), width=max(1, round(24 * unit))
    )
    white_draw.polygon(head, fill=(245, 245, 245, 255))
    return Image.alpha_composite(glow, white).resize(
        (size, size), Image.Resampling.LANCZOS
    )


def render_cyber_selection_frame(
    base_path: Path, size: int, *, is_big: bool = True
):
    """Generate high-contrast cyber selection frame with luminous neon brackets."""
    _require_pillow()
    im = crop_square(open_rgba(base_path, selection_frame=True))
    enh_col = ImageEnhance.Color(im).enhance(2.0)
    enh_bri = ImageEnhance.Brightness(enh_col).enhance(1.8)
    base_resized = enh_bri.resize((size, size), Image.Resampling.LANCZOS)

    scale = _supersample(size, cap=4)
    dim = size * scale
    sharp = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    glow = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))

    s_draw = ImageDraw.Draw(sharp)
    g_draw = ImageDraw.Draw(glow)

    margin = round(dim * 0.03)
    x0, y0 = margin, margin
    x1, y1 = dim - margin, dim - margin
    blen = round((x1 - x0) * 0.28)
    lw = max(2, round(dim * 0.03))
    gw = max(4, round(dim * 0.08))

    glow_col = (255, 0, 60, 240)
    core_col = (255, 240, 245, 255)
    accent_col = (255, 0, 60, 255)

    def brackets(d, w, col):
        d.line([(x0, y0), (x0 + blen, y0)], fill=col, width=w)
        d.line([(x0, y0), (x0, y0 + blen)], fill=col, width=w)
        d.line([(x1, y0), (x1 - blen, y0)], fill=col, width=w)
        d.line([(x1, y0), (x1, y0 + blen)], fill=col, width=w)
        d.line([(x0, y1), (x0 + blen, y1)], fill=col, width=w)
        d.line([(x0, y1), (x0, y1 - blen)], fill=col, width=w)
        d.line([(x1, y1), (x1 - blen, y1)], fill=col, width=w)
        d.line([(x1, y1), (x1, y1 - blen)], fill=col, width=w)
        d.rectangle([(x0, y0), (x1, y1)], outline=col, width=max(1, w // 3))

    brackets(g_draw, gw, glow_col)
    glow = glow.filter(ImageFilter.GaussianBlur(round(dim * 0.04)))
    brackets(s_draw, lw, accent_col)
    brackets(s_draw, max(1, lw // 2), core_col)

    bracket_img = Image.alpha_composite(glow, sharp).resize(
        (size, size), Image.Resampling.LANCZOS
    )
    return Image.alpha_composite(base_resized, bracket_img)


CJK_FONT_CANDIDATES = (
    Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
)
CARD_WHITE = (238, 238, 242, 255)
CARD_DIM = (150, 150, 158, 255)
CARD_RED = (255, 0, 60, 255)


def find_cjk_font(size: int):
    """Load a CJK-capable font, or None when the host has no CJK coverage."""
    _require_pillow()
    for candidate in CJK_FONT_CANDIDATES:
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return None


def _grain_layer(dim: int, seed: int, *, cells: int = 256, strength: int = 15):
    """Deterministic film grain used as the card's near-black base."""
    rng = random.Random(seed)
    small = max(8, cells)
    noise = bytes(rng.randrange(strength) for _ in range(small * small))
    layer = Image.frombytes("L", (small, small), noise)
    return layer.resize((dim, dim), Image.Resampling.BILINEAR)


def _scanline_layer(dim: int, *, period: int, alpha: int = 46):
    """Horizontal CRT scan lines drawn as a black overlay."""
    layer = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width = max(1, period // 3)
    for y in range(0, dim, period):
        draw.rectangle([(0, y), (dim, y + width - 1)], fill=(0, 0, 0, alpha))
    return layer


def _distress_mask(dim: int, seed: int):
    """Gritty erosion mask that keeps most of a glyph but chews its edges."""
    rng = random.Random(seed)
    small = 96
    data = bytes(
        255 if rng.random() > 0.07 else rng.randrange(165, 240)
        for _ in range(small * small)
    )
    mask = Image.frombytes("L", (small, small), data)
    mask = mask.resize((dim, dim), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(mask)
    for _ in range(5):
        y = rng.randrange(dim)
        height = rng.randrange(max(2, dim // 260), max(4, dim // 130))
        draw.rectangle(
            [(0, y), (dim, y + height)], fill=rng.randrange(175, 230)
        )
    return mask


def _tracked_text(draw, xy, text, font, fill, *, tracking=0, anchor="mm"):
    """Draw monospace text with extra letter spacing, centred on ``xy``."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x, y = xy
    if anchor.startswith("m"):
        x -= total / 2
    elif anchor.startswith("r"):
        x -= total
    for ch, width in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill, anchor="l" + anchor[1])
        x += width + tracking
    return total


def _bracket_frame(draw, dim: int, *, margin: int, line: int, arm: int):
    """Thin rectangle plus heavier corner brackets, the theme's signature."""
    x0 = y0 = margin
    x1 = y1 = dim - margin
    draw.rectangle([(x0, y0), (x1, y1)], outline=CARD_DIM, width=max(1, line // 2))
    for cx, sx in ((x0, 1), (x1, -1)):
        for cy, sy in ((y0, 1), (y1, -1)):
            draw.line([(cx, cy), (cx + sx * arm, cy)], fill=CARD_WHITE, width=line)
            draw.line([(cx, cy), (cx, cy + sy * arm)], fill=CARD_WHITE, width=line)


def _quad_point(quad, u: float, v: float):
    """Bilinear point inside a quad given as (tl, tr, br, bl)."""
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = quad
    top = (ax + (bx - ax) * u, ay + (by - ay) * u)
    bottom = (dx + (cx - dx) * u, dy + (cy - dy) * u)
    return (
        top[0] + (bottom[0] - top[0]) * v,
        top[1] + (bottom[1] - top[1]) * v,
    )


def _draw_card_glyph(layer, glyph: str, box: tuple[float, float, float, float]):
    """Draw the card's central symbol inside ``box`` (x0, y0, x1, y1)."""
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    span = x1 - x0

    def p(u: float, v: float):
        return (x0 + span * u, y0 + span * v)

    stroke = max(2, round(span * 0.045))

    if glyph == "win":
        quad = (p(0.04, 0.10), p(0.96, 0.00), p(0.96, 0.90), p(0.04, 1.00))
        for u0, u1 in ((0.0, 0.465), (0.535, 1.0)):
            for v0, v1 in ((0.0, 0.465), (0.535, 1.0)):
                draw.polygon(
                    [
                        _quad_point(quad, u0, v0),
                        _quad_point(quad, u1, v0),
                        _quad_point(quad, u1, v1),
                        _quad_point(quad, u0, v1),
                    ],
                    fill=CARD_WHITE,
                )
    elif glyph == "arch":
        draw.polygon(
            [
                p(0.50, 0.00), p(0.60, 0.24), p(0.53, 0.22), p(0.50, 0.30),
                p(1.00, 1.00), p(0.66, 1.00), p(0.50, 0.66), p(0.34, 1.00),
                p(0.00, 1.00), p(0.50, 0.30), p(0.47, 0.22), p(0.40, 0.24),
            ],
            fill=CARD_WHITE,
        )
    elif glyph == "penguin":
        # Union silhouette, then keep only its outline: no seams where the
        # head, flippers and feet overlap the body.
        width, height = layer.size
        silhouette = Image.new("L", (width, height), 0)
        sil = ImageDraw.Draw(silhouette)
        sil.ellipse([p(0.16, 0.28), p(0.84, 0.97)], fill=255)
        sil.ellipse([p(0.27, 0.00), p(0.73, 0.42)], fill=255)
        sil.polygon(
            [p(0.21, 0.42), p(0.02, 0.66), p(0.11, 0.80), p(0.28, 0.60)],
            fill=255,
        )
        sil.polygon(
            [p(0.79, 0.42), p(0.98, 0.66), p(0.89, 0.80), p(0.72, 0.60)],
            fill=255,
        )
        sil.ellipse([p(0.20, 0.88), p(0.47, 1.00)], fill=255)
        sil.ellipse([p(0.53, 0.88), p(0.80, 1.00)], fill=255)
        thickness = max(3, round(span * 0.052)) | 1
        outline = ImageChops.subtract(
            silhouette, silhouette.filter(ImageFilter.MinFilter(thickness))
        )
        layer.paste(CARD_WHITE, (0, 0), outline)
        draw.ellipse([p(0.33, 0.46), p(0.67, 0.90)], outline=CARD_WHITE,
                     width=max(2, round(span * 0.030)))
        draw.ellipse([p(0.375, 0.10), p(0.497, 0.27)], fill=CARD_WHITE)
        draw.ellipse([p(0.503, 0.10), p(0.625, 0.27)], fill=CARD_WHITE)
        for cx in (0.436, 0.564):
            draw.ellipse(
                [p(cx - 0.026, 0.155), p(cx + 0.026, 0.225)], fill=(0, 0, 0, 255)
            )
        draw.polygon(
            [p(0.50, 0.27), p(0.61, 0.325), p(0.50, 0.38), p(0.39, 0.325)],
            fill=CARD_RED,
        )
    elif glyph == "prompt":
        draw.line(
            [p(0.10, 0.22), p(0.44, 0.50), p(0.10, 0.78)],
            fill=CARD_WHITE, width=stroke, joint="curve",
        )
        draw.rectangle([p(0.56, 0.62), p(0.92, 0.78)], fill=CARD_WHITE)
    else:  # pragma: no cover - guarded by the caller
        raise ThemeError(f"unknown card glyph: {glyph}")


def _supersample(size: int, *, cap: int = 8, budget: int = 2048) -> int:
    """Pick a supersample factor that keeps the work canvas bounded."""
    return max(2, min(cap, budget // max(1, size)))


def render_cyber_card(
    size: int,
    *,
    glyph: str,
    title: str,
    label: str,
    index: str,
    katakana: str = "",
    footer: str = "+OS.BOOT",
):
    """Render a 1:1 stylistic match of the hand-made ghoul-cyber OS cards."""
    _require_pillow()
    scale = _supersample(size)
    dim = size * scale
    seed = sum(ord(ch) for ch in f"{glyph}{title}{label}{index}")

    grain = _grain_layer(dim, seed)
    card = Image.merge("RGB", (grain, grain, grain)).convert("RGBA")

    glyph_layer = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    box = (dim * 0.29, dim * 0.235, dim * 0.71, dim * 0.655)
    _draw_card_glyph(glyph_layer, glyph, box)
    alpha = ImageChops.multiply(
        glyph_layer.getchannel("A"), _distress_mask(dim, seed + 17)
    )
    glyph_layer.putalpha(alpha)
    card = Image.alpha_composite(card, glyph_layer)

    chrome = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    draw = ImageDraw.Draw(chrome)
    _bracket_frame(
        draw,
        dim,
        margin=round(dim * 0.055),
        line=max(2, round(dim * 0.008)),
        arm=round(dim * 0.115),
    )

    title_font = find_font(None, max(6, round(dim * 0.048)))
    label_font = find_font(None, max(7, round(dim * 0.070)))
    index_font = find_font(None, max(5, round(dim * 0.040)))
    tiny_font = find_font(None, max(4, round(dim * 0.026)))

    _tracked_text(
        draw, (dim * 0.5, dim * 0.145), title, title_font, CARD_WHITE,
        tracking=round(dim * 0.013),
    )
    _tracked_text(
        draw, (dim * 0.5, dim * 0.785), label, label_font, CARD_WHITE,
        tracking=round(dim * 0.020),
    )

    rule = max(1, round(dim * 0.005))
    y_rule = dim * 0.695
    draw.line(
        [(dim * 0.20, y_rule), (dim * 0.44, y_rule)], fill=CARD_WHITE, width=rule
    )
    draw.line(
        [(dim * 0.56, y_rule), (dim * 0.80, y_rule)], fill=CARD_WHITE, width=rule
    )
    tick = dim * 0.012
    draw.rectangle(
        [(dim * 0.47 - tick, y_rule - tick), (dim * 0.47 + tick, y_rule + tick)],
        outline=CARD_WHITE, width=max(1, rule // 2),
    )
    draw.ellipse(
        [(dim * 0.53 - tick, y_rule - tick), (dim * 0.53 + tick, y_rule + tick)],
        fill=CARD_RED,
    )

    _tracked_text(
        draw, (dim * 0.085, dim * 0.895), index, index_font, CARD_WHITE,
        tracking=round(dim * 0.006), anchor="lm",
    )
    draw.line(
        [(dim * 0.20, dim * 0.895), (dim * 0.33, dim * 0.895)],
        fill=CARD_DIM, width=max(1, rule // 2),
    )
    barcode_x = dim * 0.915
    for step in range(11):
        bar = max(1, round(dim * (0.004 if step % 3 else 0.008)))
        x = barcode_x - step * dim * 0.014
        draw.rectangle(
            [(x, dim * 0.868), (x + bar, dim * 0.905)], fill=CARD_DIM
        )
    _tracked_text(
        draw, (dim * 0.925, dim * 0.935), footer, tiny_font, CARD_DIM,
        tracking=round(dim * 0.003), anchor="rm",
    )

    if katakana:
        cjk_font = find_cjk_font(max(5, round(dim * 0.042)))
        if cjk_font is not None:
            for offset, char in enumerate(katakana):
                draw.text(
                    (dim * 0.865, dim * (0.30 + offset * 0.062)),
                    char, font=cjk_font, fill=CARD_DIM, anchor="mm",
                )

    card = Image.alpha_composite(card, chrome)
    card = Image.alpha_composite(card, _scanline_layer(dim, period=max(2, scale)))
    return card.resize((size, size), Image.Resampling.LANCZOS)


def render_cyber_icon(size: int, icon_type: str) -> Image.Image:
    """Render procedural cyber neon icons for all standard rEFInd functions."""
    _require_pillow()
    scale = _supersample(size)
    dim = size * scale
    glow = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    sharp = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    sharp_draw = ImageDraw.Draw(sharp)

    glow_color = (255, 0, 60, 150)
    core_color = (245, 245, 245, 255)
    accent_red = (255, 0, 60, 255)

    c = dim / 2
    r = dim * 0.38

    def draw_all(fn, width):
        fn(glow_draw, width + round(dim * 0.016), glow_color)
        fn(sharp_draw, width, core_color)

    if icon_type == "shell":
        def _draw(draw, w, col):
            draw.line([(c - r * 0.7, c - r * 0.6), (c - r * 0.1, c - r * 0.1)], fill=col, width=w)
            draw.line([(c - r * 0.1, c - r * 0.1), (c - r * 0.7, c + r * 0.4)], fill=col, width=w)
            draw.line([(c + r * 0.1, c + r * 0.4), (c + r * 0.8, c + r * 0.4)], fill=col, width=w)
        draw_all(_draw, round(dim * 0.04))

    elif icon_type == "about":
        def _draw(draw, w, col):
            draw.ellipse([(c - r, c - r), (c + r, c + r)], outline=col, width=w)
            draw.ellipse([(c - r * 0.15, c - r * 0.6), (c + r * 0.15, c - r * 0.3)], fill=col)
            draw.line([(c, c - r * 0.1), (c, c + r * 0.55)], fill=col, width=w)
            draw.line([(c - r * 0.25, c - r * 0.1), (c, c - r * 0.1)], fill=col, width=w)
            draw.line([(c - r * 0.3, c + r * 0.55), (c + r * 0.3, c + r * 0.55)], fill=col, width=w)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "exit":
        def _draw(draw, w, col):
            draw.line([(c - r * 0.4, c - r * 0.8), (c + r * 0.6, c - r * 0.8)], fill=col, width=w)
            draw.line([(c + r * 0.6, c - r * 0.8), (c + r * 0.6, c + r * 0.8)], fill=col, width=w)
            draw.line([(c + r * 0.6, c + r * 0.8), (c - r * 0.4, c + r * 0.8)], fill=col, width=w)
            draw.line([(c - r * 0.7, c), (c + r * 0.2, c)], fill=col, width=w)
            draw.line([(c - r * 0.1, c - r * 0.3), (c + r * 0.2, c)], fill=col, width=w)
            draw.line([(c - r * 0.1, c + r * 0.3), (c + r * 0.2, c)], fill=col, width=w)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "memtest":
        def _draw(draw, w, col):
            draw.rectangle([(c - r * 0.85, c - r * 0.45), (c + r * 0.85, c + r * 0.45)], outline=col, width=w)
            for i in range(-3, 4):
                px = c + i * (r * 0.22)
                draw.line([(px, c + r * 0.45), (px, c + r * 0.65)], fill=col, width=max(2, w // 2))
            for i in range(-2, 3):
                cx = c + i * (r * 0.32)
                draw.rectangle([(cx - r * 0.1, c - r * 0.25), (cx + r * 0.1, c + r * 0.15)], outline=col, width=max(1, w // 2))
        draw_all(_draw, round(dim * 0.03))

    elif icon_type == "mok":
        def _draw(draw, w, col):
            pts = [
                (c, c - r * 0.8),
                (c + r * 0.7, c - r * 0.5),
                (c + r * 0.7, c + r * 0.2),
                (c, c + r * 0.85),
                (c - r * 0.7, c + r * 0.2),
                (c - r * 0.7, c - r * 0.5),
            ]
            draw.polygon(pts, outline=col, width=w)
            draw.ellipse([(c - r * 0.2, c - r * 0.3), (c + r * 0.2, c + r * 0.1)], outline=col, width=max(2, w // 2))
            draw.line([(c, c + r * 0.1), (c, c + r * 0.45)], fill=col, width=w)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "netboot":
        def _draw(draw, w, col):
            draw.ellipse([(c - r * 0.75, c - r * 0.75), (c + r * 0.75, c + r * 0.75)], outline=col, width=w)
            draw.ellipse([(c - r * 0.35, c - r * 0.75), (c + r * 0.35, c + r * 0.75)], outline=col, width=max(2, w // 2))
            draw.line([(c - r * 0.75, c), (c + r * 0.75, c)], fill=col, width=max(2, w // 2))
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "part":
        def _draw(draw, w, col):
            draw.rectangle([(c - r * 0.75, c - r * 0.75), (c + r * 0.75, c + r * 0.75)], outline=col, width=w)
            draw.line([(c - r * 0.1, c - r * 0.75), (c - r * 0.1, c + r * 0.75)], fill=col, width=w)
            draw.line([(c - r * 0.75, c), (c + r * 0.75, c)], fill=col, width=max(2, w // 2))
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "rescue":
        def _draw(draw, w, col):
            draw.rectangle([(c - r * 0.8, c - r * 0.65), (c + r * 0.8, c + r * 0.65)], outline=col, width=w)
            draw.line([(c - r * 0.3, c - r * 0.65), (c - r * 0.3, c - r * 0.85)], fill=col, width=w)
            draw.line([(c + r * 0.3, c - r * 0.65), (c + r * 0.3, c - r * 0.85)], fill=col, width=w)
            draw.line([(c - r * 0.3, c - r * 0.85), (c + r * 0.3, c - r * 0.85)], fill=col, width=w)
            draw.line([(c, c - r * 0.35), (c, c + r * 0.35)], fill=col, width=w * 2)
            draw.line([(c - r * 0.35, c), (c + r * 0.35, c)], fill=col, width=w * 2)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "fwupdate":
        def _draw(draw, w, col):
            draw.rectangle([(c - r * 0.6, c - r * 0.6), (c + r * 0.6, c + r * 0.6)], outline=col, width=w)
            draw.line([(c, c + r * 0.35), (c, c - r * 0.35)], fill=col, width=w)
            draw.line([(c - r * 0.3, c - r * 0.05), (c, c - r * 0.35)], fill=col, width=w)
            draw.line([(c + r * 0.3, c - r * 0.05), (c, c - r * 0.35)], fill=col, width=w)
            for off in (-0.35, 0, 0.35):
                draw.line([(c + off * r, c - r * 0.6), (c + off * r, c - r * 0.8)], fill=col, width=max(2, w // 2))
                draw.line([(c + off * r, c + r * 0.6), (c + off * r, c + r * 0.8)], fill=col, width=max(2, w // 2))
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "hidden":
        def _draw(draw, w, col):
            draw.arc([(c - r * 0.85, c - r * 0.5), (c + r * 0.85, c + r * 0.5)], 200, 340, fill=col, width=w)
            draw.arc([(c - r * 0.85, c - r * 0.5), (c + r * 0.85, c + r * 0.5)], 20, 160, fill=col, width=w)
            draw.ellipse([(c - r * 0.3, c - r * 0.3), (c + r * 0.3, c + r * 0.3)], fill=col)
            draw.line([(c - r * 0.7, c - r * 0.6), (c + r * 0.7, c + r * 0.6)], fill=col, width=w)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "bootorder":
        def _draw(draw, w, col):
            draw.line([(c - r * 0.35, c + r * 0.6), (c - r * 0.35, c - r * 0.6)], fill=col, width=w)
            draw.line([(c - r * 0.65, c - r * 0.2), (c - r * 0.35, c - r * 0.6)], fill=col, width=w)
            draw.line([(c - r * 0.05, c - r * 0.2), (c - r * 0.35, c - r * 0.6)], fill=col, width=w)
            draw.line([(c + r * 0.35, c - r * 0.6), (c + r * 0.35, c + r * 0.6)], fill=col, width=w)
            draw.line([(c + r * 0.05, c + r * 0.2), (c + r * 0.35, c + r * 0.6)], fill=col, width=w)
            draw.line([(c + r * 0.65, c + r * 0.2), (c + r * 0.35, c + r * 0.6)], fill=col, width=w)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "csr_rotate":
        def _draw(draw, w, col):
            draw.arc([(c - r * 0.7, c - r * 0.7), (c + r * 0.7, c + r * 0.7)], 45, 315, fill=col, width=w)
            draw.polygon([(c + r * 0.4, c - r * 0.9), (c + r * 0.8, c - r * 0.6), (c + r * 0.3, c - r * 0.4)], fill=col)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type == "mouse":
        pts = [
            (c - r * 0.55, c - r * 0.85), (c + r * 0.45, c + r * 0.15),
            (c - r * 0.02, c + r * 0.18), (c + r * 0.22, c + r * 0.85),
            (c - r * 0.02, c + r * 0.95), (c - r * 0.26, c + r * 0.3),
            (c - r * 0.55, c + r * 0.55),
        ]

        glow_draw.polygon(
            [(x + (x - c) * 0.05, y + (y - c) * 0.05) for x, y in pts],
            fill=glow_color,
        )
        sharp_draw.polygon(pts, fill=core_color)
        sharp_draw.line(
            [(c - r * 0.02, c + r * 0.18), (c + r * 0.22, c + r * 0.85)],
            fill=accent_red, width=max(2, round(dim * 0.02)),
        )

    elif icon_type in ("arrow_left", "arrow_right"):
        sign = -1 if icon_type == "arrow_left" else 1

        def _draw(draw, w, col):
            draw.line(
                [
                    (c - sign * r * 0.30, c - r * 0.62),
                    (c + sign * r * 0.34, c),
                    (c - sign * r * 0.30, c + r * 0.62),
                ],
                fill=col, width=w, joint="curve",
            )
            tick = max(2, w // 3)
            for edge in (-1, 1):
                y = c + edge * r * 0.92
                draw.line(
                    [(c - r * 0.55, y), (c - r * 0.25, y)], fill=col, width=tick
                )
                draw.line(
                    [(c + r * 0.55, y), (c + r * 0.25, y)], fill=col, width=tick
                )
        draw_all(_draw, round(dim * 0.055))

    elif icon_type == "os_unknown":
        def _draw(draw, w, col):
            draw.rectangle([(c - r * 0.75, c - r * 0.75), (c + r * 0.75, c + r * 0.75)], outline=col, width=w)
            draw.ellipse([(c - r * 0.3, c - r * 0.55), (c + r * 0.3, c - r * 0.15)], outline=col, width=w)
            draw.line([(c, c - r * 0.15), (c, c + r * 0.15)], fill=col, width=w)
            draw.ellipse([(c - r * 0.1, c + r * 0.35), (c + r * 0.1, c + r * 0.55)], fill=col)
        draw_all(_draw, round(dim * 0.035))

    elif icon_type.startswith("os_"):
        os_name = icon_type[3:].upper()
        def _draw(draw, w, col):
            draw.rectangle([(c - r * 0.85, c - r * 0.85), (c + r * 0.85, c + r * 0.85)], outline=col, width=w)
            draw.text((c, c), os_name[:3], fill=col, anchor="mm", font_size=round(dim * 0.28))
        draw_all(_draw, round(dim * 0.035))

    elif icon_type.startswith("vol_"):
        v_type = icon_type[4:]

        def _draw(draw, w, col):
            if v_type == "external":  # USB stick
                draw.rectangle(
                    [(c - r * 0.42, c - r * 0.30), (c + r * 0.42, c + r * 0.90)],
                    outline=col, width=w,
                )
                draw.rectangle(
                    [(c - r * 0.30, c - r * 0.86), (c + r * 0.30, c - r * 0.30)],
                    outline=col, width=w,
                )
                for offset in (-0.14, 0.14):
                    draw.line(
                        [(c + offset * r, c - r * 0.74),
                         (c + offset * r, c - r * 0.42)], fill=col, width=w)
            elif v_type == "optical":  # disc
                draw.ellipse(
                    [(c - r * 0.86, c - r * 0.86), (c + r * 0.86, c + r * 0.86)],
                    outline=col, width=w,
                )
                draw.ellipse(
                    [(c - r * 0.22, c - r * 0.22), (c + r * 0.22, c + r * 0.22)],
                    outline=col, width=w,
                )
                draw.arc(
                    [(c - r * 0.58, c - r * 0.58), (c + r * 0.58, c + r * 0.58)],
                    210, 285, fill=col, width=max(2, w // 2),
                )
            elif v_type == "net":  # globe with meridians
                draw.ellipse(
                    [(c - r * 0.85, c - r * 0.85), (c + r * 0.85, c + r * 0.85)],
                    outline=col, width=w,
                )
                draw.ellipse(
                    [(c - r * 0.34, c - r * 0.85), (c + r * 0.34, c + r * 0.85)],
                    outline=col, width=w,
                )
                draw.line(
                    [(c - r * 0.85, c), (c + r * 0.85, c)], fill=col, width=w
                )
            elif v_type == "efi":  # chip with pins
                draw.rectangle(
                    [(c - r * 0.55, c - r * 0.55), (c + r * 0.55, c + r * 0.55)],
                    outline=col, width=w,
                )
                for offset in (-0.30, 0.0, 0.30):
                    draw.line(
                        [(c + offset * r, c - r * 0.90),
                         (c + offset * r, c - r * 0.55)], fill=col, width=w)
                    draw.line(
                        [(c + offset * r, c + r * 0.55),
                         (c + offset * r, c + r * 0.90)], fill=col, width=w)
                    draw.line(
                        [(c - r * 0.90, c + offset * r),
                         (c - r * 0.55, c + offset * r)], fill=col, width=w)
                    draw.line(
                        [(c + r * 0.55, c + offset * r),
                         (c + r * 0.90, c + offset * r)], fill=col, width=w)
            else:  # internal drive stack
                draw.rectangle(
                    [(c - r * 0.85, c - r * 0.62), (c + r * 0.85, c + r * 0.02)],
                    outline=col, width=w,
                )
                draw.rectangle(
                    [(c - r * 0.85, c + r * 0.18), (c + r * 0.85, c + r * 0.82)],
                    outline=col, width=w,
                )
                draw.ellipse(
                    [(c + r * 0.42, c + r * 0.42), (c + r * 0.62, c + r * 0.62)],
                    fill=col,
                )
        draw_all(_draw, round(dim * 0.055))

    glow = glow.filter(ImageFilter.GaussianBlur(max(1, round(dim * 0.014))))
    combined = Image.alpha_composite(glow, sharp)
    return combined.resize((size, size), Image.Resampling.LANCZOS)


def ellipsize(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    shortened = text
    while shortened and draw.textlength(
        shortened + suffix, font=font
    ) > max_width:
        shortened = shortened[:-1]
    return shortened + suffix


# --- AI-generated icon directory ---
AI_ICON_DIR = Path(__file__).resolve().parent / "ai_icons"


def load_ai_icon(name: str, size: int) -> "Image.Image | None":
    """Load an AI-generated icon from the ai_icons/ directory.

    Looks for ``ai_icons/<name>.jpg`` or ``ai_icons/<name>.png``.
    Returns an RGBA image resized to ``(size, size)`` with the background
    flood-filled to transparency from all four corners, or *None* if no
    file is found.
    """
    _require_pillow()
    for suffix in (".png", ".jpg", ".jpeg"):
        candidate = AI_ICON_DIR / f"{name}{suffix}"
        if candidate.exists():
            break
    else:
        return None

    try:
        with Image.open(candidate) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGBA")
    except (OSError, ValueError):
        return None

    # Crop to square center
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    # Work at 4× resolution for clean antialiased edges
    work_size = size * 4
    img = img.resize((work_size, work_size), Image.Resampling.LANCZOS)

    # Flood-fill background removal from all 4 corners
    pixels = img.load()
    ww, hh = img.size
    visited: set[tuple[int, int]] = set()

    # Determine background color from corner average
    corner_samples = [
        pixels[1, 1], pixels[ww - 2, 1],
        pixels[1, hh - 2], pixels[ww - 2, hh - 2],
    ]
    avg_lum = sum(
        (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) for c in corner_samples
    ) / len(corner_samples)
    # If corners are bright → white bg; if dark → black bg
    is_light_bg = avg_lum > 128
    tolerance = 55  # color-distance tolerance for flood fill

    def _matches_bg(r: int, g: int, b: int, a: int) -> bool:
        if a < 30:
            return True  # already transparent
        if is_light_bg:
            return min(r, g, b) > (255 - tolerance)
        else:
            return max(r, g, b) < tolerance

    # Seed from edges (all border pixels)
    stack: list[tuple[int, int]] = []
    for x in range(ww):
        stack.append((x, 0))
        stack.append((x, hh - 1))
    for y in range(1, hh - 1):
        stack.append((0, y))
        stack.append((ww - 1, y))

    while stack:
        x, y = stack.pop()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        r, g, b, a = pixels[x, y]
        if not _matches_bg(r, g, b, a):
            continue
        pixels[x, y] = (0, 0, 0, 0)
        # 4-connected neighbors
        if x > 0:
            stack.append((x - 1, y))
        if x < ww - 1:
            stack.append((x + 1, y))
        if y > 0:
            stack.append((x, y - 1))
        if y < hh - 1:
            stack.append((x, y + 1))

    # Crop tightly to the icon's non-transparent bounding box so its cyber frame
    # matches the 100% scale of bios.png and power.png (no empty outer padding)
    bbox = img.getbbox()
    if bbox:
        bx0, by0, bx1, by1 = bbox
        max_d = max(bx1 - bx0, by1 - by0)
        cx = (bx0 + bx1) // 2
        cy = (by0 + by1) // 2
        half = max_d // 2
        img = img.crop((cx - half, cy - half, cx + half, cy + half))

    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_background(
    source: Path,
    resolution: Resolution,
    hardware: HardwareInfo,
    font_path: Path | None = None,
    *,
    overlay_path: Path | None = None,
    effect_path: Path | None = None,
):
    """Compose the full-screen artwork with HUD overlay, glitch effects, and
    typewriter-style hardware readout.

    Layers (bottom to top):
      1. ``source`` — dark base background (skull, eye, HUD elements)
      2. ``overlay_path`` — white/RGBA HUD frame, title bar, decorative art
      3. Hardware spec text rendered as a typewriter animation frozen mid-line
      4. ``effect_path`` — glitch/noise scanline texture (screen-blended)
      5. Procedural scanlines and noise grain for extra life
      6. Navigation bar
    """
    _require_pillow()
    import random as _rng

    target_w, target_h = resolution.width, resolution.height

    # --- Layer 1: base background ---
    try:
        with Image.open(source) as image:
            base = ImageOps.fit(
                ImageOps.exif_transpose(image).convert("RGBA"),
                (target_w, target_h),
                Image.Resampling.LANCZOS,
            )
    except (OSError, ValueError) as exc:
        raise ThemeError(f"cannot open background {source}: {exc}") from exc

    canvas = Image.new("RGBA", base.size, (0, 0, 0, 255))
    canvas.alpha_composite(base)
    canvas.putpixel((0, 0), (0, 0, 0, 255))

    # --- Layer 2: HUD overlay (white text, skull, eye art) ---
    if overlay_path is not None:
        try:
            with Image.open(overlay_path) as ov:
                overlay_rgba = ImageOps.fit(
                    ImageOps.exif_transpose(ov).convert("RGBA"),
                    (target_w, target_h),
                    Image.Resampling.LANCZOS,
                )
                canvas.alpha_composite(overlay_rgba)
        except (OSError, ValueError):
            pass  # overlay is optional — skip if unreadable

    draw = ImageDraw.Draw(canvas)

    # --- Layer 3: Hardware spec — typewriter style ---
    scale_h = target_h / 2160.0
    scale_w = target_w / 3840.0
    font_size = max(14, round(24 * scale_h)) if overlay_path is not None else 22
    hud_font = find_font(font_path, font_size)

    spec_lines = [
        f"UEFI {hardware.uefi_version} ] Secure Boot: {hardware.secure_boot}",
        f"CPU: {hardware.cpu}",
        f"RAM: {hardware.ram}",
        f"GPU: {hardware.gpu}",
        f"NVMe: {hardware.nvme} -- OK",
    ]

    if overlay_path is not None:
        y_coords = [round(y * scale_h) for y in (168, 240, 312, 384, 456)]
        x_start = round(175 * scale_w)
        c_y = round(528 * scale_h)
        prompt_str = ""
    else:
        y_coords = [60 + i * 32 for i in range(5)]
        x_start = 70
        c_y = 60 + 5 * 32
        prompt_str = "> "

    for line, y in zip(spec_lines, y_coords):
        display_line = f"{prompt_str}{line}"
        draw.text(
            (x_start, y),
            ellipsize(draw, display_line, hud_font, resolution.width // 2),
            font=hud_font,
            fill="#E4E4E4",
        )

    # Active typing line with glowing cyber red cursor
    init_text = f"{prompt_str}INIT_CORE_v2.6..."
    draw.text((x_start, c_y), init_text, font=hud_font, fill="#EFEFEF")
    c_len = draw.textlength(init_text, font=hud_font)
    cur_h = max(16, round(24 * scale_h))
    cur_w = max(10, round(16 * scale_w))
    draw.rectangle(
        (x_start + c_len + 8, c_y + 4, x_start + c_len + 8 + cur_w, c_y + 4 + cur_h),
        fill="#FF003C",
    )

    # --- Layer 4: Glitch/noise effect overlay (screen blend) ---
    if effect_path is not None:
        try:
            with Image.open(effect_path) as ef:
                effect_rgba = ImageOps.fit(
                    ImageOps.exif_transpose(ef).convert("RGBA"),
                    (target_w, target_h),
                    Image.Resampling.LANCZOS,
                )
                # Boost brightness so the subtle noise is visible
                effect_boosted = ImageEnhance.Brightness(effect_rgba).enhance(3.5)
                # Screen blend: for each channel, result = 1 - (1-a)*(1-b)
                # Approximated by compositing with moderate opacity
                effect_semi = effect_boosted.copy()
                r, g, b, a = effect_semi.split()
                # Set alpha to ~40% for visible but not overwhelming noise
                a = a.point(lambda x: min(255, int(x * 0.45)))
                effect_semi = Image.merge("RGBA", (r, g, b, a))
                canvas.alpha_composite(effect_semi)
        except (OSError, ValueError):
            pass  # effect is optional

    # --- Layer 5: Procedural scanlines and noise grain ---
    scanline_overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    scan_draw = ImageDraw.Draw(scanline_overlay)

    # Horizontal scanlines every 4 pixels, very subtle
    for y_pos in range(0, target_h, 4):
        scan_draw.line(
            [(0, y_pos), (target_w, y_pos)],
            fill=(0, 0, 0, 18),
            width=1,
        )

    # Random glitch bars — short bright/dark horizontal bars scattered across
    _rng.seed(42)  # deterministic so it's reproducible
    for _ in range(35):
        gy = _rng.randint(0, target_h - 1)
        gx = _rng.randint(0, target_w - 200)
        gw = _rng.randint(40, 250)
        brightness = _rng.choice([20, 25, 30, 35, 40])
        alpha = _rng.randint(30, 80)
        scan_draw.rectangle(
            [(gx, gy), (gx + gw, gy + 1)],
            fill=(brightness, brightness, brightness, alpha),
        )

    # Red glitch accents — sparse neon-red bars
    for _ in range(8):
        gy = _rng.randint(0, target_h - 1)
        gx = _rng.randint(0, target_w - 100)
        gw = _rng.randint(20, 120)
        scan_draw.rectangle(
            [(gx, gy), (gx + gw, gy + 1)],
            fill=(255, 0, 60, _rng.randint(15, 50)),
        )

    canvas.alpha_composite(scanline_overlay)

    # --- Layer 6: Navigation bar ---
    nav_size = 20
    nav_font = find_font(font_path, nav_size)
    total = sum(
        draw.textlength(segment, font=nav_font)
        for segment in (NAV_LEFT, NAV_ENTER, NAV_RIGHT)
    )
    while nav_size > 14 and total > resolution.width - 140:
        nav_size -= 1
        nav_font = find_font(font_path, nav_size)
        total = sum(
            draw.textlength(segment, font=nav_font)
            for segment in (NAV_LEFT, NAV_ENTER, NAV_RIGHT)
        )
    if total > resolution.width - 40:
        raise ThemeError(f"navigation text does not fit resolution {resolution}")
    x = (resolution.width - total) / 2
    y = resolution.height - 70
    for segment, color in (
        (NAV_LEFT, "#DCDCDC"),
        (NAV_ENTER, "#FF003C"),
        (NAV_RIGHT, "#DCDCDC"),
    ):
        draw.text((x, y), segment, font=nav_font, fill=color)
        x += draw.textlength(segment, font=nav_font)
    return canvas


def run_command(
    argv: Sequence[str], *, check: bool = False, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run an external command without a shell or locale-dependent decoding."""
    full_env = dict(os.environ)
    full_env["LC_ALL"] = "C"
    full_env["LANG"] = "C"
    if env:
        full_env.update(env)
    return subprocess.run(
        list(argv),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
        env=full_env,
    )


def _storage_size(value: int) -> str:
    for unit, divisor in (("TB", 10**12), ("GB", 10**9)):
        if value >= divisor:
            return f"{round(value / divisor)} {unit}"
    return f"{round(value / 10**6)} MB"


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_windows_cim(payload: str) -> HardwareInfo:
    """Normalize the compact JSON emitted by the PowerShell CIM probe."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ThemeError(f"invalid Windows hardware JSON: {exc}") from exc

    memory = _as_list(data.get("Memory"))
    capacity = sum(int(item.get("Capacity") or 0) for item in memory)
    ddr_types = {
        20: "DDR",
        21: "DDR2",
        24: "DDR3",
        26: "DDR4",
        34: "DDR5",
    }
    ddr = next(
        (
            ddr_types.get(int(item.get("SMBIOSMemoryType") or 0))
            for item in memory
            if ddr_types.get(int(item.get("SMBIOSMemoryType") or 0))
        ),
        "DDR",
    )
    speeds = [int(item.get("Speed") or 0) for item in memory]
    speed = max(speeds, default=0)
    ram_parts = [
        f"{round(capacity / 1024**3)} GB" if capacity else "UNKNOWN",
        ddr,
    ]
    if speed:
        ram_parts.append(f"{speed} MT/s")

    gpu_names = [
        str(item.get("Name", "")).strip()
        for item in _as_list(data.get("Gpu"))
        if str(item.get("Name", "")).strip()
    ]
    nvme_sizes = []
    for item in _as_list(data.get("Disk")):
        descriptor = " ".join(
            str(item.get(key, ""))
            for key in ("Model", "InterfaceType", "PNPDeviceID")
        ).casefold()
        if "nvme" in descriptor:
            nvme_sizes.append(int(item.get("Size") or 0))
    secure_boot = "ON" if data.get("SecureBoot") is True else "OFF"
    return HardwareInfo(
        cpu=str(data.get("Cpu") or "UNKNOWN").strip(),
        ram=" ".join(ram_parts),
        gpu=" / ".join(dict.fromkeys(gpu_names)) or "UNKNOWN",
        nvme=_storage_size(max(nvme_sizes)) if nvme_sizes else "UNKNOWN",
        secure_boot=secure_boot,
    )


def _flatten_block_devices(devices: Iterable[Mapping[str, object]]):
    for device in devices:
        yield device
        children = device.get("children")
        if isinstance(children, list):
            yield from _flatten_block_devices(children)


def parse_linux_telemetry(
    outputs: Mapping[str, str], files: Mapping[str, str]
) -> HardwareInfo:
    """Normalize Linux command/file samples without requiring every utility."""
    cpu_match = re.search(
        r"^(?:Model name|model name|Nazwa modelu)\s*:\s*(.+)$",
        outputs.get("lscpu", ""),
        re.MULTILINE | re.IGNORECASE,
    )
    if not cpu_match:
        cpu_match = re.search(
            r"^(?:model name|Model name|Nazwa modelu)\s*:\s*(.+)$",
            files.get("/proc/cpuinfo", ""),
            re.MULTILINE | re.IGNORECASE,
        )
    cpu = cpu_match.group(1).strip() if cpu_match else "UNKNOWN"

    mem_match = re.search(
        r"^MemTotal:\s*(\d+)\s+kB",
        files.get("/proc/meminfo", ""),
        re.MULTILINE,
    )
    dmi = outputs.get("dmidecode", "")
    dmi_sizes = [
        int(m.group(1)) * (1024 if "G" in m.group(2).upper() else 1)
        for m in re.finditer(
            r"^\s*Size:\s*(\d+)\s*(MB|GB|GiB|MiB)", dmi, re.MULTILINE | re.IGNORECASE
        )
    ]
    if dmi_sizes:
        memory_gb = round(sum(dmi_sizes) / 1024)
    elif mem_match:
        memory_gb = round(int(mem_match.group(1)) / 1024**2)
    else:
        memory_gb = 0

    type_match = re.search(r"^\s*Type:\s*(DDR\d*)", dmi, re.MULTILINE | re.I)
    speed_match = re.search(
        r"^\s*(?:Configured Memory Speed|Speed):\s*(\d+)\s*MT/s",
        dmi,
        re.MULTILINE | re.I,
    )
    ram_parts = [f"{memory_gb} GB" if memory_gb else "UNKNOWN"]
    if type_match:
        ram_parts.append(type_match.group(1).upper())
    if speed_match:
        ram_parts.append(f"{speed_match.group(1)} MT/s")

    gpu_names: list[str] = []
    for line in outputs.get("lspci", "").splitlines():
        if re.search(r"\b(VGA|3D|Display)\b", line, re.I):
            gpu_names.append(line.split(": ", 1)[-1].strip())

    nvme_sizes: list[int] = []
    try:
        lsblk = json.loads(outputs.get("lsblk", "{}"))
        for item in _flatten_block_devices(lsblk.get("blockdevices", [])):
            name = str(item.get("name", ""))
            transport = str(item.get("tran", ""))
            if (
                str(item.get("type", "")).casefold() == "disk"
                and ("nvme" in name.casefold() or transport.casefold() == "nvme")
            ):
                nvme_sizes.append(int(item.get("size") or 0))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    mokutil = outputs.get("mokutil", "").casefold()
    if "enabled" in mokutil:
        secure_boot = "ON"
    elif "disabled" in mokutil:
        secure_boot = "OFF"
    else:
        secure_boot = "UNKNOWN"
        for path, raw in files.items():
            if "SecureBoot-" in path and raw:
                secure_boot = "ON" if ord(raw[-1]) else "OFF"
                break

    return HardwareInfo(
        cpu=cpu,
        ram=" ".join(ram_parts),
        gpu=" / ".join(dict.fromkeys(gpu_names)) or "UNKNOWN",
        nvme=_storage_size(max(nvme_sizes)) if nvme_sizes else "UNKNOWN",
        secure_boot=secure_boot,
    )


def apply_hardware_overrides(
    info: HardwareInfo, overrides: HardwareOverrides
) -> HardwareInfo:
    secure_boot = (
        info.secure_boot
        if overrides.secure_boot == "auto"
        else overrides.secure_boot.upper()
    )
    return dataclasses.replace(
        info,
        cpu=overrides.cpu or info.cpu,
        ram=overrides.ram or info.ram,
        gpu=overrides.gpu or info.gpu,
        nvme=overrides.nvme or info.nvme,
        uefi_version=overrides.uefi_version,
        secure_boot=secure_boot,
    )


WINDOWS_CIM_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$secure = $false
try { $secure = Confirm-SecureBootUEFI } catch { $secure = $false }
[ordered]@{
  Cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
  Memory = @(Get-CimInstance Win32_PhysicalMemory |
    Select-Object Capacity, SMBIOSMemoryType, Speed)
  Gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name)
  Disk = @(Get-CimInstance Win32_DiskDrive |
    Select-Object Model, Size, InterfaceType, PNPDeviceID)
  SecureBoot = [bool]$secure
} | ConvertTo-Json -Compress -Depth 5
"""


def collect_linux_outputs(
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, str]:
    commands = {
        "lscpu": ("lscpu",),
        "lspci": ("lspci",),
        "lsblk": ("lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,TRAN"),
        "dmidecode": ("dmidecode", "--type", "memory"),
        "mokutil": ("mokutil", "--sb-state"),
    }
    outputs: dict[str, str] = {}
    for key, command in commands.items():
        try:
            result = runner(command)
        except OSError:
            continue
        if result.returncode == 0 and result.stdout:
            outputs[key] = result.stdout
        elif key == "dmidecode":
            try:
                sudo_res = runner(("sudo", "-n", "dmidecode", "--type", "memory"))
                if sudo_res.returncode == 0 and sudo_res.stdout:
                    outputs[key] = sudo_res.stdout
            except OSError:
                pass
    return outputs


def collect_linux_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for path_str in ("/proc/meminfo", "/proc/cpuinfo"):
        p = Path(path_str)
        try:
            files[path_str] = p.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            pass
    efivars = Path("/sys/firmware/efi/efivars")
    try:
        secure_vars = list(efivars.glob("SecureBoot-*"))
    except OSError:
        secure_vars = []
    for path in secure_vars[:1]:
        try:
            files[str(path)] = path.read_bytes().decode("latin-1")
        except OSError:
            pass
    return files


def detect_hardware(
    system: str,
    overrides: HardwareOverrides,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> HardwareInfo:
    normalized = system.casefold()
    if normalized == "windows":
        try:
            result = runner(
                (
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    WINDOWS_CIM_SCRIPT,
                )
            )
        except OSError:
            result = None
        detected = (
            parse_windows_cim(result.stdout)
            if result is not None and result.returncode == 0 and result.stdout
            else HardwareInfo(cpu=platform.processor() or "UNKNOWN")
        )
    elif normalized == "linux":
        detected = parse_linux_telemetry(
            collect_linux_outputs(runner), collect_linux_files()
        )
    else:
        detected = HardwareInfo(cpu=platform.processor() or "UNKNOWN")
    return apply_hardware_overrides(detected, overrides)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _native_path(root: Path, relative: PurePosixPath) -> Path:
    return root.joinpath(*relative.parts)


def _safe_child(root: Path, relative: PurePosixPath) -> Path:
    root_resolved = root.resolve()
    target = _native_path(root_resolved, relative).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ThemeError(f"path escapes managed root: {relative}") from exc
    return target


def validate_theme(root: Path, resolution: Resolution) -> tuple[Path, ...]:
    """Re-open and validate every generated artifact before publication."""
    _require_pillow()
    root = root.resolve()
    files: list[Path] = []
    for relative_text, expected_size in IMAGE_SIZES.items():
        relative = PurePosixPath(relative_text)
        path = _safe_child(root, relative)
        if not path.is_file():
            raise ThemeError(f"generated image is missing: {path}")
        expected = (
            (resolution.width, resolution.height)
            if relative_text == "background.png"
            else expected_size
        )
        try:
            with Image.open(path) as image:
                actual_size = image.size
                actual_mode = image.mode
                image.verify()
        except OSError as exc:
            raise ThemeError(f"generated image is invalid: {path}: {exc}") from exc
        if actual_size != expected:
            raise ThemeError(
                f"generated image has wrong size: {path}: "
                f"{actual_size}, expected {expected}"
            )
        if actual_mode != "RGBA":
            raise ThemeError(
                f"generated image has wrong mode: {path}: "
                f"{actual_mode}, expected RGBA"
            )
        files.append(path)

    config_path = root / "theme.conf"
    if config_path.read_text(encoding="utf-8") != THEME_CONF:
        raise ThemeError(f"generated theme.conf is inconsistent: {config_path}")
    files.append(config_path)

    state_path = root / "install-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeError(f"generated install-state.json is invalid: {exc}") from exc
    if state.get("format_version") != 1 or state.get("resolution") != str(
        resolution
    ):
        raise ThemeError("generated install-state.json has incompatible metadata")
    files.append(state_path)
    return tuple(files)


def publish_owned_theme(staging: Path, output: Path) -> tuple[Path, ...]:
    """Atomically publish only files owned by this script."""
    staging = staging.resolve()
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    published: list[Path] = []
    for relative in OWNED_RELATIVE_PATHS:
        source = _safe_child(staging, relative)
        target = _safe_child(output, relative)
        if not source.is_file():
            raise ThemeError(f"staging file is missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        published.append(target)
    return tuple(published)


def _save_png(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(path, format="PNG", compress_level=6)


def build_theme(
    source_dir: Path,
    output_dir: Path,
    resolution: Resolution,
    hardware: HardwareInfo,
    font_path: Path | None = None,
) -> ThemeBuild:
    """Build a complete, validated theme through an external staging folder."""
    _require_pillow()
    assets = discover_assets(source_dir)
    output_dir = output_dir.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="ghoul-cyber-build-") as raw:
        staging = Path(raw) / THEME_NAME
        (staging / "icons").mkdir(parents=True)

        _save_png(
            render_background(
                assets["background"],
                resolution,
                hardware,
                font_path,
                overlay_path=assets.get("background_overlay"),
                effect_path=assets.get("background_effect"),
            ),
            staging / "background.png",
        )
        _save_png(
            render_cyber_selection_frame(
                assets["selection_box"], SELECTION_BIG_SIZE, is_big=True
            ),
            staging / "selection_big.png",
        )
        _save_png(
            render_cyber_selection_frame(
                assets["selection_box"], SELECTION_SMALL_SIZE, is_big=False
            ),
            staging / "selection_small.png",
        )
        source_mapping = {
            "selection_item_windev": ("os_win_dev.png", BIG_ICON_SIZE),
            "selection_item_wingame": ("os_win_game.png", BIG_ICON_SIZE),
            "selection_item_linux": ("os_cachyos.png", BIG_ICON_SIZE),
            "bios": ("tool_firmware.png", SMALL_ICON_SIZE),
            "power": ("tool_shutdown.png", SMALL_ICON_SIZE),
        }
        for stem, (filename, size) in source_mapping.items():
            _save_png(
                resize_asset(assets[stem], size),
                staging / "icons" / filename,
            )
        ai_reboot = load_ai_icon("reboot", SMALL_ICON_SIZE) or load_ai_icon(
            "tool_reboot", SMALL_ICON_SIZE
        )
        _save_png(
            ai_reboot
            if ai_reboot is not None
            else render_reboot_icon(SMALL_ICON_SIZE),
            staging / "icons/tool_reboot.png",
        )

        generated_icons = {
            "tool_shell.png": (SMALL_ICON_SIZE, "shell"),
            "tool_memtest.png": (SMALL_ICON_SIZE, "memtest"),
            "tool_mok_tool.png": (SMALL_ICON_SIZE, "mok"),
            "tool_netboot.png": (SMALL_ICON_SIZE, "netboot"),
            "tool_part.png": (SMALL_ICON_SIZE, "part"),
            "tool_rescue.png": (SMALL_ICON_SIZE, "rescue"),
            "tool_fwupdate.png": (SMALL_ICON_SIZE, "fwupdate"),
            "func_about.png": (SMALL_ICON_SIZE, "about"),
            "func_exit.png": (SMALL_ICON_SIZE, "exit"),
            "func_hidden.png": (SMALL_ICON_SIZE, "hidden"),
            "func_bootorder.png": (SMALL_ICON_SIZE, "bootorder"),
            "func_csr_rotate.png": (SMALL_ICON_SIZE, "csr_rotate"),
            "mouse.png": (SMALL_ICON_SIZE, "mouse"),
            "arrow_left.png": (SMALL_ICON_SIZE, "arrow_left"),
            "arrow_right.png": (SMALL_ICON_SIZE, "arrow_right"),
            "vol_internal.png": (BADGE_ICON_SIZE, "vol_internal"),
            "vol_external.png": (BADGE_ICON_SIZE, "vol_external"),
            "vol_optical.png": (BADGE_ICON_SIZE, "vol_optical"),
            "vol_net.png": (BADGE_ICON_SIZE, "vol_net"),
            "vol_efi.png": (BADGE_ICON_SIZE, "vol_efi"),
            "os_unknown.png": (BIG_ICON_SIZE, "os_unknown"),
            "os_ubuntu.png": (BIG_ICON_SIZE, "os_ubuntu"),
            "os_debian.png": (BIG_ICON_SIZE, "os_debian"),
            "os_fedora.png": (BIG_ICON_SIZE, "os_fedora"),
            "os_mac.png": (BIG_ICON_SIZE, "os_mac"),
        }
        for filename, (sz, itype) in generated_icons.items():
            # Prefer AI-generated icon if available in ai_icons/ directory
            ai_img = load_ai_icon(itype, sz)
            if ai_img is not None:
                _save_png(ai_img, staging / "icons" / filename)
            else:
                _save_png(render_cyber_icon(sz, itype), staging / "icons" / filename)

        # Distro cards rEFInd falls back to. They must NOT be copies of the
        # CachyOS/DEV cards: those carry baked-in "CACHY" and "DEV" labels.
        card_icons = {
            "os_win.png": {
                "glyph": "win", "title": "WINDOWS // 11",
                "label": "WIN_OS", "index": "02", "katakana": "ウィン",
            },
            "os_arch.png": {
                "glyph": "arch", "title": "ARCH // LINUX",
                "label": "ARCH_OS", "index": "04", "katakana": "アーチ",
            },
            "os_linux.png": {
                "glyph": "penguin", "title": "GNU // LINUX",
                "label": "LINUX", "index": "05", "katakana": "リナクス",
            },
        }
        for filename, spec in card_icons.items():
            ai_img = load_ai_icon(filename[: -len(".png")], BIG_ICON_SIZE)
            _save_png(
                ai_img
                if ai_img is not None
                else render_cyber_card(BIG_ICON_SIZE, **spec),
                staging / "icons" / filename,
            )

        aliases = {
            "func_firmware.png": "tool_firmware.png",
            "func_shutdown.png": "tool_shutdown.png",
            "func_reset.png": "tool_reboot.png",
        }
        for alias, source_name in aliases.items():
            shutil.copy2(
                staging / "icons" / source_name, staging / "icons" / alias
            )

        (staging / "theme.conf").write_text(
            THEME_CONF, encoding="utf-8", newline="\n"
        )
        hashed_paths = [
            PurePosixPath(path) for path in (*IMAGE_SIZES, "theme.conf")
        ]
        state = {
            "format_version": 1,
            "theme": THEME_NAME,
            "resolution": str(resolution),
            "assignments": {},
            "sha256": {
                relative.as_posix(): sha256_file(_safe_child(staging, relative))
                for relative in hashed_paths
            },
        }
        (staging / "install-state.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        validate_theme(staging, resolution)
        files = publish_owned_theme(staging, output_dir)
    validate_theme(output_dir, resolution)
    return ThemeBuild(output_dir=output_dir, resolution=resolution, files=files)


BOOT_LINE = re.compile(
    r"^Boot(?P<num>[0-9A-Fa-f]{4})\*?\s+"
    r"(?P<label>.*?)\s+HD\(\d+,GPT,"
    r"(?P<guid>[0-9A-Fa-f-]+),[^)]*\)"
    r".*?(?:(?:/|/\\|\\)?File\()?(?P<path>\\(?:[^\s()]*?\.(?:efi|bin|img|elf)|[^\s()]+))",
    re.IGNORECASE,
)


def parse_efibootmgr(text: str) -> list[BootEntry]:
    """Parse GPT file-loader entries from efibootmgr -v."""
    entries: list[BootEntry] = []
    for line in text.splitlines():
        match = BOOT_LINE.search(line)
        if match:
            path = match.group("path")
            if path.endswith(")"):
                path = path[:-1]
            entries.append(
                BootEntry(
                    bootnum=match.group("num").upper(),
                    label=match.group("label").strip(),
                    partuuid=match.group("guid").lower(),
                    loader_path=path,
                )
            )
    if not entries:
        raise ThemeError(
            "efibootmgr did not expose any GPT file-loader entries; "
            "confirm that Linux was booted in UEFI mode"
        )
    return entries


def parse_lsblk(text: str) -> dict[str, Mapping[str, object]]:
    """Flatten lsblk JSON and index partitions by lowercase PARTUUID."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ThemeError(f"invalid lsblk JSON: {exc}") from exc
    devices: dict[str, Mapping[str, object]] = {}
    for item in _flatten_block_devices(payload.get("blockdevices", [])):
        partuuid = str(item.get("partuuid") or "").strip().casefold()
        if partuuid:
            devices[partuuid] = item
    return devices


def _mount_points(item: Mapping[str, object]) -> tuple[str, ...]:
    raw = item.get("mountpoints")
    if isinstance(raw, list):
        values = raw
    elif raw:
        values = [raw]
    elif item.get("mountpoint"):
        values = [item.get("mountpoint")]
    else:
        values = []
    return tuple(str(value) for value in values if value)


def enrich_boot_entries(
    entries: Iterable[BootEntry],
    devices: Mapping[str, Mapping[str, object]],
) -> list[BootEntry]:
    enriched: list[BootEntry] = []
    for entry in entries:
        item = devices.get(entry.partuuid.casefold(), {})
        enriched.append(
            dataclasses.replace(
                entry,
                device=str(item.get("path") or item.get("name") or ""),
                fs_label=str(item.get("label") or ""),
                part_label=str(item.get("partlabel") or ""),
                size=str(item.get("size") or ""),
                mount_points=_mount_points(item),
            )
        )
    return enriched


def _entry_tokens(entry: BootEntry) -> set[str]:
    text = " ".join(
        (
            entry.label,
            entry.fs_label,
            entry.part_label,
            entry.loader_path,
        )
    ).casefold()
    return {token for token in re.split(r"[^a-z0-9]+", text) if token}


def _entry_matches_previous(
    entry: BootEntry, role_data: Mapping[str, object] | None
) -> bool:
    if not role_data:
        return False
    return (
        str(role_data.get("partuuid", "")).casefold()
        == entry.partuuid.casefold()
        and str(role_data.get("loader_path", "")).casefold()
        == entry.loader_path.casefold()
    )


def assign_boot_roles(
    entries: Sequence[BootEntry],
    *,
    choose_dev: Callable[[Sequence[BootEntry]], int] | None,
    non_interactive: bool,
    previous: Mapping[str, object] | None = None,
    devices: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, BootEntry]:
    """Assign Windows loader(s) and CachyOS loader."""
    windows = [
        entry
        for entry in entries
        if "windows" in _entry_tokens(entry)
        or "microsoft" in entry.loader_path.casefold()
        or "bootmgfw.efi" in entry.loader_path.casefold()
    ]
    cachy = [
        entry
        for entry in entries
        if (
            any(
                token.startswith(("cachy", "arch", "linux"))
                for token in _entry_tokens(entry)
            )
            or "cachy" in entry.loader_path.casefold()
            or "vmlinuz" in entry.loader_path.casefold()
        )
        and "refind" not in entry.loader_path.casefold()
    ]
    if not cachy:
        boot_kernel = find_cachyos_kernel(Path("/boot"))
        kernel_name = boot_kernel.name if boot_kernel else "vmlinuz-linux-cachyos"
        loader_rel = f"\\{kernel_name}"
        boot_entry = None
        if devices:
            for partuuid, item in devices.items():
                mounts = _mount_points(item)
                if any(m.rstrip("/") == "/boot" for m in mounts):
                    boot_entry = BootEntry(
                        bootnum="AUTO",
                        label="CachyOS",
                        partuuid=partuuid,
                        loader_path=loader_rel,
                        device=str(item.get("path") or item.get("name") or ""),
                        fs_label=str(item.get("label") or "CachyOS"),
                        mount_points=mounts,
                    )
                    break
        if not boot_entry and Path("/boot").is_dir():
            boot_entry = BootEntry(
                bootnum="AUTO",
                label="CachyOS",
                partuuid="",
                loader_path=loader_rel,
                device="/dev/nvme0n1p1",
                fs_label="CachyOS",
                mount_points=("/boot",),
            )
        if boot_entry:
            cachy = [boot_entry]

    if not windows:
        raise ThemeError("expected at least one Windows UEFI loader, found 0")
    if not cachy:
        raise ThemeError("expected at least one CachyOS UEFI loader, found 0")

    if len(windows) == 1:
        dev = windows[0]
        game = windows[0]
    else:
        previous = previous or {}
        previous_dev = next(
            (
                entry
                for entry in windows
                if _entry_matches_previous(
                    entry,
                    previous.get("win_dev")
                    if isinstance(previous.get("win_dev"), Mapping)
                    else None,
                )
            ),
            None,
        )
        previous_game = next(
            (
                entry
                for entry in windows
                if _entry_matches_previous(
                    entry,
                    previous.get("win_game")
                    if isinstance(previous.get("win_game"), Mapping)
                    else None,
                )
            ),
            None,
        )
        if previous_dev and previous_game and previous_dev != previous_game:
            return {
                "win_dev": previous_dev,
                "win_game": previous_game,
                "cachyos": cachy[0],
            }
        if previous_dev:
            return {
                "win_dev": previous_dev,
                "win_game": next(entry for entry in windows if entry != previous_dev),
                "cachyos": cachy[0],
            }
        if previous_game:
            return {
                "win_dev": next(entry for entry in windows if entry != previous_game),
                "win_game": previous_game,
                "cachyos": cachy[0],
            }

        dev_matches = [
            entry
            for entry in windows
            if _entry_tokens(entry) & {"dev", "developer", "development"}
        ]
        game_matches = [
            entry
            for entry in windows
            if _entry_tokens(entry) & {"game", "gaming", "games"}
        ]
        dev: BootEntry | None = None
        game: BootEntry | None = None
        if len(dev_matches) == 1:
            dev = dev_matches[0]
            game = next(entry for entry in windows if entry != dev)
        if len(game_matches) == 1:
            candidate_game = game_matches[0]
            candidate_dev = next(entry for entry in windows if entry != candidate_game)
            if dev is None or (dev == candidate_dev and game == candidate_game):
                dev, game = candidate_dev, candidate_game
            else:
                dev = game = None

        if dev is None or game is None:
            if non_interactive or choose_dev is None:
                raise ThemeError(
                    "ambiguous Windows loaders: label an ESP DEV/GAMING or "
                    "run interactively"
                )
            selected = choose_dev(tuple(windows))
            if not isinstance(selected, int) or not 0 <= selected < len(windows):
                raise ThemeError("invalid DEV selection")
            dev = windows[selected]
            game = windows[1 - selected]

    return {"win_dev": dev, "win_game": game, "cachyos": cachy[0]}


def icon_path_for_loader(loader_path: str) -> str:
    if "\x00" in loader_path:
        raise ThemeError(f"loader path is unsafe: {loader_path!r}")
    path = PureWindowsPath(loader_path)
    if ".." in path.parts or not loader_path.startswith(("\\", "/")):
        raise ThemeError(f"loader path is unsafe: {loader_path!r}")
    if loader_path.casefold().endswith(".efi"):
        return loader_path[:-4] + ".png"
    return loader_path + ".png"


def find_cachyos_kernel(boot_dir: Path) -> Path | None:
    """Find a CachyOS kernel without following it outside the boot tree."""
    root = boot_dir.resolve()
    candidates: list[Path] = []
    try:
        for path in boot_dir.glob("vmlinuz*cachy*"):
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if resolved.is_file():
                candidates.append(path)
    except OSError:
        pass
    if not candidates and os.name == "posix" and getattr(os, "geteuid", lambda: 1)() != 0:
        res = subprocess.run(
            ["sudo", "-n", "ls", str(boot_dir)], capture_output=True, text=True
        )
        if res.returncode == 0:
            for name in res.stdout.splitlines():
                if "vmlinuz" in name and "cachy" in name:
                    candidates.append(boot_dir / name)
    if not candidates:
        return None
    main_cachy = [c for c in candidates if c.name == "vmlinuz-linux-cachyos"]
    if main_cachy:
        return main_cachy[0]
    return sorted(candidates, key=lambda item: item.name)[-1]


def find_refind_dir(
    explicit: Path | None, candidates: Iterable[Path]
) -> Path:
    """Find a directory containing both refind.conf and a rEFInd EFI binary."""

    def valid(path: Path) -> bool:
        try:
            if (
                path.is_dir()
                and (path / "refind.conf").is_file()
                and any(candidate.is_file() for candidate in path.glob("refind_*.efi"))
            ):
                return True
        except OSError:
            pass
        if os.name == "posix" and getattr(os, "geteuid", lambda: 1)() != 0:
            res = subprocess.run(
                ["sudo", "-n", "test", "-f", str(path / "refind.conf")],
                capture_output=True,
            )
            if res.returncode == 0:
                return True
        return False

    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        if not valid(resolved):
            raise ThemeError(
                f"invalid rEFInd directory: {resolved}; expected "
                "refind.conf and refind_*.efi"
            )
        return resolved
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if valid(resolved):
            return resolved
    raise ThemeError(
        "rEFInd installation was not found; mount the ESP or pass --refind-dir"
    )


def update_managed_config(raw: bytes) -> bytes:
    """Append one idempotent managed include block while preserving encoding."""
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    try:
        body = raw[len(bom) :].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ThemeError("refind.conf must be UTF-8") from exc
    newline = "\r\n" if "\r\n" in body else "\n"
    pattern = re.compile(
        rf"(?ms)^[ \t]*{re.escape(MANAGED_BEGIN)}\r?\n.*?"
        rf"^[ \t]*{re.escape(MANAGED_END)}[ \t]*(?:\r?\n)?"
    )
    body = pattern.sub("", body).rstrip("\r\n")
    block = newline.join((MANAGED_BEGIN, MANAGED_INCLUDE, MANAGED_END))
    updated = body + newline * 2 + block + newline if body else block + newline
    return bom + updated.encode("utf-8")


class FileTransaction:
    """Recover file replacements and creations if deployment does not commit."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="ghoul-cyber-rollback-"
        )
        self._records: list[tuple[Path, Path | None]] = []
        self._finished = False

    def _capture(
        self, target: Path, permanent_backup: Path | None
    ) -> bool:
        if target.exists():
            if not target.is_file():
                raise ThemeError(f"deployment target is not a file: {target}")
            backup = Path(self._temporary.name) / f"{len(self._records):06d}"
            shutil.copy2(target, backup)
            self._records.append((target, backup))
            if permanent_backup is not None and not permanent_backup.exists():
                permanent_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, permanent_backup)
            return True
        self._records.append((target, None))
        return False

    @staticmethod
    def _atomic_copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(raw)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def copy_file(
        self,
        source: Path,
        target: Path,
        permanent_backup: Path | None = None,
    ) -> None:
        if not source.is_file():
            raise ThemeError(f"deployment source is not a file: {source}")
        if (
            target.is_file()
            and target.stat().st_size == source.stat().st_size
            and sha256_file(target) == sha256_file(source)
        ):
            return
        self._capture(target, permanent_backup)
        self._atomic_copy(source, target)

    def write_bytes(
        self,
        target: Path,
        payload: bytes,
        permanent_backup: Path | None = None,
    ) -> None:
        if target.is_file() and target.read_bytes() == payload:
            return
        self._capture(target, permanent_backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(raw)
        try:
            temporary.write_bytes(payload)
            if target.exists():
                shutil.copymode(target, temporary)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def rollback(self) -> None:
        if self._finished:
            return
        errors: list[str] = []
        for target, backup in reversed(self._records):
            try:
                if backup is None:
                    if target.is_file() or target.is_symlink():
                        target.unlink()
                else:
                    self._atomic_copy(backup, target)
            except OSError as exc:
                errors.append(f"{target}: {exc}")
        self._finished = True
        self._temporary.cleanup()
        if errors:
            raise ThemeError("rollback was incomplete: " + "; ".join(errors))

    def commit(self) -> None:
        if not self._finished:
            self._finished = True
            self._temporary.cleanup()


def copy_owned_theme(
    source: Path, refind_dir: Path, transaction: FileTransaction
) -> Path:
    source = source.resolve()
    destination = (refind_dir / "themes" / THEME_NAME).resolve()
    expected_parent = refind_dir.resolve()
    try:
        destination.relative_to(expected_parent)
    except ValueError as exc:
        raise ThemeError("theme destination escapes the rEFInd directory") from exc
    for relative in OWNED_RELATIVE_PATHS:
        source_file = _safe_child(source, relative)
        destination_file = _safe_child(destination, relative)
        transaction.copy_file(source_file, destination_file)
    return destination


def deployment_plan_to_json(plan: DeploymentPlan) -> str:
    payload = {
        "theme_source": str(plan.theme_source),
        "refind_dir": str(plan.refind_dir),
        "invoking_uid": plan.invoking_uid,
        "invoking_gid": plan.invoking_gid,
        "targets": [
            {
                "role": target.role,
                "source_icon": str(target.source_icon),
                "device": target.device,
                "partuuid": target.partuuid,
                "loader_path": target.loader_path,
                "mount_point": (
                    str(target.mount_point)
                    if target.mount_point is not None
                    else None
                ),
            }
            for target in plan.targets
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _validate_source_icon(theme_source: Path, source_icon: Path) -> Path:
    icons_root = (theme_source / "icons").resolve()
    resolved = source_icon.resolve()
    try:
        resolved.relative_to(icons_root)
    except ValueError as exc:
        raise ThemeError(f"source icon escapes theme icons: {source_icon}") from exc
    if not resolved.is_file():
        raise ThemeError(f"source icon does not exist: {resolved}")
    return resolved


def deployment_plan_from_json(
    payload: str, *, validate: bool = True
) -> DeploymentPlan:
    try:
        data = json.loads(payload)
        targets = tuple(
            BootTarget(
                role=str(item["role"]),
                source_icon=Path(item["source_icon"]),
                device=str(item["device"]),
                partuuid=str(item["partuuid"]),
                loader_path=str(item["loader_path"]),
                mount_point=(
                    Path(item["mount_point"]) if item.get("mount_point") else None
                ),
            )
            for item in data["targets"]
        )
        plan = DeploymentPlan(
            theme_source=Path(data["theme_source"]),
            refind_dir=Path(data["refind_dir"]),
            targets=targets,
            invoking_uid=data.get("invoking_uid"),
            invoking_gid=data.get("invoking_gid"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ThemeError(f"invalid privileged deployment plan: {exc}") from exc
    if not validate:
        return plan

    theme_source = plan.theme_source.resolve()
    state_path = theme_source / "install-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        resolution = parse_resolution(str(state["resolution"]))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ThemeError(f"cannot validate deployment theme: {exc}") from exc
    validate_theme(theme_source, resolution)
    refind_dir = find_refind_dir(plan.refind_dir, ())
    roles = {target.role for target in plan.targets}
    if not roles.intersection({"win_dev", "win_game", "cachyos"}) or not plan.targets:
        raise ThemeError(
            "deployment plan must contain valid boot roles"
        )
    validated_targets = []
    for target in plan.targets:
        icon_path_for_loader(target.loader_path)
        if not target.device.startswith("/dev/"):
            raise ThemeError(f"unsafe block device in plan: {target.device!r}")
        if not target.partuuid or "\x00" in target.partuuid:
            raise ThemeError("deployment plan contains an invalid PARTUUID")
        validated_targets.append(
            dataclasses.replace(
                target,
                source_icon=_validate_source_icon(
                    theme_source, target.source_icon
                ),
                mount_point=(
                    target.mount_point.resolve()
                    if target.mount_point is not None
                    else None
                ),
            )
        )
    return dataclasses.replace(
        plan,
        theme_source=theme_source,
        refind_dir=refind_dir,
        targets=tuple(validated_targets),
    )


def missing_linux_dependencies(
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    return tuple(
        name
        for name in ("efibootmgr", "lsblk", "findmnt")
        if which(name) is None
    )


def _arch_family() -> bool:
    try:
        raw = Path("/etc/os-release").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return False
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').casefold()
    return values.get("ID") in {"arch", "cachyos"} or "arch" in values.get(
        "ID_LIKE", ""
    ).split()


def bootstrap_linux_dependencies(
    missing: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    """Install known dependencies through pacman on CachyOS/Arch only."""
    if not missing:
        return
    if not _arch_family():
        packages = " ".join(PACMAN_PACKAGES.get(item, item) for item in missing)
        raise ThemeError(
            "missing Linux dependencies: "
            + ", ".join(missing)
            + f"; install the equivalent of: {packages}"
        )
    packages = list(
        dict.fromkeys(PACMAN_PACKAGES.get(item, item) for item in missing)
    )
    command = ["pacman", "-S", "--needed", "--noconfirm", *packages]
    if getattr(os, "geteuid", lambda: 1)() != 0:
        command.insert(0, "sudo")
    try:
        result = runner(tuple(command))
    except OSError as exc:
        raise ThemeError(f"cannot run dependency installer: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ThemeError(
            "dependency installation failed "
            f"(exit {result.returncode}): {detail or 'no diagnostic output'}"
        )


def ensure_volume_mounted(
    target: BootTarget,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> tuple[Path, bool]:
    """Return a mount root and whether this process mounted it."""
    if target.mount_point is not None:
        mount_point = target.mount_point.resolve()
        if mount_point.is_dir():
            return mount_point, False
    if platform.system().casefold() != "linux":
        raise ThemeError(
            f"volume for {target.role} is not mounted: {target.device}"
        )
    if not target.device.startswith("/dev/") or "\x00" in target.device:
        raise ThemeError(f"unsafe block device: {target.device!r}")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", target.partuuid)
    mount_point = Path("/run/ghoul-cyber") / safe_name
    mount_point.mkdir(parents=True, exist_ok=True)
    result = runner(("mount", "--", target.device, str(mount_point)))
    if result.returncode != 0:
        try:
            mount_point.rmdir()
        except OSError:
            pass
        raise ThemeError(
            f"cannot mount {target.device}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return mount_point.resolve(), True


def _efi_host_path(mount_root: Path, efi_path: str) -> Path:
    if (
        "\x00" in efi_path
        or not efi_path.startswith(("\\", "/"))
        or ".." in PureWindowsPath(efi_path).parts
    ):
        raise ThemeError(f"unsafe EFI volume path: {efi_path!r}")
    pure = PureWindowsPath(efi_path)
    parts = pure.parts[1:] if pure.parts and pure.parts[0] in {"\\", "/"} else pure.parts
    target = mount_root.joinpath(*parts).resolve()
    try:
        target.relative_to(mount_root.resolve())
    except ValueError as exc:
        raise ThemeError(f"EFI path escapes mounted volume: {efi_path}") from exc
    return target


def _load_theme_state(theme_source: Path) -> tuple[dict, Resolution]:
    try:
        state = json.loads(
            (theme_source / "install-state.json").read_text(encoding="utf-8")
        )
        resolution = parse_resolution(str(state["resolution"]))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ThemeError(f"invalid theme state: {exc}") from exc
    validate_theme(theme_source, resolution)
    return state, resolution


def apply_deployment(
    plan: DeploymentPlan,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    """Apply a validated deployment with file-level rollback."""
    theme_source = plan.theme_source.resolve()
    state, _ = _load_theme_state(theme_source)
    refind_dir = find_refind_dir(plan.refind_dir, ())
    roles = {target.role for target in plan.targets}
    if not roles.intersection({"win_dev", "win_game", "cachyos"}) or not plan.targets:
        raise ThemeError("deployment requires at least one assigned boot target")

    transaction = FileTransaction()
    mounted_by_us: list[Path] = []
    stage = "validation"
    try:
        resolved_targets: list[tuple[BootTarget, Path, Path]] = []
        for target in plan.targets:
            stage = f"mounting {target.role}"
            source_icon = _validate_source_icon(
                theme_source, target.source_icon
            )
            mount_root, mounted = ensure_volume_mounted(target, runner)
            if mounted:
                mounted_by_us.append(mount_root)
            loader_file = _efi_host_path(mount_root, target.loader_path)
            if not loader_file.is_file():
                raise ThemeError(
                    f"loader for {target.role} does not exist: {loader_file}"
                )
            resolved_targets.append((target, source_icon, mount_root))

        stage = "copying theme"
        deployed_theme = copy_owned_theme(
            theme_source, refind_dir, transaction
        )

        assignments: dict[str, dict[str, str]] = {}
        for target, source_icon, mount_root in resolved_targets:
            stage = f"copying {target.role} icon"
            icon_file = _efi_host_path(
                mount_root, icon_path_for_loader(target.loader_path)
            )
            permanent_backup = Path(str(icon_file) + ".ghoul-cyber.bak")
            transaction.copy_file(source_icon, icon_file, permanent_backup)
            if target.role == "cachyos":
                lts_kernel = _efi_host_path(mount_root, "\\vmlinuz-linux-cachyos-lts")
                if lts_kernel.is_file():
                    lts_icon = _efi_host_path(mount_root, "\\vmlinuz-linux-cachyos-lts.png")
                    lts_bak = Path(str(lts_icon) + ".ghoul-cyber.bak")
                    transaction.copy_file(source_icon, lts_icon, lts_bak)
            assignments[target.role] = {
                "partuuid": target.partuuid.casefold(),
                "loader_path": target.loader_path,
                "device": target.device,
                "icon_sha256": sha256_file(source_icon),
            }

        stage = "writing deployment state"
        deployed_state = dict(state)
        deployed_state["assignments"] = assignments
        transaction.write_bytes(
            deployed_theme / "install-state.json",
            (
                json.dumps(deployed_state, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
        )

        stage = "activating theme"
        config_path = refind_dir / "refind.conf"
        original_config = config_path.read_bytes()
        updated_config = update_managed_config(original_config)
        if updated_config != original_config:
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = refind_dir / (
                f"refind.conf.ghoul-cyber-{stamp}.bak"
            )
            transaction.write_bytes(
                config_path, updated_config, permanent_backup=backup_path
            )
        transaction.commit()
    except Exception as exc:
        try:
            transaction.rollback()
        except ThemeError as rollback_error:
            raise ThemeError(
                f"deployment failed during {stage}: {exc}; {rollback_error}"
            ) from exc
        if isinstance(exc, ThemeError):
            raise ThemeError(f"deployment failed during {stage}: {exc}") from exc
        raise ThemeError(f"deployment failed during {stage}: {exc}") from exc
    finally:
        for mount_point in reversed(mounted_by_us):
            result = runner(("umount", "--", str(mount_point)))
            if result.returncode != 0:
                print(
                    f"warning: could not unmount {mount_point}: "
                    f"{(result.stderr or result.stdout).strip()}",
                    file=sys.stderr,
                )
                continue
            try:
                mount_point.rmdir()
                mount_point.parent.rmdir()
            except OSError:
                pass


def _read_previous_assignments(theme_dir: Path) -> Mapping[str, object]:
    try:
        state = json.loads(
            (theme_dir / "install-state.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    assignments = state.get("assignments")
    return assignments if isinstance(assignments, Mapping) else {}


def _choose_dev_interactively(options: Sequence[BootEntry]) -> int:
    print("Nie można automatycznie odróżnić dwóch instalacji Windows.")
    print("Wybierz pozycję Windows 11 DEV:")
    for index, entry in enumerate(options, 1):
        details = " | ".join(
            value
            for value in (
                f"Boot{entry.bootnum}",
                entry.label,
                entry.device,
                entry.partuuid,
                entry.fs_label,
                entry.part_label,
                entry.size,
            )
            if value
        )
        print(f"  {index}. {details}")
    while True:
        try:
            raw = input(f"DEV [1-{len(options)}]: ").strip()
        except EOFError as exc:
            raise ThemeError("interactive DEV selection needs a terminal") from exc
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("Podaj numer widoczny na liście.")


def _refind_candidates(entries: Sequence[BootEntry]) -> tuple[Path, ...]:
    candidates: list[Path] = [
        Path("/boot/EFI/refind"),
        Path("/boot/efi/EFI/refind"),
        Path("/efi/EFI/refind"),
    ]
    for entry in entries:
        for mount_text in entry.mount_points:
            mount = Path(mount_text)
            candidates.append(mount / "EFI" / "refind")
            if "refind" in entry.loader_path.casefold():
                pure = PureWindowsPath(entry.loader_path)
                parent_parts = pure.parent.parts[1:]
                candidates.append(mount.joinpath(*parent_parts))
    return tuple(dict.fromkeys(candidates))


def _run_required(
    command: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    try:
        result = runner(tuple(command))
    except OSError as exc:
        raise ThemeError(f"cannot run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ThemeError(
            f"{command[0]} failed with exit {result.returncode}: {detail}"
        )
    return result.stdout


def run_linux_deploy(
    build: ThemeBuild,
    args,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    """Discover Linux boot targets and hand a validated plan to root."""
    if platform.system().casefold() != "linux":
        raise ThemeError("deployment is supported only on Linux")
    missing = missing_linux_dependencies()
    if missing:
        bootstrap_linux_dependencies(missing, runner)

    efi_text = _run_required(("efibootmgr", "-v"), runner)
    lsblk_text = _run_required(
        (
            "lsblk",
            "-J",
            "-b",
            "-o",
            "PATH,TYPE,PARTUUID,LABEL,PARTLABEL,SIZE,MOUNTPOINTS",
        ),
        runner,
    )
    devices_map = parse_lsblk(lsblk_text)
    entries = enrich_boot_entries(
        parse_efibootmgr(efi_text), devices_map
    )
    previous = _read_previous_assignments(build.output_dir)
    roles = assign_boot_roles(
        entries,
        choose_dev=(
            None if args.non_interactive else _choose_dev_interactively
        ),
        non_interactive=args.non_interactive,
        previous=previous,
        devices=devices_map,
    )
    refind_dir = find_refind_dir(
        args.refind_dir,
        _refind_candidates(entries) if args.refind_dir is None else (),
    )
    icons = {
        "win_dev": build.output_dir / "icons/os_win_dev.png",
        "win_game": build.output_dir / "icons/os_win_game.png",
        "cachyos": build.output_dir / "icons/os_cachyos.png",
    }
    targets = []
    seen_targets: set[tuple[str, str]] = set()
    for role in ("win_dev", "win_game", "cachyos"):
        entry = roles.get(role)
        if not entry:
            continue
        if not entry.device:
            raise ThemeError(
                f"lsblk did not map {role} PARTUUID {entry.partuuid} "
                "to a block device"
            )
        target_key = (entry.partuuid.casefold(), entry.loader_path.casefold())
        if target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        mounted = next(
            (Path(path) for path in entry.mount_points if Path(path).is_dir()),
            None,
        )
        targets.append(
            BootTarget(
                role=role,
                source_icon=icons[role],
                device=entry.device,
                partuuid=entry.partuuid,
                loader_path=entry.loader_path,
                mount_point=mounted,
            )
        )
    plan = DeploymentPlan(
        theme_source=build.output_dir,
        refind_dir=refind_dir,
        targets=tuple(targets),
        invoking_uid=getattr(os, "getuid", lambda: None)(),
        invoking_gid=getattr(os, "getgid", lambda: None)(),
    )
    if args.dry_run:
        print("Dry-run deployment mapping:")
        for target in plan.targets:
            print(
                f"  {target.role}: {target.partuuid} "
                f"{target.loader_path} ({target.device})"
            )
        print(f"  rEFInd: {plan.refind_dir}")
        return
    if getattr(os, "geteuid", lambda: 1)() == 0:
        apply_deployment(plan, runner=runner)
        return

    descriptor, raw_plan_path = tempfile.mkstemp(
        prefix="ghoul-cyber-plan-", suffix=".json"
    )
    os.close(descriptor)
    plan_path = Path(raw_plan_path)
    try:
        plan_path.write_text(
            deployment_plan_to_json(plan), encoding="utf-8", newline="\n"
        )
        command = ["sudo"]
        if args.non_interactive:
            command.append("-n")
        command.extend(
            (
                "--",
                sys.executable,
                str(Path(__file__).resolve()),
                "--_apply-plan",
                str(plan_path),
            )
        )
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise ThemeError(
                f"privileged deployment failed with exit {result.returncode}"
            )
    finally:
        if plan_path.exists():
            plan_path.unlink()


def _ensure_graphics_dependencies(font: Path | None = None) -> None:
    if PIL_IMPORT_ERROR is not None:
        if platform.system().casefold() != "linux":
            raise ThemeError(
                "Pillow is missing; install it with: python -m pip install Pillow"
            )
        bootstrap_linux_dependencies(("Pillow",))
        os.execv(sys.executable, [sys.executable, *sys.argv])

    if is_monospace_font_available(font):
        return
    if platform.system().casefold() != "linux":
        raise ThemeError(
            "no Unicode monospace TTF/OTF font found; install ttf-dejavu "
            "or pass --font"
        )
    bootstrap_linux_dependencies(("font",))
    if not is_monospace_font_available(font):
        raise ThemeError(
            "ttf-dejavu was installed but no usable monospace font is available; "
            "pass --font"
        )


def main(argv: Sequence[str] | None = None) -> int:
    script_dir = Path(__file__).resolve().parent
    parser = create_parser(script_dir)
    args = parser.parse_args(argv)
    try:
        if args._apply_plan is not None:
            payload = args._apply_plan.read_text(encoding="utf-8")
            apply_deployment(deployment_plan_from_json(payload))
            print("ghoul-cyber deployment completed")
            return 0

        _ensure_graphics_dependencies(args.font)

        overrides = HardwareOverrides(
            cpu=args.cpu,
            ram=args.ram,
            gpu=args.gpu,
            nvme=args.nvme,
            uefi_version=args.uefi_version,
            secure_boot=args.secure_boot,
        )
        hardware = detect_hardware(platform.system(), overrides)
        build = build_theme(
            args.source_dir,
            args.output_dir,
            args.resolution,
            hardware,
            args.font,
        )
        should_deploy = (
            platform.system().casefold() == "linux" and not args.build_only
        )
        if should_deploy:
            run_linux_deploy(build, args)
        print(f"ghoul-cyber ready: {build.output_dir}")
        return 0
    except (OSError, ThemeError, ValueError) as exc:
        print(f"ghoul-cyber: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
