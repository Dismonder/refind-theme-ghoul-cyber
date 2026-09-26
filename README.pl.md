# Ghoul Cyber – rEFInd Bootloader Theme

[🇬🇧 English](README.md) | **🇵🇱 Polski**

> **Nowoczesny, cyberpunkowy motyw dla bootloadera rEFInd zaprojektowany z myślą o panelach 4K OLED / QHD / FHD z automatyczną detekcją i wdrożeniem.**

[![GitHub Releases](https://img.shields.io/badge/GitHub-Releases-blue?style=for-the-badge&logo=github)](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)
[![Licencja](https://img.shields.io/badge/Licencja-GCPL--1.0-orange?style=for-the-badge)](LICENSE)

![Ghoul Cyber Preview](full_bootloader_preview_1080p.png)

---

## ☕ Wesprzyj projekt (Support the Author)

Jeśli motyw przypadł Ci do gustu, świetnie wygląda na Twoim ekranie lub zaoszczędził Ci konfiguracji – możesz docenić pracę i postawić wirtualną kawę:

[![Postaw kawę na BuyCoffee.to](https://img.shields.io/badge/BuyCoffee.to-Postaw%20kawę%20(BLIK)-37AC49?style=for-the-badge&logo=buy-me-a-coffee&logoColor=white)](https://buycoffee.to/dismonder)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/dismonder)
[![Zostań Patronem na Patronite](https://img.shields.io/badge/Patronite-Zostań%20Patronem-EC1D24?style=for-the-badge)](https://patronite.pl/Dismonder)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Dismonder-EA4AAA?style=for-the-badge&logo=github-sponsors&logoColor=white)](https://github.com/sponsors/Dismonder)

- 🇵🇱 **[BuyCoffee.to/dismonder](https://buycoffee.to/dismonder)** – szybka kawa w PLN (BLIK, karta, Apple Pay / Google Pay).
- 🌍 **[Ko-fi.com/dismonder](https://ko-fi.com/dismonder)** – wsparcie zagraniczne (PayPal / karty, 0% prowizji platformy).
- 🏆 **[Patronite.pl/Dismonder](https://patronite.pl/Dismonder)** – comiesięczne wsparcie patronackie / subskrypcja.
- 🐙 **[GitHub Sponsors (Dismonder)](https://github.com/sponsors/Dismonder)** – bezpośredni program sponsoringu GitHub.

---

## 👤 Autor i Podpis (Author & Signature)

- **Autor / Creator:** **Dismonder**
- **Wydania / Releases:** [Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)
- **Copyright:** © 2026 Dismonder. Wszystkie prawa zastrzeżone / All Rights Reserved.
- **Licencja:** [Ghoul Cyber Protective License (GCPL-1.0)](LICENSE)

---

## 📜 Licencja (License Summary)

Projekt objęty jest dedykowaną licencją ochronną **GCPL-1.0 (Ghoul Cyber Protective License)**:

✅ **Co MOŻESZ robić:**
- Bezpłatnie pobierać, instalować i używać motywu na własnych urządzeniach (komputery stacjonarne, laptopy, konsole handheld).
- Modyfikować pliki i konfigurację na własny, prywatny użytek (np. własne rozdzielczości, własne etykiety EFI).

❌ **Czego KATEGORYCZNIE NIE WOLNO robić:**
- **ZAKAZ ROZPOWSZECHNIANIA POD WŁASNYMI INICJAŁAMI / NAZWISKIEM:** Zabrania się publikowania, udostępniania i re-uploadu motywu pod własnym nazwiskiem, inicjałami, pseudonimem, marką lub jako rzekomo własnego projektu (bezwzględny zakaz przywłaszczania autorstwa).
- **ZAKAZ USUWANIA DANYCH AUTORA:** Zabrania się usuwania lub zamazywania podpisu, pseudonimu `Dismonder`, not prawno-autorskich i pliku licencji z kodu, plików konfiguracyjnych i dokumentacji.
- **ZAKAZ UŻYTKU KOMERCYJNEGO:** Zabrania się sprzedaży motywu, pobierania za niego opłat lub dołączania go do płatnych pakietów komercyjnych bez pisemnej zgody autora.

Pełny, prawnie wiążący tekst licencji w języku polskim i angielskim znajduje się w pliku [LICENSE](LICENSE).

---

## 🎮 Kluczowe cechy (Features)

- **Natywna geometria 4K UHD (3840×2160):**
  - Duże ikony systemowe 768×768 px (idealne na ekrany 4K / OLED).
  - Narzędzia funkcyjne 240×240 px, ramki wyboru 864×864 px / 270×270 px.
  - Obsługa rozdzielczości 1440p (2560×1440) oraz 1080p (1920×1080) i innych formatów 16:9.
- **W pełni zautomatyzowany instalator (`build_and_deploy_theme.py`):**
  - **Linux (CachyOS / Arch / inne):** Pełny automat — wykrywa instalację rEFInd na ESP, mapuje wpisy UEFI NVRAM na właściwe karty rozruchowe (*Windows DEV*, *Windows Gaming*, *CachyOS*), instaluje assety do `/boot/efi/EFI/refind/themes/ghoul-cyber` i bezpiecznie aktualizuje `refind.conf` (z transakcyjnym backupem i rollbackiem).
  - **Windows:** Tryb build-only generujący gotową paczkę do katalogu `dist/ghoul-cyber`.
- **Generator assetów z dynamiczną telemetrią:**
  - Automatyczne nakładanie informacji o procesorze (CPU), pamięci RAM, karcie graficznej (GPU), dysku NVMe i stanie Secure Boot na tapetę tła.
  - Generowanie kompletnego zestawu ikon narzędziowych i systemowych (Windows, CachyOS, Linux, Arch, Debian, Ubuntu, Fedora, macOS i inne).

---

## ✅ Wymagania (Requirements)

| | Wymaganie |
| :--- | :--- |
| Firmware | Rozruch w trybie **UEFI** (nie Legacy BIOS / CSM) — sprawdzisz przez `ls /sys/firmware/efi/efivars` |
| Linux | **CachyOS / Arch** — pełna automatyka (brakujące pakiety doinstalowane przez `pacman`). Inne dystrybucje: najpierw zainstaluj `efibootmgr` i `util-linux` |
| Python | **Python 3** + **Pillow** |
| Bootloader | **rEFInd** zainstalowany na partycji EFI (ESP) |

### Instalacja rEFInd (jeśli jeszcze go nie masz)

```bash
# CachyOS / Arch
sudo pacman -S refind
sudo refind-install

# Ubuntu / Debian
sudo apt install refind
```

Instalator szuka rEFInd w `/boot/EFI/refind`, `/boot/efi/EFI/refind` oraz `/efi/EFI/refind` (albo podaj `--refind-dir`).

---

## 🚀 Szybki start (Quick Start)

> 📦 **Gotowe wydania:** Gotowe, spakowane archiwa motywu (4K / 1440p / 1080p) i instalatora możesz również pobrać bezpośrednio z zakładki **[Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases)**.

### 1. Pobranie repozytorium

```bash
git clone https://github.com/Dismonder/refind-theme-ghoul-cyber.git
cd refind-theme-ghoul-cyber
```

### 2. Tryb symulacji (Dry-Run) — zalecany
Pozwala sprawdzić zaplanowane działania, odczytać telemetrię i zbadać loader rEFInd bez wprowadzania jakichkolwiek zmian:

```bash
python3 build_and_deploy_theme.py --dry-run
```

Jeśli masz dwie instalacje Windows, skrypt zapyta, która z nich to *DEV*. Na końcu wypisze plan wdrożenia (który wpis dostanie którą ikonę i gdzie leży rEFInd).

### 3. Wdrożenie na CachyOS / Linux (automatyczne)
Uruchomienie skryptu bez argumentów wykonuje pełną detekcję, budowę motywu 4K oraz aktywację w rEFInd:

```bash
python3 build_and_deploy_theme.py
```

*Skrypt w razie potrzeby zapyta o hasło `sudo` (tylko do zapisu na ESP) i automatycznie uzupełni brakujące pakiety (`python-pillow`, `efibootmgr`, fonty).* Po restarcie nowy motyw jest aktywny.

### 4. Budowa samej paczki motywu (Build-Only / Windows)
Na systemie Windows lub gdy chcesz jedynie wygenerować pliki motywu bez dotykania partycji rozruchowej ESP:

```bash
python3 build_and_deploy_theme.py --build-only
```
Pliki trafią do katalogu `dist/ghoul-cyber/`.

---

## 🪟 Ręczna instalacja na Windowsie

Na Windowsie skrypt nigdy nie dotyka partycji rozruchowej. Zbuduj paczkę (`py build_and_deploy_theme.py --build-only`) **albo** pobierz gotowe archiwum `ghoul-cyber-v*.zip` z [Releases](https://github.com/Dismonder/refind-theme-ghoul-cyber/releases), a następnie w terminalu **uruchomionym jako administrator**:

```powershell
mountvol S: /S
robocopy dist\ghoul-cyber S:\EFI\refind\themes\ghoul-cyber /E
notepad S:\EFI\refind\refind.conf
mountvol S: /D
```

W `refind.conf` dopisz na samym końcu:

```
include themes/ghoul-cyber/theme.conf
```

> 💡 Przy ręcznej instalacji zajrzyj też do `themes/ghoul-cyber/theme.conf`: linijka `resolution` musi pasować do Twojego monitora, a przykładowy blok `menuentry "Windows 11 Gaming"` możesz usunąć albo dostosować do swoich dysków.

---

## ⚙️ Najważniejsze parametry CLI

| Parametr | Opis |
| :--- | :--- |
| `--resolution WIDTHxHEIGHT` | Rozdzielczość docelowa (domyślnie `3840x2160`, wspierane także `2560x1440`, `1920x1080`) |
| `--build-only` | Generuje motyw do `dist/` bez ingerencji w ESP i konfigurację rEFInd |
| `--dry-run` | Sprawdza środowisko i wypisuje planowane operacje bez modyfikowania dysku |
| `--non-interactive` | Kończy się błędem zamiast pytać, która instalacja Windows to DEV |
| `--source-dir PATH` | Ścieżka do katalogu z surowymi grafikami źródłowymi |
| `--output-dir PATH` | Ścieżka wyjściowa dla wygenerowanego motywu |
| `--refind-dir PATH` | Ścieżka do katalogu rEFInd na zamontowanej partycji ESP |
| `--cpu`, `--gpu`, `--ram`, `--nvme` | Ręczne nadpisanie danych telemetrycznych wypisywanych na tapecie |
| `--secure-boot {auto,on,off}` | Ręczne ustawienie wskaźnika Secure Boot |
| `--font PATH` | Ścieżka do własnego pliku fontu TTF/OTF |

---

## 🛠️ Rozwiązywanie problemów

**Zamiast rEFInd startuje Windows albo GRUB** — ustaw rEFInd na początku kolejności rozruchu UEFI (albo zrób to w BIOS-ie):

```bash
efibootmgr                         # znajdź numer wpisu "rEFInd Boot Manager"
sudo efibootmgr -o 0001,0000,0003  # ustaw go jako pierwszy
```

**W menu brakuje systemu** — `theme.conf` ukrywa niektóre katalogi przez `dont_scan_dirs` (np. `EFI/ubuntu`). Usuń z tej linijki wpis, którego potrzebujesz.

---

## ♻️ Odinstalowanie

Wszystko, co zmienia instalator, ma kopię zapasową:

1. Usuń z `refind.conf` blok między `# BEGIN ghoul-cyber managed theme` a `# END ghoul-cyber managed theme` — **albo** przywróć kopię `refind.conf.ghoul-cyber-<data>.bak` z katalogu rEFInd.
2. Przywróć oryginalne ikony systemów z plików `*.png.ghoul-cyber.bak` obok loaderów.
3. Usuń katalog `EFI/refind/themes/ghoul-cyber`.

---

## 🧪 Testy (Test Suite)

Projekt posiada zestaw testów jednostkowych pokrywających kontrakt budowania, geometrię assetów, transakcyjność zapisu ESP i parsowanie UEFI:

```bash
python3 -m pytest tests
```
