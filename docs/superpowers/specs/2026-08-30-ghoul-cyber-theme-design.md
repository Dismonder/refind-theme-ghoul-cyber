# Ghoul Cyber rEFInd Theme Design

## Cel

Powstanie samodzielny skrypt `build_and_deploy_theme.py`, który z assetów
znajdujących się obok skryptu zbuduje motyw `ghoul-cyber` dla rEFInd. Na
Windows skrypt utworzy wyłącznie gotowy katalog `dist/ghoul-cyber`. Na Linuksie
uruchomienie bez argumentów wykona pełny proces: wykryje sprzęt, zbuduje motyw w
rozdzielczości 4K, odnajdzie instalację rEFInd, przypisze trzy karty do
właściwych loaderów, wdroży pliki i aktywuje motyw.

Skrypt nie instaluje samego bootloadera rEFInd. Brak istniejącej instalacji
rEFInd kończy działanie przed zmianą ESP i wyświetla jednoznaczną instrukcję.

## Środowisko i zależności

- Minimalna wersja interpretera: Python 3.10.
- Pipeline graficzny używa Pillow i standardowej biblioteki Pythona.
- Na CachyOS brakujące `python-pillow`, `efibootmgr` lub font DejaVu Mono są
  doinstalowywane przez `sudo pacman -S --needed --noconfirm` po potwierdzeniu
  uprawnień przez użytkownika i przed rozpoczęciem instalacji.
- Na innych dystrybucjach brak zależności kończy działanie przed zapisem na ESP
  i podaje właściwą komendę instalacyjną zamiast zgadywać menedżer pakietów.
- Przypisanie loaderów na Linuksie wymaga `efibootmgr`, `lsblk` i `findmnt`.
  Telemetria korzysta opcjonalnie z `lspci`, `dmidecode`, `mokutil` i danych w
  `/proc` oraz `/sys`; brak narzędzia telemetrycznego uruchamia udokumentowany
  fallback.
- Detekcja Windows korzysta ze standardowego modułu `platform` i PowerShell/CIM.

## Interfejs CLI

Uruchomienie bez argumentów ma następującą semantykę:

- Windows i inne systemy niż Linux: build-only do `dist/ghoul-cyber`.
- Linux: build, przypisanie ikon, deploy i aktywacja rEFInd.

Najważniejsze opcje:

- `--resolution WIDTHxHEIGHT`, domyślnie `3840x2160`; obsługiwane jest również
  `2560x1440` i `1920x1080` oraz inne poprawne rozdzielczości 16:9.
- `--build-only` wyłącza operacje uprzywilejowane i modyfikacje ESP.
- `--dry-run` wykonuje detekcję oraz walidację i raportuje planowane operacje bez
  zmiany rEFInd ani loaderów.
- `--source-dir`, `--output-dir` i `--refind-dir` pozwalają jawnie wskazać
  katalogi; ścieżki domyślne są wyprowadzane z lokalizacji skryptu.
- `--font` pozwala użyć konkretnego pliku TTF/OTF.
- `--cpu`, `--ram`, `--gpu`, `--nvme`, `--uefi-version` i
  `--secure-boot {auto,on,off}` nadpisują automatyczną telemetrię.
- `--non-interactive` zabrania pytań. Niejednoznaczne przypisanie dwóch
  instalacji Windows kończy wtedy działanie przed modyfikacją ESP.

Nieudokumentowane opcje wewnętrzne mogą służyć wyłącznie do wykonania
uprzywilejowanej fazy po ponownym uruchomieniu przez `sudo`; nie są częścią
publicznego interfejsu.

## Odkrywanie assetów

Skrypt szuka dokładnych nazw bazowych `background`, `selection_box`,
`selection_item_windev`, `selection_item_wingame`, `selection_item_linux`,
`bios` i `power`, niezależnie od wielkości liter, z rozszerzeniem `.png`,
`.jpg` lub `.jpeg`. Pliki takie jak `background_overlay.png` nie pasują do
`background`.

Brak assetu lub więcej niż jeden plik o tym samym wymaganym rdzeniu powoduje
błąd walidacji z listą kolidujących ścieżek. Pipeline nie wybiera arbitralnie
jednego z konfliktujących obrazów.

## Autocrop i normalizacja obrazów

Każdy asset jest otwierany z korektą orientacji EXIF i konwertowany do RGBA.
Kadrowanie przebiega następująco:

1. Dla obrazów z kanałem alfa powstaje maska pikseli o znaczącym alfa.
2. Rzadkie pojedyncze piksele przy krawędziach są ignorowane przez analizę
   zajętości wierszy i kolumn, dzięki czemu artefakt nie rozszerza kadru.
3. Dla nieprzezroczystych JPEG-ów jasne tło połączone z krawędzią obrazu jest
   zamieniane na przezroczystość.
4. Dla nieprzezroczystego `selection_box` czerń jest usuwana miękkim kluczem
   luminancji, aby wnętrze i zewnętrze ramki pozostały przezroczyste.
5. Prostokąt zawartości jest rozszerzany wokół środka do kwadratu bez obcinania
   istotnych elementów, a następnie skalowany filtrem LANCZOS.

Wyniki zachowują tryb RGBA. Rozmiary są dokładne:

- `icons/os_win_dev.png`: 128x128,
- `icons/os_win_game.png`: 128x128,
- `icons/os_cachyos.png`: 128x128,
- `icons/tool_firmware.png`: 48x48,
- `icons/tool_shutdown.png`: 48x48,
- `icons/tool_reboot.png`: 48x48,
- `selection_big.png`: 144x144,
- `selection_small.png`: 56x56.

Ponieważ rEFInd używa dla wbudowanych funkcji nazw `func_firmware.png`,
`func_shutdown.png` i `func_reset.png`, w `icons/` powstaną również identyczne
aliasy tych trzech obrazów. Wymagane pliki `tool_*.png` pozostają obecne.

## Proceduralna ikona restartu

`tool_reboot.png` nie zależy od dodatkowego assetu. Skrypt rysuje ikonę na
większej przezroczystej kanwie, a następnie skaluje ją do 48x48. Motyw składa
się z białej, zaokrąglonej strzałki obiegającej niepełny okrąg i subtelnego
krwistoczerwonego rozmycia. Środek oraz obszar poza symbolem pozostają
przezroczyste.

## Tło, HUD i nawigacja

Tło jest dopasowywane metodą `fillscreen` do docelowej rozdzielczości i
komponowane na kanwie OLED `#000000`. Dla domyślnego uruchomienia wynik ma
dokładnie 3840x2160 pikseli. Lewy górny piksel pozostaje czarny, aby zachować
poprawny kolor wypełnienia rEFInd.

HUD zaczyna się w `(70, 60)`, używa interlinii 32 px, fontu monospace oraz
koloru `#CCCCCC`. Zawiera kolejno:

```text
> UEFI 2.9 ] Secure Boot: OFF
> CPU: [detected or overridden value]
> RAM: [capacity] [DDR type] [speed MT/s]
> GPU: [detected or overridden value]
> NVMe: [capacity] -- OK
>
```

Po ostatnim `>` rysowany jest biały prostokątny kursor. Długie wartości są
skracane wielokropkiem dopiero wtedy, gdy nie mieszczą się w bezpiecznej
szerokości HUD-u; etykiety i wykryte pojemności pozostają czytelne.

Pasek nawigacji jest wycentrowany względem całego ekranu na wysokości
`height - 70` i ma dokładną treść:

```text
_SELECT OS    [ ↑ ][ ↓ ] NAVIGATE    [ ENTER ] SELECT    [ E ] EDIT BOOT    [ TAB ] INFO
```

Całość poza słowem `ENTER` ma kolor `#DCDCDC`. Samo `ENTER`, bez nawiasów i
spacji, ma kolor `#FF003C`. Rozmiar fontu nawigacji jest wybierany w wąskim,
kontrolowanym zakresie tak, aby tekst mieścił się także w 1920x1080.

## Detekcja telemetrii

Detektor zwraca jeden ujednolicony obiekt danych. Na Linuksie CPU pochodzi z
`lscpu` lub `/proc/cpuinfo`, RAM z `/proc/meminfo` uzupełnionego danymi SMBIOS,
GPU z `lspci`, NVMe z `lsblk`, a stan Secure Boot z `mokutil` lub zmiennej EFI.
Na Windows dane pochodzą z klas CIM `Win32_Processor`, `Win32_PhysicalMemory`,
`Win32_VideoController` i `Win32_DiskDrive`, a Secure Boot z
`Confirm-SecureBootUEFI`.

Wersja UEFI domyślnie wynosi `2.9`, ponieważ system operacyjny nie udostępnia
przenośnego i wiarygodnego API zwracającego wersję specyfikacji firmware.
Można ją zawsze zmienić przez `--uefi-version`.

Brak części danych nie zatrzymuje budowania. Pole otrzymuje zwięzłą wartość
`UNKNOWN`; wyjątkiem są jawne, niepoprawne nadpisania CLI, które kończą się
błędem wejścia.

## Struktura wyjściowa i konfiguracja

Skrypt tworzy następującą strukturę:

```text
dist/ghoul-cyber/
├── background.png
├── selection_big.png
├── selection_small.png
├── theme.conf
├── install-state.json
└── icons/
    ├── os_win_dev.png
    ├── os_win_game.png
    ├── os_cachyos.png
    ├── tool_firmware.png
    ├── tool_shutdown.png
    ├── tool_reboot.png
    ├── func_firmware.png
    ├── func_shutdown.png
    └── func_reset.png
```

`install-state.json` nie zawiera sekretów. Przechowuje wersję formatu,
rozdzielczość, skróty wygenerowanych plików oraz — po instalacji — mapowanie
ról na PARTUUID i ścieżki loaderów. Podczas samego build-only mapowanie może
być puste.

`theme.conf` ma dokładną treść funkcjonalną wymaganą przez projekt:

```ini
banner themes/ghoul-cyber/background.png
banner_scale fillscreen

selection_big themes/ghoul-cyber/selection_big.png
selection_small themes/ghoul-cyber/selection_small.png

big_icon_size 128
small_icon_size 48

icons_dir themes/ghoul-cyber/icons

hideui hints,arrows,badges,label
showtools firmware, reboot, shutdown
timeout 10
```

## Automatyczne przypisanie kart systemów

Skrypt nie zastępuje działających wpisów rEFInd ręcznymi stanzami. Zamiast
tego stosuje mechanizm rEFInd, w którym obraz PNG nazwany jak loader znajduje
się obok pliku loadera.

Na Linuksie wykonywane są następujące kroki:

1. `efibootmgr -v` dostarcza wpisy UEFI, numery partycji, PARTUUID i ścieżki
   loaderów.
2. `lsblk` i `findmnt` uzupełniają etykiety, rozmiary, urządzenia oraz aktualne
   punkty montowania.
3. CachyOS jest rozpoznawany po etykiecie lub ścieżce. Jeżeli system startuje
   bez osobnego wpisu NVRAM, skrypt używa aktualnego obrazu `vmlinuz*` z
   `/boot` i tworzy odpowiadający mu plik PNG.
4. Dwa wpisy Windows są klasyfikowane po etykietach zawierających `DEV` oraz
   `GAME`/`GAMING`. Jeżeli nadal są nierozróżnialne, tryb interaktywny pokazuje
   Boot####, urządzenie, PARTUUID, etykietę i rozmiar. Użytkownik wskazuje DEV,
   a drugi kandydat staje się GAMING.
5. Na docelowych woluminach powstają odpowiednio pliki PNG nazwane jak loader,
   na przykład `bootmgfw.png` obok `bootmgfw.efi`. Różne ESP mogą więc mieć
   różne obrazy mimo identycznej nazwy windowsowego loadera.
6. Mapowanie trafia do `install-state.json` i jest ponownie używane tylko po
   potwierdzeniu, że PARTUUID oraz ścieżka loadera nadal istnieją.

Wolumin zamontowany przez skrypt jest odmontowywany po zakończeniu. Skrypt nie
odmontowuje woluminów, które były zamontowane przed jego uruchomieniem.

## Deploy i aktywacja na Linuksie

Instalacja rEFInd jest wyszukiwana w `/boot/EFI/refind`,
`/boot/efi/EFI/refind` i `/efi/EFI/refind`, a następnie w zamontowanych ESP.
Jawne `--refind-dir` ma pierwszeństwo. Kandydat musi zawierać `refind.conf`
oraz plik `refind_*.efi`; sama zgodność nazwy katalogu nie wystarcza.

Cały build i walidacja odbywają się przed operacjami uprzywilejowanymi.
`sudo` jest używane tylko do instalacji zależności, dostępu do SMBIOS,
montowania ESP, wdrożenia i modyfikacji konfiguracji. Skrypt nie wymaga, aby
użytkownik uruchamiał go bezpośrednio jako root.

Gotowy motyw jest kopiowany do `themes/ghoul-cyber`. Skrypt nadpisuje wyłącznie
znane pliki, których sam jest właścicielem, i nie usuwa obcych plików z
katalogu motywu. `refind.conf` otrzymuje na końcu zarządzany blok:

```ini
# BEGIN ghoul-cyber managed theme
include themes/ghoul-cyber/theme.conf
# END ghoul-cyber managed theme
```

Blok jest aktualizowany idempotentnie. Pozycja na końcu pliku gwarantuje, że
ustawienia motywu mają pierwszeństwo. Przed rzeczywistą zmianą powstaje kopia
`refind.conf.ghoul-cyber-YYYYmmdd-HHMMSS.bak`.

Istniejące pliki ikon obok loaderów są przed zastąpieniem kopiowane do plików
z sufiksem `.ghoul-cyber.bak`. Skrypt nie nadpisuje wcześniejszego backupu,
jeżeli ten już istnieje.

## Atomowość, błędy i rollback

- Obrazy powstają najpierw w prywatnym katalogu staging poza finalnym
  `ghoul-cyber`; dopiero kompletny, zweryfikowany zestaw jest publikowany.
- Każdy PNG jest ponownie otwierany i sprawdzany pod kątem rozmiaru, trybu i
  uszkodzenia przed deployem.
- Role loaderów są rozwiązywane przed pierwszą zmianą ESP.
- Modyfikacja `refind.conf` następuje jako ostatnia operacja, po udanym deployu
  motywu i ikon.
- Zapis konfiguracji używa pliku tymczasowego na tym samym systemie plików i
  atomowej podmiany.
- Jeżeli faza instalacji nie powiedzie się, dziennik transakcji przywraca
  zmienione ikony i konfigurację z backupów oraz usuwa wyłącznie pliki utworzone
  przez bieżącą transakcję.
- Skrypt nigdy nie usuwa loaderów EFI, wpisów NVRAM, partycji ani cudzych
  katalogów motywów.
- Błędy kończą się niezerowym kodem wyjścia i komunikatem zawierającym etap,
  ścieżkę oraz możliwą akcję naprawczą, bez ujawniania danych uwierzytelniających.

## Testowanie i weryfikacja

Testy używają `unittest` ze standardowej biblioteki i tymczasowych katalogów.
Obejmują:

- parsowanie rozdzielczości oraz odrzucanie niepoprawnych wartości,
- jednoznaczne odkrywanie assetów i raportowanie konfliktów,
- autocrop przezroczystego PNG i JPEG-a z jasnym obramowaniem,
- zachowanie przezroczystości ramki wyboru,
- dokładne rozmiary i tryby wszystkich ikon,
- obecność jasnych i czerwonych pikseli proceduralnego restartu,
- render HUD-u, białego kursora oraz czerwonego `ENTER`,
- generowanie dokładnej konfiguracji `theme.conf`,
- parsowanie kontrolowanych próbek `efibootmgr` i `lsblk`,
- automatyczne oraz interaktywne przypisanie DEV/GAMING/CachyOS,
- idempotentne zarządzanie blokiem `refind.conf`, backup i rollback,
- integracyjny build z syntetycznych assetów bez dostępu do prawdziwego ESP.

Po testach skrypt zostanie uruchomiony w bieżącym katalogu na prawdziwych
assetach w trybie build-only. Wygenerowane pliki zostaną sprawdzone skryptowo,
a `background.png`, selektory oraz ikony przejdą wizualną inspekcję. Pełny
deploy do prawdziwego ESP nie może zostać wykonany ani potwierdzony na obecnym
hoście Windows; jego logika zostanie zweryfikowana na sztucznej strukturze ESP.

## Źródła zgodności rEFInd

- Oficjalna dokumentacja motywów:
  `https://www.rodsbooks.com/refind/themes.html`
- Oficjalna dokumentacja konfiguracji i przypisywania ikon:
  `https://www.rodsbooks.com/refind/configfile.html`
- Oficjalne repozytorium nazw ikon:
  `https://sourceforge.net/p/refind/code/ci/master/tree/icons/`
