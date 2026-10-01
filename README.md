# Ghoul Cyber – rEFInd Bootloader Theme

**🇬🇧 English** | [🇵🇱 Polski](README.pl.md)

> **A modern cyberpunk theme for the rEFInd boot manager, designed for 4K OLED / QHD / FHD panels, with automatic hardware detection and one-command deployment.**

[![GitHub Releases](https://img.shields.io/badge/GitHub-Releases-blue?style=for-the-badge&logo=github)](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)
[![License](https://img.shields.io/badge/License-GCPL--1.0-orange?style=for-the-badge)](LICENSE)
[![Theme Studio](https://img.shields.io/badge/App-Theme%20Studio-FF003C?style=for-the-badge&logo=github)](https://github.com/Dismonder/ghoul-cyber-theme-studio)

> 🖥️ **New: [Ghoul Cyber – Theme Studio](https://github.com/Dismonder/ghoul-cyber-theme-studio)** — the app for this theme. Pick one of 18 themes, tune it with a live preview and build or install it with one click, on Linux and Windows. **[⬇️ Download](https://github.com/Dismonder/ghoul-cyber-theme-studio/releases/latest)**

![Ghoul Cyber Preview](full_bootloader_preview_1080p.png)

---

## ☕ Support the Author

If you like the theme, it looks great on your screen, or it saved you some configuration time — you can buy me a virtual coffee:

[![Buy me a coffee on BuyCoffee.to](https://img.shields.io/badge/BuyCoffee.to-Buy%20a%20coffee%20(BLIK)-37AC49?style=for-the-badge&logo=buy-me-a-coffee&logoColor=white)](https://buycoffee.to/dismonder)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/dismonder)
[![Become a Patron on Patronite](https://img.shields.io/badge/Patronite-Become%20a%20Patron-EC1D24?style=for-the-badge)](https://patronite.pl/Dismonder)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Dismonder-EA4AAA?style=for-the-badge&logo=github-sponsors&logoColor=white)](https://github.com/sponsors/Dismonder)

- 🌍 **[Ko-fi.com/dismonder](https://ko-fi.com/dismonder)** – international support (PayPal / cards, 0% platform fee).
- 🐙 **[GitHub Sponsors (Dismonder)](https://github.com/sponsors/Dismonder)** – GitHub's own sponsorship program.
- 🇵🇱 **[BuyCoffee.to/dismonder](https://buycoffee.to/dismonder)** – quick coffee in PLN (BLIK, card, Apple Pay / Google Pay).
- 🏆 **[Patronite.pl/Dismonder](https://patronite.pl/Dismonder)** – monthly patronage / subscription.

---

## 👤 Author & Signature

- **Author / Creator:** **Dismonder**
- **Releases:** [Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)
- **Copyright:** © 2026 Dismonder. All Rights Reserved.
- **License:** [Ghoul Cyber Protective License (GCPL-1.0)](LICENSE)

---

## 📜 License Summary

This project is covered by a dedicated protective license, **GCPL-1.0 (Ghoul Cyber Protective License)**:

✅ **You MAY:**
- Download, install and use the theme free of charge on your own devices (desktops, laptops, handheld consoles).
- Modify the files and configuration for your own private use (e.g. custom resolutions, custom EFI labels).

❌ **You may NOT:**
- **REDISTRIBUTE IT UNDER YOUR OWN NAME:** publishing, sharing or re-uploading the theme under your own name, initials, nickname or brand, or presenting it as your own work, is strictly prohibited.
- **REMOVE THE AUTHOR'S DETAILS:** removing or obscuring the `Dismonder` signature, copyright notices or the license file from the code, configuration files and documentation is prohibited.
- **USE IT COMMERCIALLY:** selling the theme, charging for it, or bundling it into paid commercial packages without the author's written permission is prohibited.

The full, legally binding license text in Polish and English is in the [LICENSE](LICENSE) file.

---

## 🎮 Features

- **Native 4K UHD geometry (3840×2160):**
  - Large 768×768 px OS icons (ideal for 4K / OLED screens).
  - 240×240 px tool icons, 864×864 px / 270×270 px selection frames.
  - Support for 1440p (2560×1440), 1080p (1920×1080) and other 16:9 resolutions.
- **Fully automated installer (`build_and_deploy_theme.py`):**
  - **Linux (any major distribution):** fully automatic — installs missing packages with your package manager, installs rEFInd itself if it is missing (after asking), maps UEFI NVRAM entries to the right boot cards (*Windows DEV*, *Windows Gaming*, *CachyOS* — each only if you have it; Linux-only PCs are fine), installs the assets to `/boot/efi/EFI/refind/themes/ghoul-cyber` and safely updates `refind.conf` (with a transactional backup and rollback).
  - **Windows:** with `--install` (or one click in Theme Studio) installs the theme — and when the PC has no rEFInd, first downloads it (SHA-256 checked), copies it to the EFI partition and adds it to the boot menu in front of Windows. Without `--install` it builds a ready-to-copy package in `dist/ghoul-cyber`.
- **Asset generator with live telemetry:**
  - Automatically prints your CPU, RAM, GPU, NVMe drive and Secure Boot status onto the wallpaper.
  - Generates the full set of tool and OS icons (Windows, CachyOS, Linux, Arch, Debian, Ubuntu, Fedora, macOS and more).

---

## ✅ Requirements

| | Requirement |
| :--- | :--- |
| Firmware | PC booting in **UEFI** mode (not Legacy BIOS / CSM) — check with `ls /sys/firmware/efi/efivars` |
| Linux | Any distribution with `pacman` (Arch, CachyOS, EndeavourOS, Manjaro), `apt` (Debian, Ubuntu, Mint, Pop!_OS), `dnf` (Fedora), `zypper` (openSUSE), `xbps` (Void) or `apk` (Alpine) — missing packages are installed automatically |
| Python | **Python 3** (Pillow is installed automatically on Linux) |
| Boot manager | **rEFInd** — if it is missing, the installer offers to install it for you |

### No rEFInd yet?

Nothing to do by hand: when rEFInd is not found, the installer asks *"rEFInd is not installed. Install it now?"*, installs the distribution package and runs `refind-install` (your current boot loader stays in the firmware menu). Use `--install-refind` to skip the question.

| Situation | What happens |
| :--- | :--- |
| PC started in legacy BIOS / CSM | stops with an explanation — rEFInd needs UEFI |
| **Secure Boot is on** | stops with an explanation — an unsigned rEFInd would not start; turn Secure Boot off or install rEFInd with shim/MOK yourself |
| openSUSE | rEFInd is not in the official repositories — the installer points you to the [official download](https://www.rodsbooks.com/refind/getting.html) |
| No Windows / another Linux than CachyOS | fine — the theme is installed and rEFInd picks the matching icons (`os_linux`, `os_ubuntu`, `os_fedora`, …) itself |
| **Only Windows on the PC** | fine — the installer adds rEFInd from Windows by itself (one click in Theme Studio), see the [step-by-step guide](#-only-windows-on-your-pc-step-by-step-guide) |

The installer looks for rEFInd in `/boot/EFI/refind`, `/boot/efi/EFI/refind`, `/efi/EFI/refind` and on every mounted partition (or pass `--refind-dir`).

---

## 🚀 Quick Start

> 📦 **Ready-made releases:** pre-built theme packages (4K / 1440p / 1080p) and the full installer archive are available on the **[Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)** page.

### 1. Get the repository

```bash
git clone https://github.com/Dismonder/refind-theme-ghoul-cyber.git
cd refind-theme-ghoul-cyber
```

### 2. Dry run (recommended)
Checks your environment, reads the telemetry and inspects the rEFInd loader without changing anything:

```bash
python3 build_and_deploy_theme.py --dry-run
```

If you have two Windows installations, the script asks which one is the *DEV* one. At the end it prints the deployment plan (which boot entry gets which icon and where rEFInd lives).

### 3. Deploy on CachyOS / Linux (automatic)
Running the script with no arguments performs full detection, builds the 4K theme and activates it in rEFInd:

```bash
python3 build_and_deploy_theme.py
```

*The script asks for your `sudo` password (only for writing to the ESP) and installs any missing packages (`python-pillow`, `efibootmgr`, fonts) when needed.* After a reboot, the new theme is active.

### 4. Build the theme package only (Build-Only / Windows)
On Windows, or when you only want to generate the theme files without touching the ESP:

```bash
python3 build_and_deploy_theme.py --build-only
```
The files end up in `dist/ghoul-cyber/`.

---

## 🪟 Manual install on Windows

Without `--install` the script never touches the boot partition on Windows. If you prefer to do it all by hand, build the package (`py build_and_deploy_theme.py --build-only`) **or** download a ready-made `ghoul-cyber-v*.zip` from [Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases), then in a terminal **running as Administrator**:

```powershell
mountvol S: /S
robocopy dist\ghoul-cyber S:\EFI\refind\themes\ghoul-cyber /E
notepad S:\EFI\refind\refind.conf
mountvol S: /D
```

In `refind.conf` append at the very end:

```
include themes/ghoul-cyber/theme.conf
```

> 💡 With a manual install, also check `themes/ghoul-cyber/theme.conf`: the `resolution` line must match your monitor, and the sample `menuentry "Windows 11 Gaming"` block can be removed or adapted to your own disks.

---

## 💻 Only Windows on your PC? Step-by-step guide

You don't need Linux to get this boot screen — **one click in Theme Studio does everything**. **Your files are safe:** nothing on the Windows drive is formatted, shrunk or moved. Only about 1 MB of rEFInd plus the theme goes onto the hidden EFI partition, and Windows stays in the BIOS boot menu as a fallback.

### Step 1 — Save your BitLocker recovery key (just in case)
Go to https://aka.ms/myrecoverykey, find your key and **write it down** or take a photo of it. The program pauses BitLocker itself before every boot change, so you should not need the key — but it is good to have.

### Step 2 — Click "Build and install"
Download **[Theme Studio](https://github.com/Dismonder/ghoul-cyber-theme-studio/releases/latest)**, pick a theme, set the resolution **to match your screen** (Settings → System → Display) and click **BUILD AND INSTALL**. Confirm the administrator prompt. The program then:

1. checks that the PC runs in **UEFI** mode and that **Secure Boot** is off,
2. downloads the official rEFInd 0.14.2 and checks its SHA-256 checksum,
3. copies it to the EFI partition (next to Windows, nothing is overwritten),
4. pauses BitLocker for the next 2 restarts (Windows turns it back on by itself),
5. adds a **new** *rEFInd* boot entry in front of *Windows Boot Manager* (which stays untouched),
6. installs and activates the theme.

<sub>Prefer the command line? `py build_and_deploy_theme.py --resolution 1920x1080 --install` (use your own resolution).</sub>

### Step 3 — Only if the program says Secure Boot is on
rEFInd is not signed by Microsoft, so it would not start with Secure Boot on — the program then installs nothing and only pauses BitLocker right away, so that turning Secure Boot off does not end with a recovery-key prompt.

1. Open the BIOS/UEFI settings. Easiest: Command Prompt as administrator → `shutdown /r /fw /t 0` (or press `F2`, `F10`, `Del` or `Esc` right after power-on).
2. Find **Secure Boot**, set it to **Disabled**, then save and exit (usually `F10`).
3. Once Windows is back, click **BUILD AND INSTALL** again.

If the program says the PC runs in **Legacy BIOS** mode, rEFInd will not work on it.

### Step 4 — Restart 🎉
You will see the Ghoul Cyber screen with a Windows tile. Press Enter (or wait a few seconds) and Windows starts as usual.

### Something wrong?
- **Windows starts instead of rEFInd:** move *rEFInd* to the top of the boot order in the BIOS. Some laptops (often HP) ignore the order set from Windows — then add an entry in the BIOS by hand with the path `\EFI\refind\refind_x64.efi` (HP: *Customized Boot*). Do not rename or replace Microsoft's files.
- **Black screen or rEFInd does not start:** right after power-on press the boot-menu key (`F12`, `F9` or `Esc`) and choose **Windows Boot Manager** — Windows starts normally.
- **After a big Windows update Windows starts directly again:** click **BUILD AND INSTALL** once more — the program puts rEFInd first again.
- **No internet:** download `refind-bin-0.14.2.zip` from the [official rEFInd page](https://www.rodsbooks.com/refind/getting.html) and pass it: `py build_and_deploy_theme.py --install --refind-zip refind-bin-0.14.2.zip`.
- **Undo everything:** `py build_and_deploy_theme.py --remove-refind` removes the *rEFInd* boot entry and the `EFI\refind` folder (theme included) — only if this program installed them. Then you can turn Secure Boot back on in the BIOS.

---

## ⚙️ Main CLI Options

| Option | Description |
| :--- | :--- |
| `--resolution WIDTHxHEIGHT` | Target resolution (default `3840x2160`, also supports `2560x1440`, `1920x1080`) |
| `--build-only` | Builds the theme into `dist/` without touching the ESP or the rEFInd config |
| `--dry-run` | Checks the environment and prints the planned operations without modifying the disk |
| `--non-interactive` | Fails instead of asking which Windows installation is DEV |
| `--install-refind` | Linux: install rEFInd without asking when it is missing |
| `--source-dir PATH` | Path to the directory with the raw source graphics |
| `--output-dir PATH` | Output path for the generated theme |
| `--refind-dir PATH` | Path to the rEFInd directory on the mounted ESP |
| `--cpu`, `--gpu`, `--ram`, `--nvme` | Manually override the telemetry text printed on the wallpaper |
| `--secure-boot {auto,on,off}` | Manually set the Secure Boot indicator |
| `--font PATH` | Path to a custom TTF/OTF font |
| `--theme NAME` | Visual theme from `themes/` (default `ghoul-cyber`) |
| `--list-themes` | Prints the available themes |
| `--config PATH` | Settings file (default: `boot-config.json` next to the script, if present) |
| `--check-config` | Validates the settings and prints the generated `theme.conf` |
| `--install` | Windows: also install the built theme into rEFInd (asks for UAC); installs rEFInd itself first if it is missing |
| `--refind-zip FILE` | Windows: use a downloaded `refind-bin-0.14.2.zip` instead of downloading it |
| `--remove-refind` | Windows: remove the rEFInd this program installed (boot entry, `EFI\refind` and the theme) |

---

## 🖥️ Theme Studio — build your own boot screen

**Theme Studio** — the app that lets you pick a theme, tune it with a **live preview** and build or install it in one click (Polish / English, Linux and Windows) — lives in its own repository and uses this one as its engine:

### 👉 [Dismonder/ghoul-cyber-theme-studio](https://github.com/Dismonder/ghoul-cyber-theme-studio) · [⬇️ download](https://github.com/Dismonder/ghoul-cyber-theme-studio/releases/latest)

Everything it does is also available from the command line of this repository (`build_and_deploy_theme.py`, settings in `boot-config.json` — below).

---

## 🧩 Customisation (`boot-config.json`)

One JSON file controls the layout, what is shown and how rEFInd behaves. Theme Studio writes it for you; you can also edit it by hand — only the values you change need to be there. See [`boot-config.example.json`](boot-config.example.json).

| Section | What you can change |
| :--- | :--- |
| `layout` | screen resolution (icons scale with it automatically), how many system tiles are visible at once (the rest scroll by one), scroll arrows on/off (off by default), tile and tool icon size, selection frame size, artwork scale / brightness, how much the art is dimmed under the UI |
| `hud` | accent colour, title / tagline / kanji column (on/off and own text), which hardware rows are shown, up to 4 own text rows, status line and its text, decorations, key-hint bar, scanlines, glitch bars, the original Ghoul overlay |
| `cards` | numbers on the OS tiles on/off, and their order (empty = automatic: your menu entries first, then the systems found on this PC; tiles left out of the list get no number) |
| `refind` | timeout, default entry (`+` = last booted), how many tools the bottom row shows at most (most important first — rEFInd never scrolls that row), which tools are shown (default: BIOS, reboot, power, about, boot order, hidden entries + every tool that exists), extra tools to add from your distribution's packages into `EFI/tools` (EFI Shell: Arch/CachyOS, Debian/Ubuntu; MemTest86+: Arch, Debian/Ubuntu — CachyOS has no EFI build), hidden UI elements, where to scan, mouse / touch, skipped folders and files, maximum number of entries |
| `entries` | your own menu entries: name, tile (`cachyos`, `win_dev`, `win_game`, `windows`, `linux`, …), EFI loader, partition and kernel options |

```bash
python3 build_and_deploy_theme.py --check-config          # validate + print the generated theme.conf
python3 build_and_deploy_theme.py --config my-look.json    # use another settings file
```

Every value is validated (type, range, allowed characters) before anything is built, and the file is picked up automatically when it sits next to the script.

> 🔢 The index numbers are not baked into the tiles any more: the builder finds the number painted on each card, paints it out and draws the right one (same place, size, weight and colour) — so a Linux-only PC gets `01`, not `03`.

> 🐧 Every theme also ships a generic **LINUX** tile (`card_linux.png` → `icons/os_linux.png`) for distributions other than CachyOS; `card_linux_gnu.png` keeps the earlier "GNU // LINUX" variant.

> ℹ️ Earlier versions hard-coded a `Windows 11 Gaming` menu entry pointing at one specific disk. It is gone: add your own through **Menu entries** (or `entries`) if you need it.

---

## 🎨 Alternative Themes

Besides the original Ghoul Cyber look, seventeen anime- and game-inspired OLED variants are included. Each one has its own AI artwork, OS cards and accent color. The installer, the telemetry text and the rEFInd layout are the same for all of them, and the theme is always installed as `themes/ghoul-cyber`.

> 🎭 **Fan art.** These seventeen themes are unofficial, non-commercial fan art inspired by popular anime and games — not affiliated with or endorsed by their creators or rights holders; all characters and trademarks belong to their owners. Theme Studio marks them as *FAN ART*. Rights holders can request removal via an issue — see [`themes/FAN-ART.md`](themes/FAN-ART.md).

| Theme | Accent | Vibe |
| :--- | :--- | :--- |
| `cursed-domain` | violet `#A020F0` | occult sorcery, cursed energy, broken torii |
| `chainsaw-devil` | orange `#FF6A00` | devil-hunter horror, chainsaws, ink splatter |
| `titan-fall` | amber `#FFB21A` | colossal giant over the wall, grappling soldier |
| `mecha-unit` | green `#7CFF3A` | 90s biomechanical mecha, hex warning HUD |
| `demon-blade` | cyan `#2BB8FF` | Taisho swordsman, ukiyo-e water dragon, wisteria |
| `neon-ronin` | magenta `#FF2E97` | cyberpunk ronin with oni mask, neon rain |
| `void-horizon` | gold `#FFC24B` | black hole, lone astronaut |
| `shadow-monarch` | indigo `#5B6CFF` | shadow sovereign, dungeon gate rift |
| `dragon-ki` | yellow `#FFE23B` | martial-arts power-up, ki aura, lightning |
| `soul-reaper` | mint `#19FFC2` | cracked hollow mask, cleaver sword, black butterflies |
| `frost-mage` | ice blue `#9FE8FF` | elf mage, ice magic circle, snowy ruins |
| `sakura-storm` | pink `#FF8FC7` | samurai under a full moon, cherry-blossom storm |
| `elden-lord` | gold `#E8B84A` | souls-like knight, golden great tree, grace |
| `night-city` | yellow `#FCEE0A` | cyberpunk merc, yellow-collar jacket, megacity, glitch |
| `hell-slayer` | hellfire `#FF4A1C` | armored demon slayer, skulls, lava |
| `hollow-vessel` | periwinkle `#A8B8FF` | tiny horned knight, bug kingdom caverns, bench |
| `wolf-witcher` | silver `#D9E1EC` | white-haired monster hunter, wolf medallion, two swords |

```bash
python3 build_and_deploy_theme.py --theme cursed-domain
```

A preview of each theme is in `themes/<name>/preview.jpg`. To make your own, add a folder `themes/<name>/` containing `art.png`/`art.jpg` (16:9, artwork in the top-right and bottom-left corners on pure black), an optional `selection_item_linux/windev/wingame.png` card set, and a `theme.json`:

```json
{ "accent": "#A020F0", "title": "CURSED_DOMAIN_v1.0", "kanji": "呪術核", "tagline": "[ DOMAIN :: EXPANSION ]", "art_brightness": 1.0 }
```

---

## 🛠️ Troubleshooting

**Windows or GRUB boots instead of rEFInd** — move rEFInd to the front of the UEFI boot order (or do it in your BIOS):

```bash
efibootmgr                         # find the "rEFInd Boot Manager" entry number
sudo efibootmgr -o 0001,0000,0003  # put it first
```

**An OS is missing from the menu** — `theme.conf` hides `EFI/refind` and `EFI/BOOT` via `dont_scan_dirs` (set in Theme Studio → Behaviour). Remove the entry you need from that line.

---

## ♻️ Uninstall

Everything the installer changes is backed up:

1. Remove the block between `# BEGIN ghoul-cyber managed theme` and `# END ghoul-cyber managed theme` from `refind.conf` — **or** restore the backup `refind.conf.ghoul-cyber-<date>.bak` from the rEFInd directory.
2. Restore the original OS icons from the `*.png.ghoul-cyber.bak` files next to your OS loaders.
3. Delete the `EFI/refind/themes/ghoul-cyber` directory.

---

## 🧪 Test Suite

The project ships with unit tests covering the build contract, asset geometry, transactional ESP writes and UEFI parsing:

```bash
python3 -m pytest tests
```

`tests/test_robustness.py` is a randomised stress test ("fuzzing"): garbage settings, broken JSON and images, odd `efibootmgr` / `lsblk` / PowerShell output. Every case must either work or stop with a clear message. Make it heavier and replay a failure by its seed:

```bash
FUZZ_ROUNDS=500 FUZZ_SEED=1234 python3 -m pytest tests/test_robustness.py
```
