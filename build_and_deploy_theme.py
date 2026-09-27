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
import colorsys
import dataclasses
import datetime as dt
import hashlib
import json
import math
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
# Alternative skins live in themes/<name>/ (art.* + theme.json). They only
# change the visuals; the theme is still installed as themes/ghoul-cyber.
SKINS_DIR = Path(__file__).resolve().parent / "themes"
DEFAULT_ACCENT = (255, 0, 60)
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
    "card_linux",  # generic Linux card -> icons/os_linux.png
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
# Icon geometry. Sized for a 3840x2160 OLED panel: rEFInd draws icons at
# exactly these pixel sizes, so the stock 128 px cards were fingernail-sized
# on 4K. Every source asset is >=1024 px, so nothing is upscaled.
# Dial these down (128 / 48 / 32) to return to the stock rEFInd geometry.
BIG_ICON_SIZE = 768
SMALL_ICON_SIZE = 240
SELECTION_SCALE = 1.125
BADGE_ICON_SIZE = BIG_ICON_SIZE // 4  # rEFInd draws drive badges at big/4
SELECTION_BIG_SIZE = round(BIG_ICON_SIZE * SELECTION_SCALE)
SELECTION_SMALL_SIZE = round(SMALL_ICON_SIZE * SELECTION_SCALE)
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
    "func_install", "tool_windows_rescue", "tool_apple_rescue",
)
BADGE_ICON_NAMES = (
    "vol_internal", "vol_external", "vol_optical", "vol_net", "vol_efi",
)

IMAGE_SIZES: dict[str, tuple[int, int]] = {}
OWNED_RELATIVE_PATHS: tuple[PurePosixPath, ...] = ()


def configure_geometry(big: int, small: int, selection_scale: float = 1.125) -> None:
    """Set the icon geometry every generator and validator uses.

    rEFInd draws icons at exactly these pixel sizes, so they are part of the
    build (and recorded in install-state.json for later validation).
    """
    global BIG_ICON_SIZE, SMALL_ICON_SIZE, SELECTION_SCALE, BADGE_ICON_SIZE
    global SELECTION_BIG_SIZE, SELECTION_SMALL_SIZE, IMAGE_SIZES, OWNED_RELATIVE_PATHS
    BIG_ICON_SIZE, SMALL_ICON_SIZE, SELECTION_SCALE = int(big), int(small), float(selection_scale)
    BADGE_ICON_SIZE = max(16, BIG_ICON_SIZE // 4)
    SELECTION_BIG_SIZE = round(BIG_ICON_SIZE * SELECTION_SCALE)
    SELECTION_SMALL_SIZE = round(SMALL_ICON_SIZE * SELECTION_SCALE)
    IMAGE_SIZES = {
        "background.png": (0, 0),
        "selection_big.png": (SELECTION_BIG_SIZE, SELECTION_BIG_SIZE),
        "selection_small.png": (SELECTION_SMALL_SIZE, SELECTION_SMALL_SIZE),
        **{f"icons/{n}.png": (BIG_ICON_SIZE, BIG_ICON_SIZE) for n in OS_ICON_NAMES},
        **{f"icons/{n}.png": (SMALL_ICON_SIZE, SMALL_ICON_SIZE) for n in TOOL_ICON_NAMES},
        **{f"icons/{n}.png": (BADGE_ICON_SIZE, BADGE_ICON_SIZE) for n in BADGE_ICON_NAMES},
    }
    OWNED_RELATIVE_PATHS = tuple(
        PurePosixPath(path)
        for path in (*IMAGE_SIZES, "theme.conf", "install-state.json")
    )


configure_geometry(BIG_ICON_SIZE, SMALL_ICON_SIZE, SELECTION_SCALE)
MANAGED_BEGIN = "# BEGIN ghoul-cyber managed theme"
MANAGED_INCLUDE = "include themes/ghoul-cyber/theme.conf"
MANAGED_END = "# END ghoul-cyber managed theme"
@dataclass(frozen=True)
class PackageManager:
    install: tuple[str, ...]
    refresh: tuple[str, ...] | None   # run once, then retry, if install fails
    names: Mapping[str, str | None]  # what we need -> package name (None = not packaged)


# Checked against each distribution's repositories (2026-09).
LINUX_PACKAGE_MANAGERS: dict[str, PackageManager] = {
    "pacman": PackageManager(  # Arch, CachyOS, EndeavourOS, Manjaro
        ("pacman", "-S", "--needed", "--noconfirm"), ("pacman", "-Sy", "--needed", "--noconfirm"),
        {"Pillow": "python-pillow", "efibootmgr": "efibootmgr", "lsblk": "util-linux",
         "findmnt": "util-linux", "font": "ttf-dejavu", "refind": "refind"}),
    "apt-get": PackageManager(  # Debian, Ubuntu, Mint, Pop!_OS
        ("apt-get", "install", "-y"), ("apt-get", "update"),
        {"Pillow": "python3-pil", "efibootmgr": "efibootmgr", "lsblk": "util-linux",
         "findmnt": "util-linux", "font": "fonts-dejavu-core", "refind": "refind"}),
    "dnf": PackageManager(  # Fedora, Nobara, RHEL clones
        ("dnf", "install", "-y"), ("dnf", "makecache"),
        {"Pillow": "python3-pillow", "efibootmgr": "efibootmgr", "lsblk": "util-linux",
         "findmnt": "util-linux", "font": "dejavu-sans-mono-fonts", "refind": "rEFInd"}),
    "zypper": PackageManager(  # openSUSE (no rEFInd in the official repositories)
        ("zypper", "--non-interactive", "install"), ("zypper", "--non-interactive", "refresh"),
        {"Pillow": "python3-Pillow", "efibootmgr": "efibootmgr", "lsblk": "util-linux",
         "findmnt": "util-linux", "font": "dejavu-fonts", "refind": None}),
    "xbps-install": PackageManager(  # Void
        ("xbps-install", "-y"), ("xbps-install", "-S"),
        {"Pillow": "python3-Pillow", "efibootmgr": "efibootmgr", "lsblk": "util-linux",
         "findmnt": "util-linux", "font": "dejavu-fonts-ttf", "refind": "refind"}),
    "apk": PackageManager(  # Alpine
        ("apk", "add"), ("apk", "update"),
        {"Pillow": "py3-pillow", "efibootmgr": "efibootmgr", "lsblk": "lsblk",
         "findmnt": "findmnt", "font": "font-dejavu", "refind": "refind"}),
}
PACMAN_PACKAGES = LINUX_PACKAGE_MANAGERS["pacman"].names
REFIND_DOWNLOAD = "https://www.rodsbooks.com/refind/getting.html"
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
    tools: tuple[tuple[str, str], ...] = ()   # (source .efi, name in ESP/EFI/tools)


@dataclass(frozen=True)
class ThemeBuild:
    output_dir: Path
    resolution: Resolution
    files: tuple[Path, ...]


@dataclass(frozen=True)
class Skin:
    """A visual variant: AI artwork, accent color and HUD strings."""

    name: str
    art: Path
    accent: tuple[int, int, int]
    title: str
    kanji: str
    tagline: str
    art_brightness: float = 1.0


def parse_hex_color(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(value).strip())
    if not match:
        raise ThemeError(f"invalid color (expected #RRGGBB): {value}")
    digits = match.group(1)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def list_skins(skins_dir: Path = SKINS_DIR) -> list[str]:
    if not skins_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in skins_dir.iterdir()
        if (path / "theme.json").is_file()
    )


def load_skin(name: str, skins_dir: Path = SKINS_DIR) -> Skin:
    """Load themes/<name>/theme.json and its art.png/art.jpg."""
    folder = skins_dir / name
    config_path = folder / "theme.json"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or not config_path.is_file():
        available = ", ".join([THEME_NAME, *list_skins(skins_dir)])
        raise ThemeError(f"unknown theme '{name}'; available: {available}")
    config = read_json_file(config_path, "theme settings")
    if not isinstance(config, Mapping):
        raise ThemeError(f"{config_path}: must be a JSON object")
    art = next(
        (
            folder / f"art{suffix}"
            for suffix in (".png", ".jpg", ".jpeg")
            if (folder / f"art{suffix}").is_file()
        ),
        None,
    )
    if art is None:
        raise ThemeError(f"{name}: missing art.png/art.jpg in {folder}")
    return Skin(
        name=name,
        art=art,
        accent=parse_hex_color(config.get("accent", "#FF003C")),
        title=str(config.get("title", name.upper().replace("-", "_"))),
        kanji=str(config.get("kanji", "")),
        tagline=str(config.get("tagline", "")),
        art_brightness=float(config.get("art_brightness", 1.0)),
    )


# --- Customisation: one schema drives validation, theme.conf, rendering and
# the Theme Studio form. Add an option here and every layer picks it up. ---

# In order of importance: rEFInd shows them in this order and refind.max_tools
# keeps the first ones.
REFIND_TOOLS = (
    "firmware", "reboot", "shutdown", "shell", "memtest", "about", "bootorder",
    "hidden_tags", "fwupdate", "install", "mok_tool", "gdisk", "gptsync", "netboot",
    "apple_recovery", "windows_recovery", "csr_rotate", "exit",
)
# "arrows" is driven by layout.scroll_arrows instead.
REFIND_HIDEUI = (
    "banner", "label", "singleuser", "safemode", "hwtest", "hints", "editor", "badges",
)
TILE_XSPACING = 8  # rEFInd's gap between tiles (menu.c)
REFIND_SCANFOR = (
    "internal", "external", "optical", "netboot", "manual", "firmware",
    "hdbios", "biosexternal", "cd",
)
DEFAULT_CONFIG_NAME = "boot-config.json"
HARDWARE_LINES = ("uefi", "cpu", "ram", "gpu", "nvme")
ENTRY_CARDS = {
    "cachyos": "os_cachyos", "win_dev": "os_win_dev", "win_game": "os_win_game",
    "windows": "os_win", "linux": "os_linux", "arch": "os_arch",
    "ubuntu": "os_ubuntu", "debian": "os_debian", "fedora": "os_fedora",
    "mac": "os_mac", "other": "os_unknown",
}
# Cards that carry an index number, in the author's default order.
NUMBERED_CARDS = ("win_dev", "win_game", "cachyos", "linux", "windows", "arch")
CARD_LABELS = {
    "win_dev": "Windows DEV", "win_game": "Windows GAMING", "cachyos": "CachyOS",
    "linux": "Linux", "windows": "Windows", "arch": "Arch Linux",
}
# Card asset stem -> card key (the painted cards whose number gets replaced).
CARD_STEMS = {
    "selection_item_windev": "win_dev", "selection_item_wingame": "win_game",
    "selection_item_linux": "cachyos", "card_linux": "linux",
}


@dataclass(frozen=True)
class OptionSpec:
    key: str            # "section.name"
    kind: str           # bool | int | float | choice | multi | order | text | lines | color | entries
    default: object
    group: str          # Theme Studio tab
    label: str          # Polish label shown in Theme Studio
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    max_len: int = 80


OPTION_SPECS: tuple[OptionSpec, ...] = (
    # Układ
    OptionSpec("layout.resolution", "choice", "3840x2160", "Układ", "Rozdzielczość ekranu",
               "Natywna rozdzielczość monitora. Tło i rozmiary ikon dopasują się same.",
               choices=("3840x2160", "2560x1440", "1920x1080", "1600x900", "1280x720")),
    OptionSpec("layout.icon_size", "int", 0, "Układ", "Rozmiar kafelków systemów (px)",
               "0 = automatycznie (768 px w 4K, 384 px w 1080p).", 0, 1024),
    OptionSpec("layout.tool_size", "int", 0, "Układ", "Rozmiar ikon narzędzi (px)",
               "0 = automatycznie (240 px w 4K).", 0, 512),
    OptionSpec("layout.visible_tiles", "int", 0, "Układ", "Ile kafelków systemów widać naraz",
               "0 = automatycznie z rozmiaru kafelków (w 4K: 3). Liczba > 0 dobiera rozmiar kafelków tak, "
               "żeby tyle się zmieściło; pozostałe systemy przewijają się o jeden. 1 kafelek tylko do 1440p.",
               0, 8),
    OptionSpec("layout.scroll_arrows", "bool", False, "Układ", "Strzałki przewijania",
               "Strzałki po bokach rzędu systemów, gdy nie wszystkie się mieszczą."),
    OptionSpec("layout.selection_scale", "float", 1.125, "Układ", "Wielkość ramki zaznaczenia",
               "Ramka względem kafelka: 1.0 = tuż przy krawędzi.", 1.0, 1.5),
    OptionSpec("layout.art_scale", "float", 0.84, "Układ", "Skala grafiki w rogach",
               "Dotyczy motywów z grafiką AI. Mniej = więcej czarnego tła.", 0.5, 1.0),
    OptionSpec("layout.art_brightness", "float", 0.0, "Układ", "Jasność grafiki",
               "0 = wartość z motywu. 1.0 = oryginał, mniej = ciemniej.", 0.0, 1.5),
    OptionSpec("layout.ui_dim", "float", 1.0, "Układ", "Przyciemnianie pod interfejsem",
               "Jak mocno przyciemnić grafikę pod kafelkami i tekstem (0 = wcale).", 0.0, 1.0),
    # Elementy
    OptionSpec("hud.accent", "color", "", "Elementy", "Kolor akcentu",
               "#RRGGBB. Puste = kolor motywu. Przekolorowuje ramkę, ikony i HUD."),
    OptionSpec("hud.title", "bool", True, "Elementy", "Tytuł w lewym górnym rogu"),
    OptionSpec("hud.title_text", "text", "", "Elementy", "Własny tytuł",
               "Puste = tytuł motywu, np. CURSED_DOMAIN_v1.0.", max_len=40),
    OptionSpec("hud.tagline", "bool", True, "Elementy", "Hasło w prawym górnym rogu"),
    OptionSpec("hud.tagline_text", "text", "", "Elementy", "Własne hasło", max_len=40),
    OptionSpec("hud.kanji", "bool", True, "Elementy", "Pionowa kolumna znaków"),
    OptionSpec("hud.kanji_text", "text", "", "Elementy", "Własne znaki (do 5)", max_len=5),
    OptionSpec("hud.hardware", "bool", True, "Elementy", "Informacje o sprzęcie"),
    OptionSpec("hud.hardware_lines", "multi", HARDWARE_LINES, "Elementy", "Które wiersze sprzętu",
               choices=HARDWARE_LINES),
    OptionSpec("hud.custom_lines", "lines", (), "Elementy", "Własne wiersze pod sprzętem",
               "Do 4 wierszy, np. imię, hostname, motto.", max_len=60),
    OptionSpec("hud.status_line", "bool", True, "Elementy", "Wiersz statusu z kursorem"),
    OptionSpec("hud.status_text", "text", "INIT_CORE_v2.6...", "Elementy", "Tekst statusu", max_len=40),
    OptionSpec("hud.decorations", "bool", True, "Elementy", "Ozdobniki HUD (linijki, narożniki)"),
    OptionSpec("hud.nav_bar", "bool", True, "Elementy", "Pasek podpowiedzi klawiszy na dole"),
    OptionSpec("hud.scanlines", "bool", True, "Elementy", "Linie skanowania (efekt CRT)"),
    OptionSpec("hud.glitch", "bool", True, "Elementy", "Paski glitch"),
    OptionSpec("hud.ghoul_overlay", "bool", True, "Elementy", "Oryginalna nakładka Ghoul Cyber",
               "Tylko motyw ghoul-cyber. Wyłączona = HUD rysowany jak w innych motywach."),
    OptionSpec("cards.numbers", "bool", True, "Elementy", "Numery na kafelkach systemów",
               "01, 02, ... w lewym dolnym rogu kafelka. Wyłączone = kafelki bez numerów."),
    OptionSpec("cards.order", "order", (), "Elementy", "Kolejność numerów",
               "Puste = automatycznie: najpierw Twoje wpisy menu, potem systemy wykryte na tym "
               "komputerze. Kafelki spoza listy nie dostaną numeru.", choices=NUMBERED_CARDS),
    # Zachowanie
    OptionSpec("refind.timeout", "int", 10, "Zachowanie", "Czas do automatycznego startu (s)",
               "0 = czekaj bez końca, -1 = startuj od razu domyślny system.", -1, 600),
    OptionSpec("refind.default_selection", "text", "", "Zachowanie", "Domyślny system",
               "Fragment nazwy wpisu (np. CachyOS) albo + = ostatnio uruchomiony. Puste = pierwszy.",
               max_len=40),
    OptionSpec("refind.showtools", "multi",
               ("firmware", "reboot", "shutdown", "shell", "memtest", "gdisk", "gptsync",
                "netboot", "mok_tool", "fwupdate", "apple_recovery", "windows_recovery",
                "csr_rotate", "install", "about", "bootorder", "hidden_tags"),
               "Zachowanie", "Narzędzia w dolnym rzędzie",
               "rEFInd pokaże tylko te, które są naprawdę dostępne.", choices=REFIND_TOOLS),
    OptionSpec("refind.max_tools", "int", 0, "Zachowanie", "Ile narzędzi w dolnym rzędzie",
               "0 = wszystkie dostępne. Liczone w kolejności ważności: BIOS, restart, wyłączenie, "
               "Shell, MemTest, informacje, kolejność rozruchu, ukryte wpisy, reszta.", 0, len(REFIND_TOOLS)),
    OptionSpec("refind.hideui", "multi", ("hints", "badges", "label"), "Zachowanie",
               "Ukryj elementy rEFInd", choices=REFIND_HIDEUI),
    OptionSpec("refind.scanfor", "multi", (), "Zachowanie", "Gdzie szukać systemów",
               "Puste = domyślnie rEFInd (internal, external, optical, manual).",
               choices=REFIND_SCANFOR),
    OptionSpec("refind.extra_tools", "multi", ("shell", "memtest"), "Zachowanie",
               "Doinstaluj narzędzia rEFInd",
               "EFI Shell (Arch/CachyOS, Debian/Ubuntu) i test pamięci MemTest86+ (Arch, "
               "Debian/Ubuntu) z pakietów dystrybucji, kopiowane do EFI/tools. Pojawią się w dolnym rzędzie.",
               choices=("shell", "memtest")),
    OptionSpec("refind.enable_mouse", "bool", False, "Zachowanie", "Obsługa myszy"),
    OptionSpec("refind.enable_touch", "bool", False, "Zachowanie", "Obsługa ekranu dotykowego"),
    OptionSpec("refind.dont_scan_dirs", "text", "EFI/refind,EFI/BOOT", "Zachowanie",
               "Pomijane katalogi", "Po przecinku.", max_len=200),
    OptionSpec("refind.dont_scan_files", "text", "refind_x64.efi,BOOTX64.EFI,bootx64.efi",
               "Zachowanie", "Pomijane pliki", "Po przecinku.", max_len=200),
    OptionSpec("refind.max_tags", "int", 0, "Zachowanie", "Maks. liczba systemów w menu",
               "0 = bez limitu.", 0, 30),
    # Wpisy
    OptionSpec("entries", "entries", (), "Wpisy menu", "Własne wpisy menu",
               "Ręczne wpisy rEFInd, np. drugi Windows na innym dysku."),
)
OPTION_BY_KEY = {spec.key: spec for spec in OPTION_SPECS}
_SAFE_TEXT = re.compile(r"[^\"\\{}\x00-\x1f\x7f\ud800-\udfff]*")  # no quotes, braces, control chars
_EFI_PATH = re.compile(r"[\\/][A-Za-z0-9_.\-\\/ ]{1,200}")
_VOLUME = re.compile(r"[A-Za-z0-9 _.\-]{1,64}")


def default_options() -> dict:
    return {
        spec.key: tuple(c for c in spec.choices if c in spec.default) if spec.kind == "multi"
        else spec.default
        for spec in OPTION_SPECS
    }


def _flatten(raw: Mapping, prefix: str = "") -> dict:
    flat: dict = {}
    for key, value in raw.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping) and full not in OPTION_BY_KEY:
            flat.update(_flatten(value, f"{full}."))
        else:
            flat[full] = value
    return flat


def nest_options(flat: Mapping) -> dict:
    """Turn {"hud.title": x} back into {"hud": {"title": x}} for saving."""
    nested: dict = {}
    for key, value in flat.items():
        node = nested
        *parents, leaf = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = list(value) if isinstance(value, tuple) else value
    return nested


def _check_entry(index: int, entry: object, errors: list[str]) -> dict | None:
    where = f"entries[{index}]"
    before = len(errors)
    if not isinstance(entry, Mapping):
        errors.append(f"{where}: must be an object")
        return None
    label = str(entry.get("label", "")).strip()
    card = str(entry.get("card", "other"))
    loader = str(entry.get("loader", "")).strip()
    volume = str(entry.get("volume", "")).strip()
    options = str(entry.get("options", "")).strip()
    if not label or len(label) > 40 or not _SAFE_TEXT.fullmatch(label):
        errors.append(f"{where}.label: 1-40 characters, no quotes or braces")
    if card not in ENTRY_CARDS:
        errors.append(f"{where}.card: one of {', '.join(ENTRY_CARDS)}")
    if not _EFI_PATH.fullmatch(loader) or ".." in loader or re.search(r"[\\/]{2}", loader):
        errors.append(f"{where}.loader: EFI path like \\EFI\\Microsoft\\Boot\\bootmgfw.efi")
    if volume and not _VOLUME.fullmatch(volume):
        errors.append(f"{where}.volume: partition GUID or label (letters, digits, - _ .)")
    if options and (len(options) > 200 or not _SAFE_TEXT.fullmatch(options)):
        errors.append(f"{where}.options: up to 200 characters, no quotes or braces")
    if len(errors) > before:
        return None  # an invalid entry is dropped, never written to theme.conf
    return {"label": label, "card": card, "loader": loader, "volume": volume,
            "options": options, "disabled": bool(entry.get("disabled", False))}


def validate_options(raw: Mapping | None) -> tuple[dict, list[str], list[str]]:
    """Validate user options against OPTION_SPECS.

    Returns (options, errors, warnings). Invalid values are reported and
    replaced by their defaults, so the result is always safe to build with.
    """
    options = default_options()
    errors: list[str] = []
    warnings: list[str] = []
    if raw is None:
        return options, errors, warnings
    if not isinstance(raw, Mapping):
        return options, ["configuration root must be a JSON object"], warnings
    for key, value in _flatten(raw).items():
        if key.startswith("_") or key in {"version", "theme"}:
            continue
        spec = OPTION_BY_KEY.get(key)
        if spec is None:
            warnings.append(f"{key}: unknown option, ignored")
            continue
        problem = None
        try:
            if spec.kind == "bool":
                if not isinstance(value, bool):
                    raise ValueError("must be true or false")
            elif spec.kind in {"int", "float"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or (
                        isinstance(value, float) and not math.isfinite(value)):
                    raise ValueError("must be a number")
                value = int(value) if spec.kind == "int" else float(value)
                if spec.minimum is not None and value < spec.minimum or (
                    spec.maximum is not None and value > spec.maximum
                ):
                    raise ValueError(f"must be between {spec.minimum:g} and {spec.maximum:g}")
            elif spec.kind == "choice":
                if value not in spec.choices:
                    raise ValueError(f"must be one of {', '.join(spec.choices)}")
            elif spec.kind == "multi":
                if key == "refind.hideui" and isinstance(value, (list, tuple)) and "arrows" in value:
                    value = [v for v in value if v != "arrows"]   # now layout.scroll_arrows
                if not isinstance(value, (list, tuple)) or not all(v in spec.choices for v in value):
                    raise ValueError(f"must be a list with items from: {', '.join(spec.choices)}")
                value = tuple(c for c in spec.choices if c in value)  # canonical order, like Studio
            elif spec.kind == "order":
                if (not isinstance(value, (list, tuple)) or not all(v in spec.choices for v in value)
                        or len(set(value)) != len(value)):
                    raise ValueError(f"must be a list of distinct items from: {', '.join(spec.choices)}")
                value = tuple(value)
            elif spec.kind == "text":
                if not isinstance(value, str) or len(value) > spec.max_len or not _SAFE_TEXT.fullmatch(value):
                    raise ValueError(f"text up to {spec.max_len} characters, no quotes or braces")
            elif spec.kind == "lines":
                if not isinstance(value, (list, tuple)) or len(value) > 4 or not all(
                    isinstance(v, str) and len(v) <= spec.max_len and _SAFE_TEXT.fullmatch(v)
                    for v in value
                ):
                    raise ValueError(f"up to 4 lines of {spec.max_len} characters")
                value = tuple(value)
            elif spec.kind == "color":
                if value:
                    parse_hex_color(value)
            elif spec.kind == "entries":
                if not isinstance(value, (list, tuple)) or len(value) > 16:
                    raise ValueError("must be a list of up to 16 entries")
                checked = [_check_entry(i, e, errors) for i, e in enumerate(value)]
                value = tuple(e for e in checked if e is not None)
        except (ValueError, ThemeError) as exc:
            problem = str(exc)
        if problem:
            errors.append(f"{key}: {problem}")
        else:
            options[key] = value
    return options, errors, warnings


MAX_CONFIG_BYTES = 1_000_000


def read_json_file(path: Path, what: str = "configuration"):
    """Parse a small JSON file; every failure becomes a readable ThemeError.

    Accepts a UTF-8 BOM (Windows Notepad) and refuses huge or deeply nested
    files instead of exhausting memory or the stack.
    """
    try:
        path = Path(path)
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ThemeError(f"{what} {path} is larger than {MAX_CONFIG_BYTES // 1000} kB")
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError as exc:
        raise ThemeError(f"{what} not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ThemeError(f"{what} {path} is not UTF-8 text") from exc
    except RecursionError as exc:
        raise ThemeError(f"{what} {path} is nested too deeply") from exc
    except (OSError, ValueError) as exc:
        raise ThemeError(f"cannot read {what} {path}: {exc}") from exc


def load_options(path: Path | None, *, strict: bool = True) -> dict:
    """Read a boot-config.json; with strict=True any error aborts the build."""
    if path is None:
        return default_options()
    raw = read_json_file(path)
    options, errors, warnings = validate_options(raw)
    for warning in warnings:
        print(f"warning: {path.name}: {warning}", file=sys.stderr)
    if errors and strict:
        raise ThemeError(
            f"invalid configuration {path}:\n  - " + "\n  - ".join(errors)
        )
    return options


def save_options(options: Mapping, path: Path, *, theme: str | None = None) -> None:
    """Write only non-default options, atomically, keeping the file readable."""
    defaults = default_options()

    def differs(key: str, value: object) -> bool:
        if OPTION_BY_KEY[key].kind == "multi":  # order of ticked boxes is irrelevant
            return set(value) != set(defaults[key])
        return value != defaults[key]

    changed = {k: v for k, v in options.items() if k in defaults and differs(k, v)}
    payload = {"version": 1, **({"theme": theme} if theme else {}), **nest_options(changed)}
    path = Path(path)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def icon_geometry(options: Mapping, resolution: Resolution) -> tuple[int, int]:
    """Big/small icon sizes: explicit options, else scaled from 4K."""
    scale = resolution.height / 2160
    big = int(options.get("layout.icon_size") or max(64, round(768 * scale / 8) * 8))
    visible = int(options.get("layout.visible_tiles") or 0)
    if visible:
        # rEFInd shows width // (big + 8) - 1 tiles in the OS row (menu.c InitScroll)
        big = max(64, min(1024, resolution.width // (visible + 1) - TILE_XSPACING))
    small = int(options.get("layout.tool_size") or max(32, round(240 * scale / 8) * 8))
    return big, small


def shown_tools(options: Mapping) -> tuple[str, ...]:
    """Enabled tools in order of importance, cut to refind.max_tools (0 = all)."""
    tools = tuple(t for t in REFIND_TOOLS if t in options["refind.showtools"])
    limit = options["refind.max_tools"]
    return tools[:limit] if limit else tools


def visible_tiles(options: Mapping, resolution: Resolution) -> int:
    """How many OS tiles rEFInd shows at once (the rest scroll)."""
    big, _ = icon_geometry(options, resolution)
    return max(1, resolution.width // (big + TILE_XSPACING) - 1)


def render_theme_conf(options: Mapping, resolution: Resolution) -> str:
    """Generate themes/ghoul-cyber/theme.conf from validated options."""
    base = "themes/ghoul-cyber"
    lines = [
        f"banner {base}/background.png",
        "banner_scale fillscreen",
        "",
        f"selection_big {base}/selection_big.png",
        f"selection_small {base}/selection_small.png",
        "",
        f"big_icon_size {BIG_ICON_SIZE}",
        f"small_icon_size {SMALL_ICON_SIZE}",
        "",
        f"icons_dir {base}/icons",
        "",
    ]
    hideui = list(options["refind.hideui"])
    if not options["layout.scroll_arrows"]:
        hideui.append("arrows")
    if hideui:
        lines.append("hideui " + ",".join(hideui))
    for key in ("dont_scan_dirs", "dont_scan_files"):
        value = ",".join(p.strip() for p in options[f"refind.{key}"].split(",") if p.strip())
        if value:
            lines.append(f"{key} {value}")
    lines.append('dont_scan_firmware "Shell", "EFI Internal Shell"')
    tools = shown_tools(options)
    if tools:
        lines.append("showtools " + ", ".join(tools))
    if options["refind.scanfor"]:
        lines.append("scanfor " + ",".join(options["refind.scanfor"]))
    if options["refind.max_tags"]:
        lines.append(f"max_tags {options['refind.max_tags']}")
    if options["refind.enable_mouse"]:
        lines.append("enable_mouse")
    if options["refind.enable_touch"]:
        lines.append("enable_touch")
    lines += ["", f"resolution {resolution.width} {resolution.height}",
              f"timeout {options['refind.timeout']}"]
    if options["refind.default_selection"]:
        lines.append(f'default_selection "{options["refind.default_selection"]}"')
    for entry in options["entries"]:
        lines += ["", f'menuentry "{entry["label"]}" {{',
                  f"    icon /EFI/refind/{base}/icons/{ENTRY_CARDS[entry['card']]}.png"]
        if entry["volume"]:
            lines.append(f'    volume "{entry["volume"]}"')
        lines.append(f"    loader {entry['loader']}")
        if entry["options"]:
            lines.append(f'    options "{entry["options"]}"')
        if entry["disabled"]:
            lines.append("    disabled")
        lines.append("}")
    return "\n".join(lines) + "\n"


def parse_resolution(value: str) -> Resolution:
    """Parse and validate a 16:9 WIDTHxHEIGHT resolution."""
    match = re.fullmatch(r"([1-9]\d{2,4})[xX]([1-9]\d{2,4})", value.strip())
    if not match:
        raise ValueError("resolution must use WIDTHxHEIGHT")
    width, height = (int(part) for part in match.groups())
    if width * 9 != height * 16:
        raise ValueError("resolution must have a 16:9 aspect ratio")
    if not 640 <= width <= 7680:
        raise ValueError("resolution must be between 640x360 and 7680x4320")
    return Resolution(width, height)


def create_parser(script_dir: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=Resolution(3840, 2160),
        help="target 16:9 resolution (default: 3840x2160)",
    )
    parser.add_argument(
        "--theme",
        default=THEME_NAME,
        help=f"visual theme from themes/ (default: {THEME_NAME})",
    )
    parser.add_argument(
        "--list-themes", action="store_true", help="print available themes"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"customisation file (default: {DEFAULT_CONFIG_NAME} next to this script, if present)",
    )
    parser.add_argument(
        "--no-config", action="store_true", help="ignore any customisation file"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate the customisation file, print the generated theme.conf and exit",
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
    parser.add_argument(
        "--install-refind",
        action="store_true",
        help="Linux: install rEFInd (package + refind-install) without asking if it is missing",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Windows: also install the built theme into rEFInd on the EFI partition (asks for UAC)",
    )
    parser.add_argument("--_apply-plan", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_windows-install", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_log", type=Path, help=argparse.SUPPRESS)
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


def _frame_bbox(img) -> tuple[int, int, int, int] | None:
    """Bounding box of a card's frame: rows/columns that stay bright for a long
    stretch (frame lines, separators). Scattered noise never qualifies."""
    rgba = img.convert("RGBA")
    luminance = rgba.convert("L").point(lambda v: 255 if v > 90 else 0)
    opaque = rgba.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    bright = ImageChops.multiply(luminance, opaque)
    rows = list(bright.resize((1, bright.height), Image.Resampling.BOX).tobytes())
    cols = list(bright.resize((bright.width, 1), Image.Resampling.BOX).tobytes())
    line_rows = [y for y, v in enumerate(rows) if v >= 255 * 0.25]
    line_cols = [x for x, v in enumerate(cols) if v >= 255 * 0.25]
    if len(line_rows) >= 2 and len(line_cols) >= 2:
        return (line_cols[0], line_rows[0], line_cols[-1] + 1, line_rows[-1] + 1)
    return bright.getbbox()


# One frame for every tool tile, drawn by the builder so all of them match to the
# pixel: thin outline, thick corner brackets and thin inner corners (the look of
# bios.png). Fractions of the tile size.
TOOL_FRAME = {"inset": 0.03, "line": 0.005, "bracket": 0.018, "bracket_len": 0.11,
              "inner_gap": 0.026, "inner_len": 0.075, "band": 0.07, "radius": 0.025}
TOOL_CARD_FILL = (5, 5, 7, 255)
TOOL_FRAME_COLOR = (236, 236, 236, 255)


def tool_card(image, size: int):
    """Re-frame a tool icon: crop to its card, drop the artwork's own frame and
    draw the shared TOOL_FRAME, so every tool tile is identical except its glyph."""
    _require_pillow()
    art = image.convert("RGBA")
    box = _frame_bbox(art)
    if box and box[2] - box[0] > art.width * 0.5 and box[3] - box[1] > art.height * 0.5:
        art = art.crop(box)
    work = size * 4
    f = {key: max(1, round(work * value)) for key, value in TOOL_FRAME.items()}
    body = Image.new("RGBA", (work, work), TOOL_CARD_FILL)
    body.alpha_composite(art.resize((work, work), Image.Resampling.LANCZOS))
    draw = ImageDraw.Draw(body)
    band = f["band"]
    for rect in ((0, 0, work, band), (0, work - band, work, work), (0, 0, band, work), (work - band, 0, work, work)):
        draw.rectangle(rect, fill=TOOL_CARD_FILL)   # the artwork's own frame goes away
    i, last = f["inset"], work - 1 - f["inset"]
    draw.rectangle((i, i, last, last), outline=TOOL_FRAME_COLOR, width=f["line"])
    t, length, gap, inner = f["bracket"], f["bracket_len"], f["inner_gap"], f["inner_len"]
    for x, y, sx, sy in ((i, i, 1, 1), (last, i, -1, 1), (i, last, 1, -1), (last, last, -1, -1)):
        def rect(x0, y0, x1, y1):
            draw.rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill=TOOL_FRAME_COLOR)
        rect(x, y, x + sx * length, y + sy * t)                # thick corner bracket
        rect(x, y, x + sx * t, y + sy * length)
        gx, gy = x + sx * gap, y + sy * gap                    # thin inner corner
        rect(gx, gy, gx + sx * inner, gy + sy * f["line"])
        rect(gx, gy, gx + sx * f["line"], gy + sy * inner)
    mask = Image.new("L", (work, work), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, work - 1, work - 1), radius=f["radius"], fill=255)
    card = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    card.paste(body, (0, 0), mask)
    return card.resize((size, size), Image.Resampling.LANCZOS)


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

    # Crop to the card itself - its bright frame, glyph and label - so every tool
    # fills the tile like bios.png and power.png. The alpha bbox is not enough:
    # on dark artwork the flood fill leaks into the card body and leaves stray
    # pixels at the edges, which kept some cards small and see-through.
    bbox = _frame_bbox(img) or img.getbbox()
    if bbox:
        bx0, by0, bx1, by1 = bbox
        max_d = max(bx1 - bx0, by1 - by0)
        cx = (bx0 + bx1) // 2
        cy = (by0 + by1) // 2
        half = max_d // 2
        img = img.crop((cx - half, cy - half, cx + half, cy + half))
    # a solid card body, like the painted cards (the flood fill may have eaten it)
    card = Image.new("RGBA", img.size, (5, 5, 7, 255))
    card.alpha_composite(img)
    return card.resize((size, size), Image.Resampling.LANCZOS)


def recolor_accent(image, accent: tuple[int, int, int]):
    """Shift the theme's signature red (#FF003C family) to another accent hue.

    Only strongly saturated red pixels move, so white linework, grey HUD
    detail and alpha stay untouched.
    """
    _require_pillow()
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    hue, sat, val = rgb.convert("HSV").split()
    target_h, target_s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in accent))
    red = hue.point(lambda h: 255 if h <= 14 or h >= 236 else 0)
    saturated = sat.point(lambda s: 255 if s >= 70 else 0)
    mask = ImageChops.multiply(red, saturated)
    shifted = Image.merge(
        "HSV",
        (
            Image.new("L", rgb.size, round(target_h * 255) % 256),
            sat.point(lambda s: round(s * target_s)),
            val,
        ),
    ).convert("RGB")
    result = Image.composite(shifted, rgb, mask).convert("RGBA")
    result.putalpha(alpha)
    return result


SKIN_ART_SCALE = 0.84
# The original theme's HUD texts, used when its baked overlay is switched off.
GHOUL_HUD = Skin(
    name=THEME_NAME, art=Path("background.png"), accent=DEFAULT_ACCENT,
    title="GHOUL_CORE_v2.6", kanji="死神核", tagline="[ 1000 - 7 = ??? ]",
)


def _pin_art_to_corners(base, scale: float = SKIN_ART_SCALE):
    """Shrink a skin's two corner pieces toward their own corners.

    Skin art has one piece top-right and one bottom-left with black between,
    so each half is scaled separately: the right half stays pinned to the
    top-right corner and the left half to the bottom-left one.
    """
    width, height = base.size
    half = width // 2
    size = (round(half * scale), round(height * scale))
    left = base.crop((0, 0, half, height)).resize(size, Image.Resampling.LANCZOS)
    right = base.crop((half, 0, width, height)).resize(size, Image.Resampling.LANCZOS)
    pinned = Image.new("RGBA", base.size, (0, 0, 0, 255))
    pinned.alpha_composite(left, (0, height - size[1]))
    pinned.alpha_composite(right, (width - size[0], 0))
    return pinned


def _darken_ui_zones(base, strength: float = 1.0):
    """Dim a skin's artwork where rEFInd draws cards, tools, text and hints."""
    if strength <= 0:
        return base

    def level(dimmed: int) -> int:
        return round(255 - (255 - dimmed) * strength)

    mask = Image.new("L", (192, 108), 255)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((0, 0, 96, 29), fill=level(60))  # hardware readout
    draw.rectangle((25, 29, 167, 76), fill=level(55))  # OS cards
    draw.rectangle((48, 76, 144, 108), fill=level(80))  # tool row + nav bar
    mask = mask.filter(ImageFilter.GaussianBlur(6)).resize(
        base.size, Image.Resampling.BICUBIC
    )
    alpha = base.getchannel("A")
    dimmed = ImageChops.multiply(
        base.convert("RGB"), Image.merge("RGB", (mask, mask, mask))
    ).convert("RGBA")
    dimmed.putalpha(alpha)
    return dimmed


def _draw_skin_hud(
    canvas,
    skin: Skin,
    font_path: Path | None,
    options: Mapping | None = None,
    accent: tuple[int, int, int] | None = None,
) -> None:
    """Procedural HUD (title bar, tagline, kanji column, decorations).

    Coordinates are authored on a 3840x2160 grid and scaled to the canvas.
    Every element can be switched off or re-worded through the options.
    """
    opts = options or default_options()
    width, height = canvas.size
    sx, sy = width / 3840.0, height / 2160.0

    def pt(x: float, y: float) -> tuple[int, int]:
        return round(x * sx), round(y * sy)

    accent = (*(accent or skin.accent), 255)
    white = (228, 228, 232, 255)
    grey = (140, 140, 146, 255)
    line = max(1, round(2 * sy))
    title_font = find_font(font_path, max(14, round(40 * sy)))
    title = opts["hud.title_text"] or skin.title
    tagline = (opts["hud.tagline_text"] or skin.tagline) if opts["hud.tagline"] else ""
    kanji = (opts["hud.kanji_text"] or skin.kanji) if opts["hud.kanji"] else ""

    # Soft dark plates keep the right-hand HUD text legible over the artwork.
    plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    plate_draw = ImageDraw.Draw(plate)
    tagline_w = title_font.getlength(tagline) / sx if tagline else 0
    if tagline_w:
        plate_draw.rectangle((pt(3726 - tagline_w, 24), pt(3790, 104)), fill=(0, 0, 0, 200))
    if kanji:
        kanji_end = 200 + 92 * len(kanji) + 90
        plate_draw.rectangle((pt(3680, 150), pt(3800, kanji_end)), fill=(0, 0, 0, 180))
    canvas.alpha_composite(plate.filter(ImageFilter.GaussianBlur(max(2, round(14 * sx)))))

    draw = ImageDraw.Draw(canvas)
    small_font = find_font(font_path, max(12, round(26 * sy)))
    if opts["hud.title"]:
        draw.text(pt(84, 52), f"0x0000_BOOT // {title}", font=title_font, fill=white)
    if tagline:
        draw.text(pt(3756, 52), tagline, font=title_font, fill=white, anchor="ra")

    if opts["hud.decorations"]:
        # Title rule with center cross, dotted marker and accent tab.
        draw.line((pt(84, 124), pt(3756, 124)), fill=grey, width=line)
        draw.line((pt(1920, 106), pt(1920, 142)), fill=white, width=line)
        for dx in (0, 16, 32):
            draw.rectangle((pt(2860 + dx, 118), pt(2868 + dx, 130)), fill=white)
        draw.rectangle((pt(84, 142), pt(104, 150)), fill=grey)
        draw.rectangle((pt(120, 142), pt(184, 150)), fill=accent)
        draw.rectangle((pt(3726, 114), pt(3756, 126)), fill=white)
        # Left and right rulers.
        draw.line((pt(150, 700), pt(150, 1010)), fill=grey, width=line)
        for ty in range(716, 1010, 42):
            draw.line((pt(140, ty), pt(160, ty)), fill=grey, width=line)
        draw.text(pt(84, 640), "SYS_01", font=small_font, fill=grey)
        draw.line((pt(3712, 860), pt(3712, 1480)), fill=grey, width=line)
        for ty in range(880, 1480, 56):
            draw.rectangle((pt(3700, ty), pt(3724, ty + 20)), outline=grey, width=line)
        # Corner brackets framing the whole screen.
        arm = 90
        for cx, cy, hx, vy in (
            (40, 40, 1, 1), (3800, 40, -1, 1), (40, 2120, 1, -1), (3800, 2120, -1, -1)
        ):
            draw.line((pt(cx, cy), pt(cx + hx * arm, cy)), fill=grey, width=line)
            draw.line((pt(cx, cy), pt(cx, cy + vy * arm)), fill=grey, width=line)

    # Vertical kanji column on the right edge, closed by an accent tab.
    if kanji:
        cjk_font = find_cjk_font(max(16, round(54 * sy)))
        y = 200
        if cjk_font is not None:
            for glyph in kanji:
                draw.text(pt(3740, y), glyph, font=cjk_font, fill=white, anchor="ma")
                y += 92
        draw.rectangle((pt(3722, y + 12), pt(3758, y + 18)), fill=accent)
        draw.text(pt(3740, y + 34), "v1.0", font=small_font, fill=accent, anchor="ma")


def hud_text_lines(hardware: HardwareInfo, options: Mapping) -> list[str]:
    """The readout under the title: selected hardware rows plus custom rows."""
    rows = {
        "uefi": f"UEFI {hardware.uefi_version} ] Secure Boot: {hardware.secure_boot}",
        "cpu": f"CPU: {hardware.cpu}",
        "ram": f"RAM: {hardware.ram}",
        "gpu": f"GPU: {hardware.gpu}",
        "nvme": f"NVMe: {hardware.nvme} -- OK",
    }
    lines = (
        [rows[key] for key in HARDWARE_LINES if key in options["hud.hardware_lines"]]
        if options["hud.hardware"] else []
    )
    return [*lines, *options["hud.custom_lines"]][:9]


def render_background(
    source: Path,
    resolution: Resolution,
    hardware: HardwareInfo,
    font_path: Path | None = None,
    *,
    overlay_path: Path | None = None,
    effect_path: Path | None = None,
    skin: Skin | None = None,
    options: Mapping | None = None,
):
    """Compose the full-screen artwork with HUD overlay, glitch effects, and
    typewriter-style hardware readout.

    Layers (bottom to top):
      1. ``source`` — dark base background (skull, eye, HUD elements), or a
         skin's AI artwork with the UI zones darkened
      2. ``overlay_path`` — white/RGBA HUD frame, title bar, decorative art;
         otherwise the HUD is drawn procedurally in the accent color
      3. Hardware spec text rendered as a typewriter animation frozen mid-line
      4. ``effect_path`` — glitch/noise scanline texture (screen-blended)
      5. Procedural scanlines and noise grain for extra life
      6. Navigation bar
    Every layer honours the customisation options (see OPTION_SPECS).
    """
    _require_pillow()
    import random as _rng

    opts = dict(options) if options is not None else default_options()
    target_w, target_h = resolution.width, resolution.height
    accent = (
        parse_hex_color(opts["hud.accent"]) if opts["hud.accent"]
        else skin.accent if skin else DEFAULT_ACCENT
    )
    accent_hex = "#{:02X}{:02X}{:02X}".format(*accent)

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
    if skin is not None:
        base = _darken_ui_zones(
            _pin_art_to_corners(base, opts["layout.art_scale"]), opts["layout.ui_dim"]
        )
        brightness = opts["layout.art_brightness"] or skin.art_brightness
        if brightness != 1.0:
            base = ImageEnhance.Brightness(base).enhance(brightness)
    elif opts["layout.art_brightness"]:
        base = ImageEnhance.Brightness(base).enhance(opts["layout.art_brightness"])

    canvas = Image.new("RGBA", base.size, (0, 0, 0, 255))
    canvas.alpha_composite(base)
    canvas.putpixel((0, 0), (0, 0, 0, 255))
    if skin is not None or overlay_path is None:
        _draw_skin_hud(canvas, skin or GHOUL_HUD, font_path, opts, accent)

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
    font_size = max(14, round(24 * scale_h))
    hud_font = find_font(font_path, font_size)
    x_start = round(175 * scale_w)
    step = 72
    lines = hud_text_lines(hardware, opts)
    for index, line in enumerate(lines):
        y = round((168 + index * step) * scale_h)
        draw.text(
            (x_start, y),
            ellipsize(draw, line, hud_font, resolution.width // 2),
            font=hud_font,
            fill="#E4E4E4",
        )
        if skin is not None or overlay_path is None:
            draw.text((round(104 * scale_w), y), ">", font=hud_font, fill=(140, 140, 146))

    # Active typing line with a glowing accent cursor
    if opts["hud.status_line"]:
        c_y = round((168 + len(lines) * step) * scale_h)
        init_text = opts["hud.status_text"]
        draw.text((x_start, c_y), init_text, font=hud_font, fill="#EFEFEF")
        c_len = draw.textlength(init_text, font=hud_font)
        cur_h = max(16, round(24 * scale_h))
        cur_w = max(10, round(16 * scale_w))
        draw.rectangle(
            (x_start + c_len + 8, c_y + 4, x_start + c_len + 8 + cur_w, c_y + 4 + cur_h),
            fill=accent_hex,
        )

    # --- Layer 4: Glitch/noise effect overlay (screen blend) ---
    if effect_path is not None and opts["hud.glitch"]:
        try:
            with Image.open(effect_path) as ef:
                effect_rgba = ImageOps.fit(
                    ImageOps.exif_transpose(ef).convert("RGBA"),
                    (target_w, target_h),
                    Image.Resampling.LANCZOS,
                )
                # Boost brightness so the subtle noise is visible
                effect_boosted = ImageEnhance.Brightness(effect_rgba).enhance(3.5)
                r, g, b, a = effect_boosted.split()
                # ~45% alpha: visible but not overwhelming noise
                a = a.point(lambda x: min(255, int(x * 0.45)))
                canvas.alpha_composite(Image.merge("RGBA", (r, g, b, a)))
        except (OSError, ValueError):
            pass  # effect is optional

    # --- Layer 5: Procedural scanlines and glitch bars ---
    scanline_overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    scan_draw = ImageDraw.Draw(scanline_overlay)
    if opts["hud.scanlines"]:
        for y_pos in range(0, target_h, 4):
            scan_draw.line([(0, y_pos), (target_w, y_pos)], fill=(0, 0, 0, 18), width=1)
    if opts["hud.glitch"]:
        _rng.seed(42)  # deterministic so it's reproducible
        for _ in range(35):
            gy = _rng.randint(0, target_h - 1)
            gx = _rng.randint(0, max(1, target_w - 200))
            gw = _rng.randint(40, 250)
            brightness = _rng.choice([20, 25, 30, 35, 40])
            alpha = _rng.randint(30, 80)
            scan_draw.rectangle(
                [(gx, gy), (gx + gw, gy + 1)],
                fill=(brightness, brightness, brightness, alpha),
            )
        # Accent glitch bars
        for _ in range(8):
            gy = _rng.randint(0, target_h - 1)
            gx = _rng.randint(0, max(1, target_w - 100))
            gw = _rng.randint(20, 120)
            scan_draw.rectangle(
                [(gx, gy), (gx + gw, gy + 1)],
                fill=(*accent, _rng.randint(15, 50)),
            )
    canvas.alpha_composite(scanline_overlay)

    # --- Layer 6: Navigation bar ---
    if opts["hud.nav_bar"]:
        nav_size = max(14, round(20 * max(scale_h, 0.75)))
        nav_font = find_font(font_path, nav_size)
        segments = (NAV_LEFT, NAV_ENTER, NAV_RIGHT)
        total = sum(draw.textlength(s, font=nav_font) for s in segments)
        while nav_size > 10 and total > resolution.width - 140:
            nav_size -= 1
            nav_font = find_font(font_path, nav_size)
            total = sum(draw.textlength(s, font=nav_font) for s in segments)
        if total <= resolution.width - 40:  # never fail a build over the hint bar
            x = (resolution.width - total) / 2
            y = resolution.height - round(70 * max(scale_h, 0.6))
            for segment, color in zip(segments, ("#DCDCDC", accent_hex, "#DCDCDC")):
                draw.text((x, y), segment, font=nav_font, fill=color)
                x += draw.textlength(segment, font=nav_font)
    return canvas


# --- Card index numbers ("01", "02", ...) ---
# The AI cards were drawn with a fixed number in the bottom-left corner. The
# builder finds that number, paints it out and draws the right one for this
# PC (or none), in the same place, size, weight and colour.

_NUMBER_PROBE = 512       # detection runs on a copy of this size
_NUMBER_INK = 150         # max channel above this counts as ink
_NUMBER_CACHE: dict[tuple, "CardNumber | None"] = {}


@dataclass(frozen=True)
class CardNumber:
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the card
    colour: tuple[int, int, int]
    background: tuple[int, int, int]
    stroke: float                           # stroke width / digit height
    glow: bool
    ink: int = _NUMBER_INK                  # brightness threshold that isolated the digits


def _ink_components(pixels, width: int, height: int, threshold: int):
    """8-connected blobs of bright pixels: (x0, y0, x1, y1, count) each."""
    ink = bytearray(1 if max(p[:3]) > threshold else 0 for p in pixels)
    seen = bytearray(width * height)
    blobs = []
    for start in range(width * height):
        if not ink[start] or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        x0 = x1 = start % width
        y0 = y1 = start // width
        count = 0
        while stack:
            pos = stack.pop()
            count += 1
            px, py = pos % width, pos // width
            x0, x1, y0, y1 = min(x0, px), max(x1, px), min(y0, py), max(y1, py)
            for ny in (py - 1, py, py + 1):
                if 0 <= ny < height:
                    for nx in (px - 1, px, px + 1):
                        if 0 <= nx < width:
                            q = ny * width + nx
                            if ink[q] and not seen[q]:
                                seen[q] = 1
                                stack.append(q)
        blobs.append((x0, y0, x1 + 1, y1 + 1, count))
    return blobs, ink


def _card_interior(rgb) -> tuple[int, int, int, int]:
    """Bounding box of the dark card body (skips white page margins)."""
    width, height = rgb.size
    dark = rgb.convert("L").point(lambda v: 255 if v < 70 else 0)
    rows = list(dark.resize((1, height), Image.Resampling.BOX).tobytes())
    cols = list(dark.resize((width, 1), Image.Resampling.BOX).tobytes())
    ys = [y for y, v in enumerate(rows) if v > 255 * 0.4] or [0, height - 1]
    xs = [x for x, v in enumerate(cols) if v > 255 * 0.4] or [0, width - 1]
    return xs[0], ys[0], xs[-1] + 1, ys[-1] + 1


def detect_card_number(image) -> CardNumber | None:
    """Find the baked-in index number in the bottom-left corner of a card."""
    _require_pillow()
    rgb = image.convert("RGB").resize((_NUMBER_PROBE, _NUMBER_PROBE), Image.Resampling.BILINEAR)
    left, top, right, bottom = _card_interior(rgb)
    card_w, card_h = right - left, bottom - top
    rx0, ry0 = left, top + round(card_h * 0.72)
    rx1, ry1 = left + round(card_w * 0.38), bottom
    roi = rgb.crop((rx0, ry0, rx1, ry1))
    raw = roi.tobytes()
    pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    # dim digits need a lower threshold, glowing ones a higher one
    for threshold in (_NUMBER_INK, 110, 190, 225):
        found = _find_number(pixels, roi.size, (rx0, ry0), card_h, threshold)
        if found is not None:
            return found
    return None


def _find_number(pixels, roi_size, origin, card_h, threshold) -> CardNumber | None:
    rw, rh = roi_size
    rx0, ry0 = origin
    blobs, ink = _ink_components(pixels, rw, rh, threshold)
    glyphs = []
    for x0, y0, x1, y1, count in blobs:
        gw, gh = x1 - x0, y1 - y0
        if card_h * 0.02 <= gh <= card_h * 0.085 and gh * 0.12 <= gw <= gh * 1.0:
            glyphs.append((x0, y0, x1, y1))
    # the slash inside a slashed zero is its own blob: drop nested ones
    glyphs = [g for g in glyphs if not any(
        o != g and o[0] <= g[0] and o[1] <= g[1] and o[2] >= g[2] and o[3] >= g[3] for o in glyphs)]
    glyphs.sort()
    best = None
    for i, first in enumerate(glyphs):
        chain = [first]
        for g in glyphs[i + 1:]:
            last = chain[-1]
            gh = last[3] - last[1]
            gap = g[0] - last[2]
            if (abs(g[1] - last[1]) <= gh * 0.2 and abs((g[3] - g[1]) - gh) <= gh * 0.2
                    and -gh * 0.1 <= gap <= gh * 0.8):
                chain.append(g)
            elif g[0] > last[2] + gh:
                break
        if 2 <= len(chain) <= 3:
            height = max(g[3] for g in chain) - min(g[1] for g in chain)
            if best is None or height > best[0] + 1:
                best = (height, chain)
    if best is None:
        return None
    chain = best[1]
    bx0, by0 = min(g[0] for g in chain), min(g[1] for g in chain)
    bx1, by1 = max(g[2] for g in chain), max(g[3] for g in chain)
    digit_h = by1 - by0
    inked = [pixels[y * rw + x] for y in range(by0, by1) for x in range(bx0, bx1) if ink[y * rw + x]]
    peak = max(max(p[:3]) for p in inked)
    strong = sorted((p for p in inked if max(p[:3]) >= peak * 0.8), key=lambda p: sum(p[:3]))
    colour = tuple(strong[len(strong) // 2][:3])
    # background: dark end of a wide ring around the number
    pad = max(2, round(digit_h * 1.2))
    ring = [
        pixels[y * rw + x]
        for y in range(max(0, by0 - pad), min(rh, by1 + pad))
        for x in range(max(0, bx0 - pad), min(rw, bx1 + pad))
        if not (bx0 <= x < bx1 and by0 <= y < by1) and not ink[y * rw + x]
    ]
    ring.sort(key=lambda p: sum(p[:3]))
    background = tuple(ring[len(ring) // 10][:3]) if ring else (0, 0, 0)
    near = [pixels[y * rw + x]
            for y in range(max(0, by0 - 2), min(rh, by1 + 2))
            for x in range(max(0, bx0 - 2), min(rw, bx1 + 2)) if not ink[y * rw + x]]
    glow = threshold > _NUMBER_INK or (
        bool(near) and sum(max(p[:3]) for p in near) / len(near) > max(background) + 40)
    # stroke: first ink run on the middle row of the first digit
    first = chain[0]
    mid = (first[1] + first[3]) // 2
    run = 0
    for x in range(first[0], first[2]):
        if ink[mid * rw + x]:
            run += 1
        elif run:
            break
    scale = _NUMBER_PROBE
    return CardNumber(
        box=((rx0 + bx0) / scale, (ry0 + by0) / scale, (rx0 + bx1) / scale, (ry0 + by1) / scale),
        colour=colour,
        background=background,
        stroke=min(run / digit_h, 0.14 if glow else 0.25) if digit_h else 0.1,
        glow=glow,
        ink=threshold,
    )


def card_number_for(path: Path) -> CardNumber | None:
    """detect_card_number() for a file, cached by path and mtime."""
    key = (str(path), path.stat().st_mtime)
    if key not in _NUMBER_CACHE:
        _NUMBER_CACHE[key] = detect_card_number(crop_square(open_rgba(path)))
    return _NUMBER_CACHE[key]


def _first_run(mask, width: int, height: int) -> int:
    """Width of the first ink run on the middle row of an L-mode mask."""
    row = list(mask.crop((0, height // 2, width, height // 2 + 1)).tobytes())
    run = 0
    for value in row:
        if value > 127:
            run += 1
        elif run:
            break
    return run


def apply_card_number(image, info: CardNumber | None, number: int | None,
                      font_path: Path | None = None):
    """Paint out the baked-in number and draw ``number`` (or nothing) instead."""
    if info is None:
        return image
    size_w, size_h = image.size
    fx0, fx1 = sorted(min(1.0, max(0.0, v)) for v in (info.box[0], info.box[2]))
    fy0, fy1 = sorted(min(1.0, max(0.0, v)) for v in (info.box[1], info.box[3]))
    x0, y0, x1, y1 = fx0 * size_w, fy0 * size_h, fx1 * size_w, fy1 * size_h
    if x1 - x0 < 1 or y1 - y0 < 1:
        return image
    mode = image.mode
    image = image.convert("RGBA" if "A" in mode or mode == "P" else "RGB")
    digit_h = y1 - y0
    pad = digit_h * (0.9 if info.glow else 0.35)
    rect = (max(0, round(x0 - pad)), max(0, round(y0 - pad)),
            min(size_w, round(x1 + pad)), min(size_h, round(y1 + pad)))
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        return image.convert(mode)
    region = image.crop(rect).convert("RGB")
    red, green, blue = region.split()
    brightest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    # flatten glow and background, keep other ink (frame lines, dashes)
    keep = max(info.ink, _NUMBER_INK)
    mask = brightest.point(lambda v: 255 if v < keep else 0)
    grow = max(1, round(digit_h * 0.08))
    ImageDraw.Draw(mask).rectangle(
        (round(x0) - rect[0] - grow, round(y0) - rect[1] - grow,
         round(x1) - rect[0] + grow, round(y1) - rect[1] + grow), fill=255)
    image.paste(info.background + ((255,) if image.mode == "RGBA" else ()), rect, mask)
    if number is None:
        return image.convert(mode)
    number = max(0, min(99, int(number)))

    text = f"{number:02d}"
    probe = find_font(font_path, 100)
    zero = probe.getbbox("0")
    font = find_font(font_path, max(6, round(100 * digit_h / max(1, zero[3] - zero[1]))))
    box = font.getbbox(text)
    # match the original weight: thicken the font by the missing stroke
    sample = Image.new("L", (box[2] + 4, box[3] + 4), 0)
    ImageDraw.Draw(sample).text((2 - box[0], 2), "0", font=font, fill=255)
    natural = _first_run(sample, *sample.size)
    extra = max(0, min(round(digit_h * 0.2), round((info.stroke * digit_h - natural) / 2)))
    pos = (round(x0) - box[0], round(y1) - box[3])
    if info.glow:
        layer = Image.new("RGB", image.size, (0, 0, 0))
        ImageDraw.Draw(layer).text(pos, text, font=font, fill=info.colour,
                                   stroke_width=extra + max(1, round(digit_h * 0.08)),
                                   stroke_fill=info.colour)
        layer = layer.filter(ImageFilter.GaussianBlur(max(1, digit_h * 0.35)))
        glowed = ImageChops.screen(image.convert("RGB"), layer)
        if image.mode == "RGBA":
            glowed.putalpha(image.getchannel("A"))
        image = glowed
    ImageDraw.Draw(image).text(pos, text, font=font, fill=info.colour + ((255,) if image.mode == "RGBA" else ()),
                               stroke_width=extra, stroke_fill=info.colour)
    return image.convert(mode)


def detect_systems(runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> tuple[str, ...]:
    """Best-effort guess of the systems on this PC, as NUMBERED_CARDS keys."""
    found: list[str] = []
    if sys.platform == "win32":
        return ("win_dev",)
    try:
        result = (runner or run_command)(("efibootmgr",), check=False)
        windows = len(re.findall(r"^Boot[0-9A-Fa-f]{4}\*?\s+Windows Boot Manager",
                                 result.stdout or "", re.MULTILINE))
        found += ["win_dev", "win_game"][:windows]
    except (OSError, subprocess.SubprocessError, TypeError):
        pass
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
        distro = re.search(r"^ID=\"?([A-Za-z0-9._-]+)", release, re.MULTILINE)
        ident = distro.group(1).casefold() if distro else ""
        found.append({"cachyos": "cachyos", "arch": "arch"}.get(ident, "linux"))
    except OSError:
        pass
    return tuple(found)


def auto_card_order(options: Mapping, detected: Sequence[str] = ()) -> tuple[str, ...]:
    """Menu entries first, then systems found on this PC, then the rest."""
    wanted = [e["card"] for e in options["entries"] if not e.get("disabled")]
    return tuple(dict.fromkeys(
        card for card in (*wanted, *detected, *NUMBERED_CARDS) if card in NUMBERED_CARDS
    ))


def card_numbers(options: Mapping, detected: Sequence[str] | None = None) -> dict[str, int]:
    """Card key -> number shown on it. Cards left out get no number."""
    if not options["cards.numbers"]:
        return {}
    order = tuple(options["cards.order"]) or auto_card_order(
        options, detect_systems() if detected is None else detected
    )
    return {card: index for index, card in enumerate(order, 1)}


# --- Fast approximate preview of the rEFInd screen (used by Theme Studio) ---

# Tool icon file per rEFInd showtools token; "always" tools appear on every PC.
PREVIEW_TOOL_ICONS = {
    "firmware": "tool_firmware", "reboot": "func_reset", "shutdown": "func_shutdown",
    "about": "func_about", "exit": "func_exit", "bootorder": "func_bootorder",
    "hidden_tags": "func_hidden", "shell": "tool_shell", "memtest": "tool_memtest",
    "gdisk": "tool_part", "gptsync": "tool_part", "netboot": "tool_netboot",
    "mok_tool": "tool_mok_tool", "fwupdate": "tool_fwupdate", "install": "func_install",
    "apple_recovery": "tool_apple_rescue", "windows_recovery": "tool_windows_rescue",
    "csr_rotate": "func_csr_rotate",
}
# rEFInd tool -> ai_icons/<name> artwork (what build_theme uses for it)
PREVIEW_TOOL_ART = {
    "reboot": "reboot", "about": "about", "exit": "exit", "bootorder": "bootorder",
    "hidden_tags": "hidden", "shell": "shell", "memtest": "memtest", "gdisk": "part",
    "gptsync": "part", "netboot": "netboot", "mok_tool": "mok", "fwupdate": "fwupdate",
    "install": "install", "apple_recovery": "rescue", "windows_recovery": "rescue",
    "csr_rotate": "csr_rotate",
}
PREVIEW_ALWAYS_TOOLS = ("firmware", "reboot", "shutdown", "about", "exit", "bootorder", "hidden_tags")
_PREVIEW_CACHE: dict[tuple, object] = {}


def _cached_asset(path: Path, size: int, *, selection_frame: bool = False):
    key = ("asset", str(path), path.stat().st_mtime, size, selection_frame)
    if key not in _PREVIEW_CACHE:
        _PREVIEW_CACHE[key] = resize_asset(path, size, selection_frame=selection_frame)
    return _PREVIEW_CACHE[key]


def render_preview(
    theme: str,
    options: Mapping | None = None,
    *,
    hardware: HardwareInfo | None = None,
    width: int = 1280,
    source_dir: Path | None = None,
):
    """Approximate the final rEFInd screen quickly, without a full build.

    Layout constants were measured on real rEFInd screenshots (OVMF/QEMU):
    OS row centred at 50% height with a 1.135x icon pitch, tool row at 78%.
    """
    _require_pillow()
    options = dict(options) if options is not None else default_options()
    source_dir = source_dir or Path(__file__).resolve().parent
    skin = None if theme == THEME_NAME else load_skin(theme)
    assets = discover_assets(source_dir)
    if skin is not None:
        for stem in (*ASSET_STEMS, "card_linux"):
            candidate = skin.art.parent / f"{stem}.png"
            if stem != "background" and candidate.is_file():
                assets[stem] = candidate
    real = parse_resolution(options["layout.resolution"])
    preview = Resolution(width, round(width * 9 / 16))
    scale = preview.width / real.width
    big, small = icon_geometry(options, real)
    big_px, small_px = max(24, round(big * scale)), max(12, round(small * scale))
    accent = (
        parse_hex_color(options["hud.accent"]) if options["hud.accent"]
        else skin.accent if skin else DEFAULT_ACCENT
    )

    if "banner" in options["refind.hideui"]:
        canvas = Image.new("RGBA", (preview.width, preview.height), (0, 0, 0, 255))
    else:
        canvas = render_background(
            skin.art if skin else assets["background"],
            preview,
            hardware or HardwareInfo(cpu="Your CPU", ram="32 GB", gpu="Your GPU", nvme="2 TB"),
            overlay_path=(
                assets.get("background_overlay")
                if skin is None and options["hud.ghoul_overlay"] else None
            ),
            effect_path=assets.get("background_effect"),
            skin=skin,
            options=options,
        )

    def tint(image):
        return recolor_accent(image, accent) if accent != DEFAULT_ACCENT else image

    cards = [("cachyos", assets["selection_item_linux"]), ("win_dev", assets["selection_item_windev"]),
             ("win_game", assets["selection_item_wingame"])]
    entry_card = {"cachyos": "selection_item_linux", "win_dev": "selection_item_windev",
                  "win_game": "selection_item_wingame"}
    if "card_linux" in assets:
        entry_card["linux"] = "card_linux"
    for entry in options["entries"]:
        if not entry["disabled"]:
            cards.append((entry["card"], assets[entry_card.get(entry["card"], "selection_item_windev")]))
    if options["refind.max_tags"]:
        cards = cards[: options["refind.max_tags"]]
    if "systems" not in _PREVIEW_CACHE:
        _PREVIEW_CACHE["systems"] = detect_systems()
    numbers = card_numbers(options, _PREVIEW_CACHE["systems"])
    shown = cards[: visible_tiles(options, real)]
    more = len(cards) > len(shown)
    cards = shown
    pitch = big_px * 1.135
    left = (preview.width - pitch * (len(cards) - 1)) / 2
    row_y = preview.height * 0.5
    frame = tint(render_cyber_selection_frame(
        assets["selection_box"], round(big_px * options["layout.selection_scale"])
    ))
    for index, (card_key, card_path) in enumerate(cards):
        cx = left + index * pitch
        if index == 0:
            canvas.alpha_composite(frame, (round(cx - frame.width / 2), round(row_y - frame.height / 2)))
        number = numbers.get(card_key)
        key = ("numbered", str(card_path), card_path.stat().st_mtime, big_px, number)
        if key not in _PREVIEW_CACHE:
            _PREVIEW_CACHE[key] = apply_card_number(
                _cached_asset(card_path, big_px), card_number_for(card_path), number)
        card = _PREVIEW_CACHE[key]
        if skin is None or skin.art.parent not in card_path.parents:
            card = tint(card)  # the build recolours inherited cards, not a skin's own
        canvas.alpha_composite(card, (round(cx - big_px / 2), round(row_y - big_px / 2)))

    if more and options["layout.scroll_arrows"]:
        arrow_px = small_px
        # the row starts unscrolled, so rEFInd shows only the right arrow
        for name, x in (("arrow_right", left + pitch * (len(cards) - 1) + big_px / 2 + arrow_px * 0.1),):
            arrow = render_cyber_icon(arrow_px, name)   # as in the build
            canvas.alpha_composite(tint(arrow), (round(x), round(row_y - arrow_px / 2)))
    tools = [t for t in shown_tools(options)
             if t in PREVIEW_ALWAYS_TOOLS or t in options["refind.extra_tools"]]
    tool_pitch = small_px * 1.37
    tool_left = (preview.width - tool_pitch * (len(tools) - 1)) / 2
    for index, tool in enumerate(tools):
        if tool in {"firmware", "shutdown"}:
            path = assets["bios" if tool == "firmware" else "power"]
            key = ("tool-card", str(path), path.stat().st_mtime, small_px)
            if key not in _PREVIEW_CACHE:
                _PREVIEW_CACHE[key] = tool_card(open_rgba(path), small_px)
            icon = _PREVIEW_CACHE[key]
        else:
            # the same artwork and shared frame as the build, never a stale dist/ copy
            key = ("tool", tool, small_px)
            if key not in _PREVIEW_CACHE:
                art = load_ai_icon(PREVIEW_TOOL_ART.get(tool, tool), small_px)
                _PREVIEW_CACHE[key] = (tool_card(art, small_px) if art is not None
                                       else render_cyber_icon(small_px, PREVIEW_TOOL_ART.get(tool, tool)))
            icon = _PREVIEW_CACHE[key]
        cx = tool_left + index * tool_pitch
        canvas.alpha_composite(tint(icon), (round(cx - small_px / 2), round(preview.height * 0.78 - small_px / 2)))
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


def _flatten_block_devices(devices: Iterable[Mapping[str, object]], depth: int = 0):
    if not isinstance(devices, list) or depth > 16:
        return
    for device in devices:
        if not isinstance(device, Mapping):
            continue  # lsblk never emits this; ignore rather than crash
        yield device
        yield from _flatten_block_devices(device.get("children"), depth + 1)


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
    state_path = root / "install-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeError(f"generated install-state.json is invalid: {exc}") from exc
    if state.get("format_version") != 1 or state.get("resolution") != str(
        resolution
    ):
        raise ThemeError("generated install-state.json has incompatible metadata")
    geometry = state.get("geometry")
    if isinstance(geometry, Mapping):
        # A theme built with custom icon sizes validates against those sizes.
        configure_geometry(
            int(geometry.get("big", 768)),
            int(geometry.get("small", 240)),
            float(geometry.get("selection_scale", 1.125)),
        )
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
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ThemeError(f"generated theme.conf is missing: {config_path}") from exc
    expected_hash = (state.get("sha256") or {}).get("theme.conf")
    if (
        not config_text.startswith("banner themes/ghoul-cyber/background.png\n")
        or expected_hash != sha256_file(config_path)
    ):
        raise ThemeError(f"generated theme.conf is inconsistent: {config_path}")
    files.append(config_path)
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


def _progress(step: int, message: str) -> None:
    print(f"[{step}/5] {message}", flush=True)


def _save_png(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(path, format="PNG", compress_level=6)


def build_theme(
    source_dir: Path,
    output_dir: Path,
    resolution: Resolution,
    hardware: HardwareInfo,
    font_path: Path | None = None,
    *,
    skin: Skin | None = None,
    options: Mapping | None = None,
) -> ThemeBuild:
    """Build a complete, validated theme through an external staging folder."""
    _require_pillow()
    options = dict(options) if options is not None else default_options()
    configure_geometry(*icon_geometry(options, resolution), options["layout.selection_scale"])
    accent = (
        parse_hex_color(options["hud.accent"]) if options["hud.accent"]
        else skin.accent if skin else DEFAULT_ACCENT
    )
    assets = discover_assets(source_dir)
    skin_stems: set[str] = set()
    if skin is not None:
        # A skin may ship its own cards/frames under the same asset stems.
        for stem in (*ASSET_STEMS, "card_linux"):
            override = next(
                (
                    skin.art.parent / f"{stem}{suffix}"
                    for suffix in (".png", ".jpg", ".jpeg")
                    if (skin.art.parent / f"{stem}{suffix}").is_file()
                ),
                None,
            )
            if override is not None and stem != "background":
                assets[stem] = override
                skin_stems.add(stem)
    output_dir = output_dir.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="ghoul-cyber-build-") as raw:
        staging = Path(raw) / THEME_NAME
        (staging / "icons").mkdir(parents=True)

        _progress(1, f"background {resolution} ({skin.name if skin else THEME_NAME})")
        _save_png(
            render_background(
                skin.art if skin else assets["background"],
                resolution,
                hardware,
                font_path,
                overlay_path=(
                    assets.get("background_overlay")
                    if skin is None and options["hud.ghoul_overlay"] else None
                ),
                effect_path=assets.get("background_effect"),
                skin=skin,
                options=options,
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
        _progress(2, "OS cards and selection frames")
        numbers = card_numbers(options)
        for stem, (filename, size) in source_mapping.items():
            icon = (tool_card(open_rgba(assets[stem]), size) if stem in {"bios", "power"}
                    else resize_asset(assets[stem], size))
            if stem in CARD_STEMS:
                icon = apply_card_number(icon, card_number_for(assets[stem]),
                                         numbers.get(CARD_STEMS[stem]), font_path)
            _save_png(icon, staging / "icons" / filename)
        ai_reboot = load_ai_icon("reboot", SMALL_ICON_SIZE) or load_ai_icon(
            "tool_reboot", SMALL_ICON_SIZE
        )
        _save_png(
            tool_card(ai_reboot, SMALL_ICON_SIZE)
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
        _progress(3, "tool and distro icons")
        for filename, (sz, itype) in generated_icons.items():
            # Prefer AI-generated icon if available in ai_icons/ directory
            ai_img = load_ai_icon(itype, sz)
            if ai_img is not None:
                if sz == SMALL_ICON_SIZE:
                    ai_img = tool_card(ai_img, sz)
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
        card_of = {"os_win.png": "windows", "os_arch.png": "arch", "os_linux.png": "linux"}
        for filename, spec in card_icons.items():
            number = numbers.get(card_of[filename])
            if filename == "os_linux.png" and "card_linux" in assets:
                icon = apply_card_number(resize_asset(assets["card_linux"], BIG_ICON_SIZE),
                                         card_number_for(assets["card_linux"]), number, font_path)
                _save_png(icon, staging / "icons" / filename)
                continue
            ai_img = load_ai_icon(filename[: -len(".png")], BIG_ICON_SIZE)
            spec = {**spec, "index": f"{number:02d}" if number else ""}
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
            # rEFInd asks for these when the matching tools are present;
            # without them it draws a placeholder in the tool row.
            "tool_windows_rescue.png": "tool_rescue.png",
            "tool_apple_rescue.png": "tool_rescue.png",
        }
        install_icon = load_ai_icon("install", SMALL_ICON_SIZE)
        if install_icon is not None:
            _save_png(tool_card(install_icon, SMALL_ICON_SIZE), staging / "icons" / "func_install.png")
        else:
            aliases["func_install.png"] = "tool_fwupdate.png"
        for alias, source_name in aliases.items():
            shutil.copy2(
                staging / "icons" / source_name, staging / "icons" / alias
            )

        if accent != DEFAULT_ACCENT:
            _progress(4, "accent color")
            # The skin's own cards are already drawn in its accent.
            own = {
                f"icons/{source_mapping[stem][0]}"
                for stem in skin_stems
                if stem in source_mapping
            }
            if "card_linux" in skin_stems:
                own.add("icons/os_linux.png")
            if "selection_box" in skin_stems:
                own |= {"selection_big.png", "selection_small.png"}
            for png in (
                *sorted((staging / "icons").glob("*.png")),
                staging / "selection_big.png",
                staging / "selection_small.png",
            ):
                if png.relative_to(staging).as_posix() in own:
                    continue
                with Image.open(png) as image:
                    recolored = recolor_accent(image, accent)
                _save_png(recolored, png)

        (staging / "theme.conf").write_text(
            render_theme_conf(options, resolution), encoding="utf-8", newline="\n"
        )
        hashed_paths = [
            PurePosixPath(path) for path in (*IMAGE_SIZES, "theme.conf")
        ]
        state = {
            "format_version": 1,
            "theme": THEME_NAME,
            "skin": skin.name if skin else THEME_NAME,
            "geometry": {
                "big": BIG_ICON_SIZE,
                "small": SMALL_ICON_SIZE,
                "selection_scale": SELECTION_SCALE,
            },
            "options": nest_options(
                {k: v for k, v in options.items() if v != OPTION_BY_KEY[k].default}
            ),
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
        _progress(5, f"validating and publishing to {output_dir}")
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
    except (ValueError, TypeError, RecursionError) as exc:
        raise ThemeError(f"invalid lsblk JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ThemeError("invalid lsblk JSON: expected an object with blockdevices")
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
    """Assign Windows loader(s) and the CachyOS loader - each only if present.

    A PC without Windows, or with another Linux, is fine: those roles are
    simply absent and rEFInd picks the theme's os_* icons by itself.
    """
    windows = [
        entry
        for entry in entries
        if "windows" in _entry_tokens(entry)
        or "microsoft" in entry.loader_path.casefold()
        or "bootmgfw.efi" in entry.loader_path.casefold()
    ]
    on_cachyos = _os_release_id() == "cachyos"
    cachy = [
        entry
        for entry in entries
        if (
            any(token.startswith("cachy") for token in _entry_tokens(entry))
            or "cachy" in entry.loader_path.casefold()
            or (on_cachyos and "vmlinuz" in entry.loader_path.casefold())
        )
        and "refind" not in entry.loader_path.casefold()
    ]
    if not cachy and on_cachyos:
        boot_kernel = find_cachyos_kernel(Path("/boot"))
        # the kernel lives on the partition mounted at /boot; never guess a device
        for partuuid, item in (devices or {}).items() if boot_kernel else ():
            mounts = _mount_points(item)
            if any(m.rstrip("/") == "/boot" for m in mounts):
                cachy = [BootEntry(
                    bootnum="AUTO",
                    label="CachyOS",
                    partuuid=partuuid,
                    loader_path=f"\\{boot_kernel.name}",
                    device=str(item.get("path") or item.get("name") or ""),
                    fs_label=str(item.get("label") or "CachyOS"),
                    mount_points=mounts,
                )]
                break
    linux_role = {"cachyos": cachy[0]} if cachy else {}

    if not windows:
        return linux_role
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
                **linux_role,
            }
        if previous_dev:
            return {
                "win_dev": previous_dev,
                "win_game": next(entry for entry in windows if entry != previous_dev),
                **linux_role,
            }
        if previous_game:
            return {
                "win_dev": next(entry for entry in windows if entry != previous_game),
                "win_game": previous_game,
                **linux_role,
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
            game = next(entry for entry in windows if entry != dev)

    return {"win_dev": dev, "win_game": game, **linux_role}


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


def _is_refind_binary(child: Path, folder: Path) -> bool:
    """refind_x64.efi, or the firmware fallback name when rEFInd lives in EFI/BOOT
    (refind-install --usedefault, or an upgrade of such an install)."""
    name = child.name.casefold()
    if name.startswith("refind_") and name.endswith(".efi"):
        return True
    return folder.name.casefold() == "boot" and name in {"bootx64.efi", "bootaa64.efi", "bootia32.efi"}


def find_refind_dir(
    explicit: Path | None, candidates: Iterable[Path]
) -> Path:
    """Find a directory containing both refind.conf and a rEFInd EFI binary."""

    def valid(path: Path) -> bool:
        try:
            if path.is_dir() and (path / "refind.conf").is_file() and any(
                child.is_file() and _is_refind_binary(child, path) for child in path.iterdir()
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
        "tools": [list(tool) for tool in plan.tools],
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
            tools=tuple((str(source), str(dest)) for source, dest in data.get("tools", ())),
        )
        for source, dest in plan.tools:
            _check_extra_tool(source, dest)
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError) as exc:
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
    # no targets is valid (Linux-only PC, other distro): only the theme is installed
    if any(target.role not in {"win_dev", "win_game", "cachyos"} for target in plan.targets):
        raise ThemeError("deployment plan must contain valid boot roles")
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


def _os_release_id() -> str:
    try:
        raw = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r'^ID="?([^"\n]+)"?', raw, re.MULTILINE)
    return match.group(1).strip().casefold() if match else ""


def linux_package_manager(which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The first supported package manager present on this system."""
    return next((name for name in LINUX_PACKAGE_MANAGERS if which(name)), None)


def _arch_family() -> bool:
    return linux_package_manager() == "pacman"


def bootstrap_linux_dependencies(
    missing: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    manager: str | None = None,
) -> None:
    """Install what is missing with the distribution's own package manager."""
    if not missing:
        return
    manager = manager or linux_package_manager()
    if manager is None:
        raise ThemeError(
            "missing: " + ", ".join(missing) + "; no supported package manager found "
            f"({', '.join(LINUX_PACKAGE_MANAGERS)}) - please install them yourself"
        )
    spec = LINUX_PACKAGE_MANAGERS[manager]
    unpackaged = [item for item in missing if not spec.names.get(item)]
    if unpackaged:
        hint = f"; download it from {REFIND_DOWNLOAD}" if "refind" in unpackaged else ""
        raise ThemeError(f"{', '.join(unpackaged)} is not packaged for {manager}{hint}")
    install_packages(list(dict.fromkeys(spec.names[item] for item in missing)), runner, manager)


def install_packages(
    packages: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    manager: str | None = None,
) -> None:
    """Install packages by name with the system package manager (via sudo)."""
    manager = manager or linux_package_manager()
    if manager is None:
        raise ThemeError("no supported package manager found")
    spec = LINUX_PACKAGE_MANAGERS[manager]
    prefix = _sudo_prefix() if getattr(os, "geteuid", lambda: 1)() != 0 else []
    if manager == "apt-get":
        prefix = [*prefix, "env", "DEBIAN_FRONTEND=noninteractive"]  # sudo drops the environment

    def run(command: Sequence[str]):
        try:
            return runner(tuple([*prefix, *command]))
        except OSError as exc:
            raise ThemeError(f"cannot run {command[0]}: {exc}") from exc

    print(f"installing {', '.join(packages)} with {manager}...")
    result = run([*spec.install, *packages])
    if result.returncode != 0 and spec.refresh is not None:
        # Fresh or never-synced system: refresh the package lists once and retry.
        if manager == "pacman":
            result = run([*spec.refresh, *packages])
        else:
            run(spec.refresh)
            result = run([*spec.install, *packages])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ThemeError(
            "dependency installation failed "
            f"(exit {result.returncode}): {detail[-600:] or 'no diagnostic output'}"
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
    # no targets is fine (Linux-only PC, another distribution): theme only
    if any(target.role not in {"win_dev", "win_game", "cachyos"} for target in plan.targets):
        raise ThemeError("deployment contains an unknown boot role")

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

        tools_dir = refind_dir.parent.parent / "EFI" / "tools"   # ESP/EFI/tools
        for source, dest in plan.tools:
            stage = f"adding {dest}"
            source_path = _check_extra_tool(source, dest)
            if source_path.is_file() and not (tools_dir / dest).exists():
                transaction.copy_file(source_path, tools_dir / dest)
                print(f"added rEFInd tool: EFI/tools/{dest}")

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


def _polish() -> bool:
    """Terminal prompts follow the system language: Polish, otherwise English."""
    forced = os.environ.get("GHOUL_LANG", "").casefold()
    if forced in {"pl", "en"}:
        return forced == "pl"
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(name)
        if value:
            return value.casefold().startswith("pl")
    if sys.platform == "win32":
        try:
            import ctypes
            return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x15
        except (OSError, AttributeError):
            return False
    return False


def _choose_dev_interactively(options: Sequence[BootEntry]) -> int:
    if _polish():
        print("Nie można automatycznie odróżnić instalacji Windows.")
        print("Wybierz pozycję Windows DEV:")
    else:
        print("Cannot tell the Windows installations apart automatically.")
        print("Choose the Windows DEV entry:")
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
        print("Podaj numer widoczny na liście." if _polish() else "Type one of the numbers above.")


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
    # rEFInd installed as the firmware fallback loader: checked last
    candidates += [path.parent / "BOOT" for path in list(candidates) if path.name == "refind"]
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


EFI_GLOBAL = "8be4df61-93ca-11d2-aa0d-00e098032b8c"


def is_uefi_boot(firmware: Path = Path("/sys/firmware/efi")) -> bool:
    return firmware.is_dir()


def secure_boot_enabled(efivars: Path = Path("/sys/firmware/efi/efivars")) -> bool | None:
    """True/False from the SecureBoot EFI variable, None if it cannot be read."""
    try:
        data = (efivars / f"SecureBoot-{EFI_GLOBAL}").read_bytes()
    except OSError:
        return None
    return bool(data[-1]) if data else None


# Extra rEFInd tools the installer can add to EFI/tools, where rEFInd looks for
# them: (file name on the ESP, package per manager, where the package puts it).
EXTRA_TOOLS: dict[str, tuple[str, Mapping[str, str], tuple[str, ...]]] = {
    "shell": ("shellx64.efi", {"pacman": "edk2-shell", "apt-get": "efi-shell-x64"},
              ("/usr/share/edk2-shell/x64/Shell_Full.efi", "/usr/share/edk2-shell/x64/Shell.efi",
               "/usr/share/efi-shell-x64/shellx64.efi")),
    "memtest": ("memtest86.efi", {"pacman": "memtest86+-efi", "apt-get": "memtest86+"},
                ("/boot/memtest86+/memtest.efi", "/boot/memtest86+x64.efi",
                 "/usr/share/ghoul-cyber/memtest86.efi")),
}
# Arch derivatives may lack a tool or ship a conflicting build (CachyOS preinstalls
# BIOS-only memtest86+, so "pacman -S memtest86+-efi" silently does nothing). Then
# the single EFI file is taken from the official, signature-checked Arch package:
# tool -> (Arch package, file inside it, where to keep it)
ARCH_EFI_FALLBACK: dict[str, tuple[str, str, str]] = {
    "memtest": ("memtest86+-efi", "boot/memtest86+/memtest.efi", "/usr/share/ghoul-cyber/memtest86.efi"),
}
EXTRA_TOOL_ROOTS = ("/usr/share/", "/usr/lib/", "/boot/")


def _root_file_exists(path: Path, runner) -> bool:
    """is_file() that also sees root-only places such as a 0700 ESP."""
    try:
        if path.is_file():
            return True
    except OSError:
        pass
    if os.name != "posix" or getattr(os, "geteuid", lambda: 1)() == 0:
        return False
    try:
        return runner(tuple([*_sudo_prefix(), "test", "-f", str(path)])).returncode == 0
    except OSError:
        return False


def _package_is_exact(package: str, runner, manager: str | None) -> bool:
    """pacman quietly swaps a name for a package that merely "provides" it
    (CachyOS: memtest86+-efi -> memtest86+, BIOS build only). Install only the
    real thing."""
    if (manager or linux_package_manager()) != "pacman":
        return True
    try:
        result = runner(("pacman", "-Si", package))
    except OSError:
        return False
    name = re.search(r"^Name\s*:\s*(\S+)", result.stdout or "", re.MULTILINE)
    return result.returncode == 0 and name is not None and name.group(1) == package


ARCH_PACKAGE_API = "https://archlinux.org/packages/extra/any/{name}/json/"
ARCH_PACKAGE_URL = "https://geo.mirror.pkgbuild.com/extra/os/x86_64/{filename}"


def _extract_from_arch(package: str, member: str, destination: str, runner) -> None:
    """Put one file from the official Arch package at `destination`.

    Nothing is installed or replaced: the package and its detached signature are
    downloaded, the signature is checked with pacman-key (archlinux-keyring) and
    only `member` is extracted.
    """
    import urllib.parse
    import urllib.request

    url = ARCH_PACKAGE_API.format(name=urllib.parse.quote(package, safe=""))
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            meta = json.loads(response.read(200_000).decode("utf-8"))
        filename = str(meta["filename"])
    except (OSError, ValueError, KeyError) as exc:
        raise ThemeError(f"cannot look up {package} in the Arch repository: {exc}") from exc
    if not re.fullmatch(r"[A-Za-z0-9@._+-]+\.pkg\.tar\.zst", filename):
        raise ThemeError(f"unexpected Arch package file name: {filename!r}")
    prefix = _sudo_prefix() if getattr(os, "geteuid", lambda: 1)() != 0 else []
    print(f"taking {member} from the Arch package {filename} (signature checked)...")

    def run(command, what):
        try:
            result = runner(tuple(command))
        except OSError as exc:
            raise ThemeError(f"cannot run {command[0]}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ThemeError(f"{what} failed: {detail[-300:] or 'no output'}")

    with tempfile.TemporaryDirectory(prefix="ghoul-cyber-arch-") as raw:
        work = Path(raw)
        package_file, signature = work / filename, work / f"{filename}.sig"
        try:
            for url, target in ((ARCH_PACKAGE_URL.format(filename=filename), package_file),
                                (ARCH_PACKAGE_URL.format(filename=filename) + ".sig", signature)):
                with urllib.request.urlopen(url, timeout=60) as response:
                    target.write_bytes(response.read(64_000_000))
        except OSError as exc:
            raise ThemeError(f"cannot download {filename}: {exc}") from exc
        run([*prefix, "pacman-key", "--verify", str(signature), str(package_file)], "signature check")
        run(["bsdtar", "-xf", str(package_file), "-C", str(work), member], "extracting")
        run([*prefix, "install", "-D", "-m", "644", str(work / member), destination], "copying")


def plan_extra_tools(
    wanted: Iterable[str],
    esp_root: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    manager: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """(source, file name) for each wanted tool missing on the ESP.

    Optional by design: a tool that cannot be provided on this distribution is
    reported and skipped; it never stops the theme from being installed.
    """
    planned = []
    for tool in wanted:
        if tool not in EXTRA_TOOLS:
            continue
        dest, packages, sources = EXTRA_TOOLS[tool]
        if _root_file_exists(esp_root / "EFI" / "tools" / dest, runner):
            continue
        source = next((Path(s) for s in sources if _root_file_exists(Path(s), runner)), None)
        if source is None:
            package = packages.get(manager or linux_package_manager() or "")
            if package is None:
                print(f"note: {tool}: no package for this distribution, skipped")
                continue
            try:
                if _package_is_exact(package, runner, manager):
                    install_packages([package], runner, manager)
            except ThemeError as exc:
                print(f"note: {tool}: {package} did not install ({exc})")
            source = next((Path(s) for s in sources if _root_file_exists(Path(s), runner)), None)
            fallback = ARCH_EFI_FALLBACK.get(tool)
            if source is None and fallback and (manager or linux_package_manager()) == "pacman":
                try:
                    _extract_from_arch(*fallback, runner)
                except ThemeError as exc:
                    print(f"note: {tool} was not added ({exc}), skipped")
                    continue
                source = next((Path(s) for s in sources if _root_file_exists(Path(s), runner)), None)
        if source is None:
            print(f"note: {tool}: package installed but no EFI file found, skipped")
            continue
        planned.append((source.as_posix(), dest))
    return tuple(planned)


def _check_extra_tool(source: str, dest: str) -> Path:
    allowed = {spec[0] for spec in EXTRA_TOOLS.values()}
    path = PurePosixPath(source)
    if dest not in allowed or not path.is_absolute() or ".." in path.parts:
        raise ThemeError(f"unsafe extra tool in plan: {source!r} -> {dest!r}")
    if not source.startswith(EXTRA_TOOL_ROOTS) or not source.casefold().endswith(".efi"):
        raise ThemeError(f"extra tool must be an .efi file from a system package: {source!r}")
    return Path(source)


def install_refind(
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    *,
    assume_yes: bool = False,
    interactive: bool = True,
    ask: Callable[[str], str] = input,
) -> None:
    """Install rEFInd with the distribution package and refind-install.

    Refuses when Secure Boot is on: an unsigned boot manager would not start,
    and the firmware would fall back to the old boot entry anyway.
    """
    if secure_boot_enabled():
        raise ThemeError(
            "rEFInd is not installed and Secure Boot is ON. An unsigned rEFInd would not start. "
            "Either turn Secure Boot off in the firmware settings and run this again, or install "
            f"rEFInd with shim/MOK signing yourself ({REFIND_DOWNLOAD}), then run this again"
        )
    if not assume_yes:
        question = (
            "rEFInd nie jest zainstalowany. Zainstalować go teraz (pakiet z dystrybucji + "
            "refind-install; obecny bootloader zostaje dostępny)? [t/N]: " if _polish() else
            "rEFInd is not installed. Install it now (distribution package + refind-install; "
            "your current boot loader stays available)? [y/N]: ")
        try:
            answer = ask(question) if interactive else ""
        except EOFError:
            answer = ""
        if answer.strip().casefold() not in {"y", "yes", "t", "tak"}:
            raise ThemeError(
                "rEFInd is required. Run again and answer 'y', or pass --install-refind, "
                f"or install it yourself: {REFIND_DOWNLOAD}"
            )
    if shutil.which("refind-install") is None:
        bootstrap_linux_dependencies(("refind",), runner)
    prefix = _sudo_prefix() if getattr(os, "geteuid", lambda: 1)() != 0 else []
    print("running refind-install...")
    try:
        result = runner(tuple([*prefix, "refind-install"]))
    except OSError as exc:
        raise ThemeError(f"cannot run refind-install: {exc}") from exc
    report = f"{result.stdout or ''}{result.stderr or ''}".strip()
    if report:
        print("\n".join(report.splitlines()[-12:]))
    if result.returncode != 0:
        raise ThemeError(f"refind-install failed (exit {result.returncode}): {report[-600:]}")


def run_linux_deploy(
    build: ThemeBuild,
    args,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    """Discover Linux boot targets and hand a validated plan to root."""
    if platform.system().casefold() != "linux":
        raise ThemeError("deployment is supported only on Linux")
    if not is_uefi_boot():
        raise ThemeError(
            "this PC was started in legacy BIOS (CSM) mode; rEFInd works only with UEFI. "
            "Switch the firmware to UEFI boot - the system itself must be installed in UEFI mode"
        )
    missing = missing_linux_dependencies()
    if missing:
        bootstrap_linux_dependencies(missing, runner)

    def scan():
        efi_text = _run_required(("efibootmgr", "-v"), runner)
        lsblk_text = _run_required(
            ("lsblk", "-J", "-b", "-o", "PATH,TYPE,PARTUUID,LABEL,PARTLABEL,SIZE,MOUNTPOINTS"),
            runner,
        )
        devices = parse_lsblk(lsblk_text)
        found = enrich_boot_entries(parse_efibootmgr(efi_text), devices)
        mounts = [Path(mount) for item in devices.values() for mount in _mount_points(item)]
        ordered = (*_refind_candidates(found), *(m / "EFI" / "refind" for m in mounts),
                   *(m / "EFI" / "BOOT" for m in mounts))
        refind_first = sorted(dict.fromkeys(ordered), key=lambda p: p.name.casefold() != "refind")
        return devices, found, tuple(refind_first)

    devices_map, entries, candidates = scan()
    try:
        refind_dir = find_refind_dir(args.refind_dir, candidates if args.refind_dir is None else ())
    except ThemeError:
        if args.refind_dir is not None or args.dry_run:
            raise
        install_refind(runner, assume_yes=args.install_refind, interactive=not args.non_interactive)
        devices_map, entries, candidates = scan()
        refind_dir = find_refind_dir(None, candidates)
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
    tools = () if args.dry_run else plan_extra_tools(
        getattr(args, "extra_tools", ()), refind_dir.parent.parent, runner)
    plan = DeploymentPlan(
        theme_source=build.output_dir,
        refind_dir=refind_dir,
        targets=tuple(targets),
        tools=tools,
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
        command = _sudo_prefix()
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


def _sudo_prefix() -> list[str]:
    """sudo, using the graphical password prompt when a launcher provides one."""
    return ["sudo", "-A"] if os.environ.get("SUDO_ASKPASS") else ["sudo"]


# --- Installing from Windows ---------------------------------------------------
# The ESP has no drive letter on Windows. Every EFI System Partition is given a
# temporary letter, the one holding rEFInd is used, and all letters are removed
# again afterwards - even if the install fails.

ESP_GPT_TYPE = "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}"
WINDOWS_ESP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Get-Partition | Where-Object { $_.GptType -eq '%s' } |
  ForEach-Object { '{0}:{1}:{2}' -f $_.DiskNumber, $_.PartitionNumber, ($_.DriveLetter -replace '\x00','') }
""" % ESP_GPT_TYPE


def _powershell(script: str, runner=run_command) -> subprocess.CompletedProcess[str]:
    return runner(("powershell", "-NoProfile", "-NonInteractive", "-Command", script))


def _windows_is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _free_drive_letters() -> list[str]:
    return [l for l in "ZYXWVUTSRQPONMLKJIHG" if not Path(f"{l}:\\").exists()]


def list_windows_esps(runner=run_command) -> list[tuple[int, int, str]]:
    """(disk, partition, current drive letter or '') for every ESP."""
    result = _powershell(WINDOWS_ESP_SCRIPT, runner)
    if result.returncode != 0:
        raise ThemeError(f"cannot list EFI partitions: {(result.stderr or result.stdout).strip()}")
    esps = []
    for line in (result.stdout or "").splitlines():
        parts = line.strip().split(":")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            esps.append((int(parts[0]), int(parts[1]), parts[2].strip()))
    return esps


def install_theme_windows(
    theme_source: Path,
    refind_dir: Path | None = None,
    *,
    dry_run: bool = False,
    runner=run_command,
) -> Path:
    """Copy a built theme into rEFInd on an ESP and activate it (Windows).

    Same guarantees as on Linux: only owned files are written, refind.conf gets
    a timestamped backup, and any failure rolls every file back.
    """
    _load_theme_state(theme_source)
    mounted: list[tuple[int, int, str]] = []
    try:
        if refind_dir is None:
            if not _windows_is_admin():
                raise ThemeError("installing to the EFI partition needs administrator rights")
            candidates: list[Path] = []
            free = _free_drive_letters()
            for disk, part, letter in list_windows_esps(runner):
                if not letter:
                    if not free:
                        raise ThemeError("no free drive letter to open the EFI partition")
                    letter = free.pop(0)
                    result = _powershell(
                        f"Add-PartitionAccessPath -DiskNumber {disk} -PartitionNumber {part} "
                        f"-AccessPath '{letter}:\\'", runner)
                    if result.returncode != 0:
                        print(f"skipping EFI partition {disk}/{part}: {(result.stderr or '').strip()}")
                        continue
                    mounted.append((disk, part, letter))
                root = Path(f"{letter}:\\")
                candidates += [root / "EFI" / "refind", root / "EFI" / "BOOT"]
                candidates += sorted(p for p in (root / "EFI").glob("*") if p.is_dir())
            try:
                refind_dir = find_refind_dir(None, candidates)
            except ThemeError as exc:
                raise ThemeError(
                    "rEFInd was not found on any EFI partition of this PC. Install rEFInd "
                    "first - the easiest way is to run this installer on your Linux system, which "
                    f"installs rEFInd by itself; on Windows follow {REFIND_DOWNLOAD} - then try again"
                ) from exc
        else:
            refind_dir = find_refind_dir(refind_dir, ())
        print(f"rEFInd found in: {refind_dir}")
        if dry_run:
            print(f"dry run: would copy the theme to {refind_dir / 'themes' / THEME_NAME} "
                  "and activate it in refind.conf")
            return refind_dir
        transaction = FileTransaction()
        try:
            copy_owned_theme(theme_source, refind_dir, transaction)
            config_path = refind_dir / "refind.conf"
            original = config_path.read_bytes()
            updated = update_managed_config(original)
            if updated != original:
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                transaction.write_bytes(
                    config_path, updated,
                    permanent_backup=refind_dir / f"refind.conf.ghoul-cyber-{stamp}.bak",
                )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        print("ghoul-cyber installed and activated in rEFInd")
        return refind_dir
    finally:
        for disk, part, letter in mounted:
            _powershell(
                f"Remove-PartitionAccessPath -DiskNumber {disk} -PartitionNumber {part} "
                f"-AccessPath '{letter}:\\'", runner)


def run_windows_install(build: ThemeBuild, args) -> None:
    """Run the privileged part elevated (UAC) and stream its log back."""
    if _windows_is_admin() or args.refind_dir is not None:
        install_theme_windows(build.output_dir, args.refind_dir, dry_run=args.dry_run)
        return
    log = Path(tempfile.gettempdir()) / f"ghoul-cyber-install-{os.getpid()}.log"
    inner = [str(Path(__file__).resolve()), "--_windows-install", str(build.output_dir),
             "--_log", str(log)] + (["--dry-run"] if args.dry_run else [])
    quoted = ",".join("'" + a.replace("'", "''") + "'" for a in inner)
    script = (
        f"$p = Start-Process -FilePath '{sys.executable}' -ArgumentList {quoted} "
        "-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode"
    )
    print("asking Windows for administrator rights (UAC)...", flush=True)
    result = _powershell(script)
    if log.is_file():
        print(log.read_text(encoding="utf-8", errors="replace"), end="")
        log.unlink()
    if result.returncode != 0:
        raise ThemeError(
            "installation was cancelled or failed; nothing was changed"
            if result.returncode in (1, 1223) and not log.exists() else
            f"elevated installer exited with {result.returncode}"
        )


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
    given = list(argv if argv is not None else sys.argv[1:])
    if args._windows_install is not None:
        # Elevated child started by run_windows_install: log to a file the
        # parent (non-admin) process reads back afterwards.
        log = open(args._log, "w", encoding="utf-8") if args._log else sys.stdout
        sys.stdout = sys.stderr = log
        try:
            install_theme_windows(args._windows_install, dry_run=args.dry_run)
            return 0
        except (OSError, ThemeError, ValueError) as exc:
            print(f"ghoul-cyber: {exc}")
            return 2
        finally:
            log.flush()
    try:
        if args.list_themes:
            for name in (THEME_NAME, *list_skins()):
                print(name)
            return 0
        config_path = None if args.no_config else (
            args.config or (
                script_dir / DEFAULT_CONFIG_NAME
                if (script_dir / DEFAULT_CONFIG_NAME).is_file() else None
            )
        )
        options = load_options(config_path)
        if config_path is not None:
            print(f"using customisation: {config_path}")
            raw = read_json_file(config_path)
            raw_theme = raw.get("theme") if isinstance(raw, Mapping) else None
            if raw_theme and not any(a.startswith("--theme") for a in given):
                args.theme = str(raw_theme)
            if not any(a.startswith("--resolution") for a in given):
                args.resolution = parse_resolution(options["layout.resolution"])
        if args.check_config:
            configure_geometry(*icon_geometry(options, args.resolution),
                               options["layout.selection_scale"])
            print(f"theme: {args.theme}   resolution: {args.resolution}   "
                  f"icons: {BIG_ICON_SIZE}/{SMALL_ICON_SIZE} px")
            print(render_theme_conf(options, args.resolution), end="")
            print("configuration OK")
            return 0
        skin = None if args.theme == THEME_NAME else load_skin(args.theme)
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
            skin=skin,
            options=options,
        )
        should_deploy = (
            platform.system().casefold() == "linux" and not args.build_only
        )
        if should_deploy:
            args.extra_tools = options["refind.extra_tools"]
            run_linux_deploy(build, args)
        elif platform.system() == "Windows" and args.install and not args.build_only:
            run_windows_install(build, args)
        print(f"ghoul-cyber ready: {build.output_dir}")
        return 0
    except (OSError, ThemeError, ValueError) as exc:
        print(f"ghoul-cyber: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
