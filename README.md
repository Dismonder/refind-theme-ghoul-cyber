# Ghoul Cyber – rEFInd Bootloader Theme

**🇬🇧 English** | [🇵🇱 Polski](README.pl.md)

> **A modern cyberpunk theme for the rEFInd boot manager, designed for 4K OLED / QHD / FHD panels, with automatic hardware detection and one-command deployment.**

[![GitHub Releases](https://img.shields.io/badge/GitHub-Releases-blue?style=for-the-badge&logo=github)](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)
[![License](https://img.shields.io/badge/License-GCPL--1.0-orange?style=for-the-badge)](LICENSE)

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
  - **Linux (CachyOS / Arch / others):** fully automatic — finds rEFInd on the ESP, maps UEFI NVRAM entries to the right boot cards (*Windows DEV*, *Windows Gaming*, *CachyOS*), installs the assets to `/boot/efi/EFI/refind/themes/ghoul-cyber` and safely updates `refind.conf` (with a transactional backup and rollback).
  - **Windows:** build-only mode that produces a ready-to-copy package in `dist/ghoul-cyber`.
- **Asset generator with live telemetry:**
  - Automatically prints your CPU, RAM, GPU, NVMe drive and Secure Boot status onto the wallpaper.
  - Generates the full set of tool and OS icons (Windows, CachyOS, Linux, Arch, Debian, Ubuntu, Fedora, macOS and more).

---

## ✅ Requirements

| | Requirement |
| :--- | :--- |
| Firmware | PC booting in **UEFI** mode (not Legacy BIOS / CSM) — check with `ls /sys/firmware/efi/efivars` |
| Linux | **CachyOS / Arch** — fully automatic (missing packages are installed via `pacman`). Other distros: install `efibootmgr` and `util-linux` first |
| Python | **Python 3** + **Pillow** |
| Boot manager | **rEFInd** installed on the EFI System Partition (ESP) |

### Installing rEFInd (if you don't have it yet)

```bash
# CachyOS / Arch
sudo pacman -S refind
sudo refind-install

# Ubuntu / Debian
sudo apt install refind
```

The installer looks for rEFInd in `/boot/EFI/refind`, `/boot/efi/EFI/refind` and `/efi/EFI/refind` (or pass `--refind-dir`).

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

On Windows the script never touches the boot partition. Build the package (`py build_and_deploy_theme.py --build-only`) **or** download a ready-made `ghoul-cyber-v*.zip` from [Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases), then in a terminal **running as Administrator**:

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

## ⚙️ Main CLI Options

| Option | Description |
| :--- | :--- |
| `--resolution WIDTHxHEIGHT` | Target resolution (default `3840x2160`, also supports `2560x1440`, `1920x1080`) |
| `--build-only` | Builds the theme into `dist/` without touching the ESP or the rEFInd config |
| `--dry-run` | Checks the environment and prints the planned operations without modifying the disk |
| `--non-interactive` | Fails instead of asking which Windows installation is DEV |
| `--source-dir PATH` | Path to the directory with the raw source graphics |
| `--output-dir PATH` | Output path for the generated theme |
| `--refind-dir PATH` | Path to the rEFInd directory on the mounted ESP |
| `--cpu`, `--gpu`, `--ram`, `--nvme` | Manually override the telemetry text printed on the wallpaper |
| `--secure-boot {auto,on,off}` | Manually set the Secure Boot indicator |
| `--font PATH` | Path to a custom TTF/OTF font |

---

## 🛠️ Troubleshooting

**Windows or GRUB boots instead of rEFInd** — move rEFInd to the front of the UEFI boot order (or do it in your BIOS):

```bash
efibootmgr                         # find the "rEFInd Boot Manager" entry number
sudo efibootmgr -o 0001,0000,0003  # put it first
```

**An OS is missing from the menu** — `theme.conf` hides some directories via `dont_scan_dirs` (e.g. `EFI/ubuntu`). Remove the entry you need from that line.

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
