from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from PIL import Image, ImageDraw


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


def write_synthetic_assets(root: Path) -> None:
    Image.new("RGB", (320, 180), "black").save(root / "background.png")

    frame = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rectangle(
        (8, 8, 111, 111), outline=(255, 0, 60, 255), width=8
    )
    frame.save(root / "selection_box.png")

    colors = {
        "selection_item_windev": (235, 235, 235, 255),
        "selection_item_wingame": (255, 0, 60, 255),
        "selection_item_linux": (220, 220, 220, 255),
        "bios": (230, 230, 230, 255),
        "power": (245, 245, 245, 255),
    }
    for stem, outline in colors.items():
        card = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(card).rectangle(
            (15, 15, 104, 104),
            fill=(5, 5, 5, 255),
            outline=outline,
            width=4,
        )
        card.save(root / f"{stem}.png")


class CoreContractTests(unittest.TestCase):
    def test_parse_resolution_accepts_4k(self):
        subject = load_subject()
        self.assertEqual(
            subject.parse_resolution("3840x2160"),
            subject.Resolution(3840, 2160),
        )

    def test_parse_resolution_rejects_non_16_by_9(self):
        subject = load_subject()
        with self.assertRaisesRegex(ValueError, "16:9"):
            subject.parse_resolution("1920x1200")

    def test_parse_resolution_rejects_malformed_value(self):
        subject = load_subject()
        with self.assertRaisesRegex(ValueError, "WIDTHxHEIGHT"):
            subject.parse_resolution("4k")

    def test_parser_defaults_to_4k_and_local_paths(self):
        subject = load_subject()
        args = subject.create_parser(ROOT).parse_args([])
        self.assertEqual(args.resolution, subject.Resolution(3840, 2160))
        self.assertEqual(args.source_dir, ROOT)
        self.assertEqual(args.output_dir, ROOT / "dist" / "ghoul-cyber")
        self.assertFalse(args.build_only)


class AssetPipelineTests(unittest.TestCase):
    def test_discovery_uses_exact_stems_and_rejects_conflicts(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for stem in subject.ASSET_STEMS:
                Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(
                    root / f"{stem}.png"
                )
            Image.new("RGBA", (20, 20)).save(root / "background_overlay.png")
            found = subject.discover_assets(root)
            self.assertEqual(found["background"].name, "background.png")

            Image.new("RGB", (20, 20), "white").save(root / "background.jpg")
            with self.assertRaisesRegex(subject.ThemeError, "background.*multiple"):
                subject.discover_assets(root)

    def test_discovery_reports_missing_asset(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(subject.ThemeError, "background.*missing"):
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
            opened = subject.open_rgba(path)
            output = subject.resize_asset(path, 128)
            self.assertLess(opened.getpixel((0, 0))[3], 32)
            self.assertEqual(output.mode, "RGBA")
            self.assertEqual(output.size, (128, 128))

    def test_selection_frame_black_key_keeps_center_transparent(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "selection_box.jpg"
            image = Image.new("RGB", (100, 100), "black")
            ImageDraw.Draw(image).rectangle((10, 10, 89, 89), outline="red", width=8)
            image.save(path, quality=100, subsampling=0)
            output = subject.resize_asset(path, 144, selection_frame=True)
            self.assertLess(output.getpixel((72, 72))[3], 16)
            self.assertGreater(
                max(pixel[0] for pixel in output.get_flattened_data()), 160
            )


class RenderingTests(unittest.TestCase):
    def test_reboot_icon_contains_alpha_white_and_cyber_red(self):
        subject = load_subject()
        icon = subject.render_reboot_icon()
        pixels = list(icon.get_flattened_data())
        self.assertEqual(
            icon.size, (subject.SMALL_ICON_SIZE, subject.SMALL_ICON_SIZE)
        )
        self.assertEqual(icon.mode, "RGBA")
        self.assertTrue(any(alpha == 0 for _, _, _, alpha in pixels))
        self.assertTrue(
            any(
                red > 220 and green > 220 and blue > 220 and alpha > 180
                for red, green, blue, alpha in pixels
            )
        )
        self.assertTrue(
            any(
                red > 150 and green < 80 and blue < 100 and alpha > 10
                for red, green, blue, alpha in pixels
            )
        )

    def test_background_is_exact_size_with_red_enter_and_white_cursor(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "background.png"
            Image.new("RGB", (320, 180), "black").save(path)
            hardware = subject.HardwareInfo(
                cpu="TEST CPU",
                ram="32 GB DDR5 6000 MT/s",
                gpu="TEST GPU",
                nvme="2 TB",
                uefi_version="2.9",
                secure_boot="OFF",
            )
            output = subject.render_background(
                path, subject.Resolution(1920, 1080), hardware
            )
            pixels = list(output.convert("RGB").get_flattened_data())
            self.assertEqual(output.size, (1920, 1080))
            self.assertEqual(output.mode, "RGBA")
            self.assertEqual(output.getpixel((0, 0))[:3], (0, 0, 0))
            self.assertTrue(
                any(red > 220 and green < 40 and blue < 90 for red, green, blue in pixels)
            )
            cursor_region = output.crop((70, 60 + 5 * 32, 400, 60 + 6 * 32))
            self.assertTrue(
                any(
                    min(pixel[:3]) > 220
                    for pixel in cursor_region.get_flattened_data()
                )
            )


class HardwareTelemetryTests(unittest.TestCase):
    def test_windows_cim_payload_is_normalized(self):
        subject = load_subject()
        payload = json.dumps(
            {
                "Cpu": "AMD Ryzen 9 9950X3D 16-Core Processor",
                "Memory": [
                    {"Capacity": 34359738368, "SMBIOSMemoryType": 34, "Speed": 6000},
                    {"Capacity": 34359738368, "SMBIOSMemoryType": 34, "Speed": 6000},
                ],
                "Gpu": [{"Name": "NVIDIA GeForce RTX 5090"}],
                "Disk": [
                    {
                        "Model": "NVMe TEST",
                        "Size": 4000787030016,
                        "InterfaceType": "SCSI",
                        "PNPDeviceID": "PCI\\VEN_TEST&NVME",
                    }
                ],
                "SecureBoot": False,
            }
        )
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
        self.assertIn("NVIDIA Corporation Test GPU", info.gpu)
        self.assertEqual(info.nvme, "2 TB")
        self.assertEqual(info.secure_boot, "OFF")

    def test_explicit_overrides_win_over_detection(self):
        subject = load_subject()
        base = subject.HardwareInfo(
            cpu="detected", ram="detected", gpu="detected", nvme="detected"
        )
        result = subject.apply_hardware_overrides(
            base,
            subject.HardwareOverrides(
                cpu="override cpu", secure_boot="on", uefi_version="2.10"
            ),
        )
        self.assertEqual(result.cpu, "override cpu")
        self.assertEqual(result.ram, "detected")
        self.assertEqual(result.secure_boot, "ON")
        self.assertEqual(result.uefi_version, "2.10")


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
                source,
                output,
                subject.Resolution(1920, 1080),
                subject.HardwareInfo(cpu="CPU", ram="RAM", gpu="GPU", nvme="1 TB"),
            )
            self.assertEqual(build.output_dir, output.resolve())
            big = (subject.BIG_ICON_SIZE, subject.BIG_ICON_SIZE)
            small = (subject.SMALL_ICON_SIZE, subject.SMALL_ICON_SIZE)
            badge = (subject.BADGE_ICON_SIZE, subject.BADGE_ICON_SIZE)
            expected_sizes = {
                "background.png": (1920, 1080),
                "selection_big.png": (
                    subject.SELECTION_BIG_SIZE, subject.SELECTION_BIG_SIZE
                ),
                "selection_small.png": (
                    subject.SELECTION_SMALL_SIZE, subject.SELECTION_SMALL_SIZE
                ),
                "icons/os_win.png": big,
                "icons/os_win_dev.png": big,
                "icons/os_win_game.png": big,
                "icons/os_cachyos.png": big,
                "icons/os_linux.png": big,
                "icons/os_arch.png": big,
                "icons/os_ubuntu.png": big,
                "icons/os_debian.png": big,
                "icons/os_fedora.png": big,
                "icons/os_mac.png": big,
                "icons/os_unknown.png": big,
                "icons/tool_firmware.png": small,
                "icons/tool_shutdown.png": small,
                "icons/tool_reboot.png": small,
                "icons/tool_shell.png": small,
                "icons/tool_memtest.png": small,
                "icons/tool_mok_tool.png": small,
                "icons/tool_netboot.png": small,
                "icons/tool_part.png": small,
                "icons/tool_rescue.png": small,
                "icons/tool_fwupdate.png": small,
                "icons/func_firmware.png": small,
                "icons/func_shutdown.png": small,
                "icons/func_reset.png": small,
                "icons/func_about.png": small,
                "icons/func_exit.png": small,
                "icons/func_hidden.png": small,
                "icons/func_bootorder.png": small,
                "icons/func_csr_rotate.png": small,
                "icons/arrow_left.png": small,
                "icons/arrow_right.png": small,
                "icons/mouse.png": small,
                "icons/func_install.png": small,
                "icons/tool_windows_rescue.png": small,
                "icons/tool_apple_rescue.png": small,
                "icons/vol_internal.png": badge,
                "icons/vol_external.png": badge,
                "icons/vol_optical.png": badge,
                "icons/vol_net.png": badge,
                "icons/vol_efi.png": badge,
            }
            for relative, size in expected_sizes.items():
                with Image.open(output / relative) as image:
                    self.assertEqual(image.size, size, relative)
                    self.assertEqual(image.mode, "RGBA", relative)
                    image.verify()
            self.assertEqual(
                (output / "theme.conf").read_text(encoding="utf-8"),
                subject.render_theme_conf(
                    subject.default_options(), subject.Resolution(1920, 1080)
                ),
            )
            state = json.loads(
                (output / "install-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["format_version"], 1)
            self.assertEqual(state["resolution"], "1920x1080")
            self.assertEqual(state["assignments"], {})
            self.assertEqual(set(state["sha256"]), set(expected_sizes) | {"theme.conf"})

    def test_publish_keeps_unknown_output_files(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            output = root / "out"
            source.mkdir()
            output.mkdir()
            (output / "user-note.txt").write_text("keep", encoding="utf-8")
            write_synthetic_assets(source)
            subject.build_theme(
                source,
                output,
                subject.Resolution(1920, 1080),
                subject.HardwareInfo(),
            )
            self.assertEqual(
                (output / "user-note.txt").read_text(encoding="utf-8"), "keep"
            )


EFIBOOTMGR_FIXTURE = """BootCurrent: 0007
BootOrder: 0007,0001,0002
Boot0001* Windows DEV HD(1,GPT,11111111-1111-1111-1111-111111111111,0x800,0x32000)/\\File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
Boot0002* Windows Boot Manager HD(1,GPT,22222222-2222-2222-2222-222222222222,0x800,0x32000)/\\File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
Boot0007* CachyOS HD(1,GPT,77777777-7777-7777-7777-777777777777,0x800,0x32000)/\\File(\\EFI\\CachyOS\\grubx64.efi)
"""

EFIBOOTMGR_MODERN_FIXTURE = """BootCurrent: 0001
BootOrder: 0001,0000
Boot0000* Windows Boot Manager\tHD(1,GPT,af082e06-e080-47ed-b3e8-450398c9ec9e,0x800,0x32000)/\\EFI\\MICROSOFT\\BOOT\\BOOTMGFW.EFI57494e
Boot0001* rEFInd Boot Manager\tHD(1,GPT,4191cc89-cbaa-4fbf-9fe0-29e52561287d,0x1000,0x400000)/\\EFI\\refind\\refind_x64.efi
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
    def test_parses_enriches_and_assigns_three_boot_entries(self):
        subject = load_subject()
        parsed = subject.parse_efibootmgr(EFIBOOTMGR_FIXTURE)
        enriched = subject.enrich_boot_entries(parsed, subject.parse_lsblk(LSBLK_FIXTURE))
        roles = subject.assign_boot_roles(
            enriched, choose_dev=None, non_interactive=True
        )
        self.assertEqual(
            roles["win_dev"].partuuid,
            "11111111-1111-1111-1111-111111111111",
        )
        self.assertEqual(
            roles["win_game"].partuuid,
            "22222222-2222-2222-2222-222222222222",
        )
        self.assertEqual(roles["cachyos"].bootnum, "0007")
        self.assertEqual(roles["win_game"].device, "/dev/nvme1n1p1")

    def test_modern_efibootmgr_parsing_and_kernel_fallback(self):
        subject = load_subject()
        parsed = subject.parse_efibootmgr(EFIBOOTMGR_MODERN_FIXTURE)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].loader_path, "\\EFI\\MICROSOFT\\BOOT\\BOOTMGFW.EFI")
        self.assertEqual(parsed[1].loader_path, "\\EFI\\refind\\refind_x64.efi")

    def test_ambiguous_windows_requires_choice_or_fails_noninteractive(self):
        subject = load_subject()
        entries = [
            subject.BootEntry(
                "0001",
                "Windows Boot Manager",
                "a",
                "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
            ),
            subject.BootEntry(
                "0002",
                "Windows Boot Manager",
                "b",
                "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
            ),
            subject.BootEntry(
                "0003", "CachyOS", "c", "\\EFI\\CachyOS\\grubx64.efi"
            ),
        ]
        with self.assertRaisesRegex(subject.ThemeError, "ambiguous"):
            subject.assign_boot_roles(entries, choose_dev=None, non_interactive=True)
        roles = subject.assign_boot_roles(
            entries, choose_dev=lambda options: 1, non_interactive=False
        )
        self.assertEqual(roles["win_dev"].bootnum, "0002")
        self.assertEqual(roles["win_game"].bootnum, "0001")

    def test_previous_mapping_must_match_guid_and_loader(self):
        subject = load_subject()
        parsed = subject.parse_efibootmgr(EFIBOOTMGR_FIXTURE)
        enriched = subject.enrich_boot_entries(parsed, subject.parse_lsblk(LSBLK_FIXTURE))
        previous = {
            "win_dev": {
                "partuuid": "11111111-1111-1111-1111-111111111111",
                "loader_path": "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
            },
            "win_game": {
                "partuuid": "wrong-guid",
                "loader_path": "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
            },
        }
        roles = subject.assign_boot_roles(
            enriched, choose_dev=None, non_interactive=True, previous=previous
        )
        self.assertEqual(roles["win_dev"].bootnum, "0001")
        self.assertEqual(roles["win_game"].bootnum, "0002")

    def test_loader_icon_uses_same_directory_and_png_stem(self):
        subject = load_subject()
        self.assertEqual(
            subject.icon_path_for_loader("\\EFI\\Microsoft\\Boot\\bootmgfw.efi"),
            "\\EFI\\Microsoft\\Boot\\bootmgfw.png",
        )


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
            self.assertEqual(
                subject.find_refind_dir(None, (invalid, valid)), valid.resolve()
            )

    def test_explicit_invalid_refind_path_does_not_fall_through(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(subject.ThemeError, "invalid rEFInd"):
                subject.find_refind_dir(root / "missing", ())

    def test_managed_block_is_last_idempotent_and_preserves_crlf_bom(self):
        subject = load_subject()
        original = b"\xef\xbb\xbftimeout 5\r\n"
        once = subject.update_managed_config(original)
        twice = subject.update_managed_config(once)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(
            once.endswith(
                b"# BEGIN ghoul-cyber managed theme\r\n"
                b"include themes/ghoul-cyber/theme.conf\r\n"
                b"# END ghoul-cyber managed theme\r\n"
            )
        )

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


class LinuxWorkflowTests(unittest.TestCase):
    def test_missing_dependencies_map_to_cachyos_packages(self):
        subject = load_subject()
        present = {"lsblk": "/usr/bin/lsblk", "findmnt": "/usr/bin/findmnt"}
        missing = subject.missing_linux_dependencies(present.get)
        self.assertEqual(missing, ("efibootmgr",))
        self.assertEqual(subject.PACMAN_PACKAGES["efibootmgr"], "efibootmgr")

    def test_graphics_bootstrap_installs_monospace_font_on_linux(self):
        subject = load_subject()
        installed: list[tuple[str, ...]] = []
        with (
            patch.object(subject, "PIL_IMPORT_ERROR", None),
            patch.object(
                subject,
                "is_monospace_font_available",
                side_effect=(False, True),
            ),
            patch.object(subject.platform, "system", return_value="Linux"),
            patch.object(
                subject,
                "bootstrap_linux_dependencies",
                side_effect=lambda names: installed.append(tuple(names)),
            ),
        ):
            subject._ensure_graphics_dependencies()
        self.assertEqual(installed, [("font",)])

    def test_deployment_plan_json_round_trip(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "theme"
            refind = root / "refind"
            source.mkdir()
            refind.mkdir()
            target = subject.BootTarget(
                "win_dev",
                source / "icons" / "os_win_dev.png",
                "/dev/a",
                "guid-a",
                "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
                root / "esp",
            )
            plan = subject.DeploymentPlan(source, refind, (target,), 1000, 1000)
            decoded = subject.deployment_plan_from_json(
                subject.deployment_plan_to_json(plan), validate=False
            )
            self.assertEqual(decoded, plan)

    def test_apply_deployment_copies_theme_icons_and_activates_last(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            asset_source = root / "assets"
            theme_source = root / "dist" / "ghoul-cyber"
            refind = root / "refind-esp" / "EFI" / "refind"
            win_dev = root / "dev-esp"
            win_game = root / "game-esp"
            cachy = root / "cachy-esp"
            asset_source.mkdir()
            for directory in (refind, win_dev, win_game, cachy):
                directory.mkdir(parents=True)
            write_synthetic_assets(asset_source)
            subject.build_theme(
                asset_source,
                theme_source,
                subject.Resolution(1920, 1080),
                subject.HardwareInfo(),
            )
            (refind / "refind.conf").write_text("timeout 5\n", encoding="utf-8")
            (refind / "refind_x64.efi").write_bytes(b"MZ")

            targets = (
                subject.BootTarget(
                    "win_dev",
                    theme_source / "icons/os_win_dev.png",
                    "/dev/a",
                    "a",
                    "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
                    win_dev,
                ),
                subject.BootTarget(
                    "win_game",
                    theme_source / "icons/os_win_game.png",
                    "/dev/b",
                    "b",
                    "\\EFI\\Microsoft\\Boot\\bootmgfw.efi",
                    win_game,
                ),
                subject.BootTarget(
                    "cachyos",
                    theme_source / "icons/os_cachyos.png",
                    "/dev/c",
                    "c",
                    "\\EFI\\CachyOS\\grubx64.efi",
                    cachy,
                ),
            )
            for mount, loader in (
                (win_dev, targets[0].loader_path),
                (win_game, targets[1].loader_path),
                (cachy, targets[2].loader_path),
            ):
                loader_file = mount / Path(*PureWindowsPath(loader).parts[1:])
                loader_file.parent.mkdir(parents=True)
                loader_file.write_bytes(b"MZ")

            plan = subject.DeploymentPlan(theme_source, refind, targets)
            subject.apply_deployment(plan)
            subject.apply_deployment(plan)

            self.assertEqual(
                (win_dev / "EFI/Microsoft/Boot/bootmgfw.png").read_bytes(),
                (theme_source / "icons/os_win_dev.png").read_bytes(),
            )
            self.assertEqual(
                (win_game / "EFI/Microsoft/Boot/bootmgfw.png").read_bytes(),
                (theme_source / "icons/os_win_game.png").read_bytes(),
            )
            config = (refind / "refind.conf").read_text(encoding="utf-8")
            self.assertEqual(config.count(subject.MANAGED_BEGIN), 1)
            self.assertTrue(config.rstrip().endswith(subject.MANAGED_END))
            self.assertTrue((refind / "themes/ghoul-cyber/background.png").is_file())
            self.assertTrue(list(refind.glob("refind.conf.ghoul-cyber-*.bak")))

    def test_main_build_only_creates_theme(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_synthetic_assets(root)
            exit_code = subject.main(
                [
                    "--source-dir",
                    str(root),
                    "--output-dir",
                    str(root / "out"),
                    "--resolution",
                    "1920x1080",
                    "--cpu",
                    "CPU",
                    "--ram",
                    "RAM",
                    "--gpu",
                    "GPU",
                    "--nvme",
                    "1 TB",
                    "--secure-boot",
                    "off",
                    "--build-only",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "out" / "background.png").is_file())


class OptionsTests(unittest.TestCase):
    def test_defaults_are_valid_and_scale_with_resolution(self):
        subject = load_subject()
        options, errors, warnings = subject.validate_options({})
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(subject.icon_geometry(options, subject.Resolution(3840, 2160)), (768, 240))
        self.assertEqual(subject.icon_geometry(options, subject.Resolution(1920, 1080)), (384, 120))

    def test_invalid_values_are_reported_and_replaced_by_defaults(self):
        subject = load_subject()
        options, errors, warnings = subject.validate_options({
            "refind": {"timeout": 9999, "showtools": ["shell", "rm -rf"]},
            "hud": {"title_text": 'bad "quote"', "accent": "red"},
            "entries": [{"label": "Ok", "card": "nope", "loader": "../../x"}],
            "typo": 1,
        })
        self.assertEqual(options["refind.timeout"], 10)
        self.assertEqual(len(errors), 6, errors)
        self.assertEqual(warnings, ["typo: unknown option, ignored"])

    def test_theme_conf_reflects_options_and_entries(self):
        subject = load_subject()
        options, errors, _ = subject.validate_options({
            "refind": {"timeout": 0, "enable_mouse": True, "default_selection": "CachyOS",
                       "hideui": ["hints"], "showtools": ["reboot", "shutdown"]},
            "entries": [{"label": "Windows Gaming", "card": "win_game",
                         "volume": "GAMEDISK", "loader": "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"}],
        })
        self.assertEqual(errors, [])
        subject.configure_geometry(*subject.icon_geometry(options, subject.Resolution(2560, 1440)))
        conf = subject.render_theme_conf(options, subject.Resolution(2560, 1440))
        for expected in ("resolution 2560 1440", "timeout 0", "enable_mouse", "hideui hints",
                         'default_selection "CachyOS"', "showtools reboot, shutdown",
                         "big_icon_size 512", 'menuentry "Windows Gaming" {',
                         'volume "GAMEDISK"', "icons/os_win_game.png"):
            self.assertIn(expected, conf)
        self.assertNotIn("af082e06", conf)

    def test_save_writes_only_changes_and_round_trips(self):
        subject = load_subject()
        options = subject.default_options()
        options["hud.nav_bar"] = False
        options["refind.timeout"] = 5
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "boot-config.json"
            subject.save_options(options, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"version": 1, "hud": {"nav_bar": False}, "refind": {"timeout": 5}})
            self.assertEqual(subject.load_options(path), options)

    def test_hud_lines_follow_options(self):
        subject = load_subject()
        options = subject.default_options()
        options["hud.hardware_lines"] = ("cpu", "gpu")
        options["hud.custom_lines"] = ("hello",)
        lines = subject.hud_text_lines(subject.HardwareInfo(cpu="X", gpu="Y"), options)
        self.assertEqual(lines, ["CPU: X", "GPU: Y", "hello"])
        options["hud.hardware"] = False
        self.assertEqual(subject.hud_text_lines(subject.HardwareInfo(), options), ["hello"])


class WindowsInstallTests(unittest.TestCase):
    def _built_theme(self, subject, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        write_synthetic_assets(source)
        output = root / "dist" / "ghoul-cyber"
        subject.build_theme(source, output, subject.Resolution(1920, 1080), subject.HardwareInfo())
        return output

    def _fake_refind(self, root: Path) -> Path:
        refind = root / "esp" / "EFI" / "refind"
        refind.mkdir(parents=True)
        (refind / "refind.conf").write_bytes(b"timeout 20\r\n")
        (refind / "refind_x64.efi").write_bytes(b"efi")
        return refind

    def test_installs_theme_and_activates_it_with_backup(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            theme, refind = self._built_theme(subject, root), self._fake_refind(root)
            subject.install_theme_windows(theme, refind)
            config = (refind / "refind.conf").read_bytes()
            self.assertIn(b"\r\ninclude themes/ghoul-cyber/theme.conf\r\n", config)
            self.assertTrue((refind / "themes" / "ghoul-cyber" / "background.png").is_file())
            self.assertEqual(len(list(refind.glob("refind.conf.ghoul-cyber-*.bak"))), 1)

    def test_failure_rolls_everything_back(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            theme, refind = self._built_theme(subject, root), self._fake_refind(root)
            with patch.object(subject, "update_managed_config", side_effect=subject.ThemeError("boom")):
                with self.assertRaises(subject.ThemeError):
                    subject.install_theme_windows(theme, refind)
            self.assertEqual((refind / "refind.conf").read_bytes(), b"timeout 20\r\n")
            self.assertFalse((refind / "themes" / "ghoul-cyber" / "background.png").exists())

    def test_lists_esp_partitions(self):
        subject = load_subject()

        def runner(command):
            return subject.subprocess.CompletedProcess(command, 0, "0:1:\n2:1:S\njunk\n", "")

        self.assertEqual(subject.list_windows_esps(runner), [(0, 1, ""), (2, 1, "S")])


# bcdedit /enum firmware /v on a Polish Windows: field names are translated.
BCD_FIRMWARE = (
    "Menedżer rozruchu oprogramowania układowego\r\n"
    "--------------------------------------------\r\n"
    "identyfikator           {a5a30fa2-3d06-4e9f-b5f4-a01df9d1fcba}\r\n"
    "displayorder            {9dea862c-5cdd-4e70-acc1-f32b344d4795}\r\n"
    "                        {11111111-2222-3333-4444-555555555555}\r\n"
    "limit czasu             0\r\n"
    "\r\n"
    "Menedżer rozruchu systemu Windows\r\n"
    "---------------------------------\r\n"
    "identyfikator           {9dea862c-5cdd-4e70-acc1-f32b344d4795}\r\n"
    "urządzenie              partition=\\Device\\HarddiskVolume1\r\n"
    "ścieżka                 \\EFI\\Microsoft\\Boot\\bootmgfw.efi\r\n"
    "opis                    Windows Boot Manager\r\n"
    "\r\n"
    "Aplikacja oprogramowania układowego (101fffff)\r\n"
    "----------------------------------------------\r\n"
    "identyfikator           {11111111-2222-3333-4444-555555555555}\r\n"
    "urządzenie              partition=\\Device\\HarddiskVolume1\r\n"
    "ścieżka                 \\EFI\\refind\\refind_x64.efi\r\n"
    "opis                    rEFInd\r\n"
)
NEW_ENTRY = "{abcdef01-2345-6789-abcd-ef0123456789}"


class WindowsRefindInstallTests(unittest.TestCase):
    """rEFInd itself on a PC with only Windows - every system call is faked."""

    def _zip(self, arch: str = "x64") -> bytes:
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            base = "refind-bin-0.14.2/refind/"
            archive.writestr(base + f"refind_{arch}.efi", b"EFI-BINARY")
            archive.writestr(base + "refind_ia32.efi", b"OTHER-ARCH")
            archive.writestr(base + "refind.conf-sample", b"timeout 20\n")
            archive.writestr(base + "icons/os_win.png", b"PNG")
            archive.writestr(base + "icons/../../escape.png", b"BAD")
            archive.writestr("refind-bin-0.14.2/refind-install", b"#!/bin/sh")
        return buffer.getvalue()

    def _esp(self, root: Path, *, windows: bool = True) -> Path:
        esp = root / "esp"
        (esp / "EFI" / "Microsoft" / "Boot").mkdir(parents=True)
        if windows:
            (esp / "EFI" / "Microsoft" / "Boot" / "bootmgfw.efi").write_bytes(b"MS")
        return esp

    def _runner(self, listing: str = "", *, bitlocker: str = "paused", fail_on: str | None = None):
        calls: list[tuple[str, ...]] = []
        subject_process = __import__("subprocess")

        def runner(command):
            command = tuple(command)
            calls.append(command)
            if command[0] == "powershell":
                return subject_process.CompletedProcess(command, 0, f"{bitlocker}\r\n", "")
            args = command[1:]
            if fail_on is not None and fail_on in args:
                return subject_process.CompletedProcess(command, 1, "", "Odmowa dostępu.")
            if args[:2] == ("/enum", "firmware"):
                return subject_process.CompletedProcess(command, 0, listing, "")
            if args[:1] == ("/copy",):
                return subject_process.CompletedProcess(
                    command, 0, f"Wpis został pomyślnie skopiowany do {NEW_ENTRY}.\r\n", "")
            return subject_process.CompletedProcess(command, 0, "Operacja ukończona pomyślnie.\r\n", "")

        return runner, calls

    def _ready(self, subject, data: bytes | None = None):
        return (
            patch.object(subject, "windows_firmware_is_uefi", return_value=True),
            patch.object(subject, "windows_secure_boot_enabled", return_value=False),
            patch.object(subject, "windows_efi_arch", return_value="x64"),
            patch.object(subject, "fetch_refind_zip", return_value=data or self._zip()),
        )

    @staticmethod
    def _bcd(calls):
        return [c[1:] for c in calls if c[0].casefold().endswith("bcdedit.exe")]

    def test_parses_translated_bcdedit_by_guid_and_path(self):
        subject = load_subject()
        self.assertEqual(subject.find_firmware_entry(BCD_FIRMWARE, r"\EFI\refind\refind_x64.efi"),
                         "{11111111-2222-3333-4444-555555555555}")
        self.assertEqual(subject.find_firmware_entry(BCD_FIRMWARE, r"\EFI\Microsoft\Boot\bootmgfw.efi"),
                         "{9dea862c-5cdd-4e70-acc1-f32b344d4795}")
        self.assertIsNone(subject.find_firmware_entry(BCD_FIRMWARE, r"\EFI\refind\refind_aa64.efi"))
        self.assertEqual(subject.firmware_display_order(BCD_FIRMWARE),
                         ["{9dea862c-5cdd-4e70-acc1-f32b344d4795}",
                          "{11111111-2222-3333-4444-555555555555}"])

    def test_takes_only_the_needed_files_from_the_zip(self):
        subject = load_subject()
        files = subject.refind_files_from_zip(self._zip(), "x64")
        self.assertEqual(sorted(files), ["icons/os_win.png", "refind.conf", "refind_x64.efi"])
        with self.assertRaises(subject.ThemeError):
            subject.refind_files_from_zip(self._zip(), "aa64")

    def test_rejects_a_zip_that_is_not_the_official_release(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            fake = Path(raw) / "refind-bin-0.14.2.zip"
            fake.write_bytes(self._zip())
            with self.assertRaises(subject.ThemeError) as caught:
                subject.fetch_refind_zip(fake)
            self.assertIn("not the official", str(caught.exception))

    def _download_env(self, subject, *, python, curl, powershell, platform="win32"):
        """Fake Python/curl.exe/PowerShell downloads: each is bytes to write or an OSError."""
        import hashlib
        import re

        calls: list[str] = []

        class Response:
            def __init__(self, data):
                self.data = data

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, _limit):
                return self.data

        def urlopen(url, timeout):
            calls.append("Python")
            if isinstance(python, Exception):
                raise python
            return Response(python)

        def runner(command):
            name = "curl.exe" if command[0].lower().endswith("curl.exe") else "PowerShell"
            calls.append(name)
            outcome = curl if name == "curl.exe" else powershell
            if isinstance(outcome, Exception):
                return subject.subprocess.CompletedProcess(command, 1, "", str(outcome))
            target = (command[command.index("--output") + 1] if name == "curl.exe"
                      else re.search(r"-OutFile '([^']+)'", command[-1]).group(1))
            Path(target).write_bytes(outcome)
            return subject.subprocess.CompletedProcess(command, 0, "", "")

        patches = (
            patch("urllib.request.urlopen", urlopen),
            patch.object(subject.sys, "platform", platform),
            patch.object(subject.Path, "is_file", return_value=True),
            patch.object(subject, "REFIND_ZIP_SHA256", hashlib.sha256(b"OFFICIAL").hexdigest()),
        )
        return patches, runner, calls

    def test_download_survives_missing_root_certificates_on_a_fresh_windows(self):
        subject = load_subject()
        error = OSError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")
        patches, runner, calls = self._download_env(subject, python=error, curl=b"OFFICIAL",
                                                    powershell=OSError("unused"))
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertEqual(subject.fetch_refind_zip(runner=runner), b"OFFICIAL")
        self.assertEqual(calls, ["Python", "curl.exe"])

    def test_download_tries_every_method_and_mirror_until_the_checksum_matches(self):
        # Python gets a mirror's web page, curl.exe fails behind a proxy, PowerShell works.
        subject = load_subject()
        patches, runner, calls = self._download_env(
            subject, python=b"<html>mirror page</html>", curl=OSError("proxy"), powershell=b"OFFICIAL")
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertEqual(subject.fetch_refind_zip(runner=runner), b"OFFICIAL")
        self.assertEqual(calls, ["Python", "curl.exe", "PowerShell"])

    def test_download_without_internet_explains_and_changes_nothing(self):
        subject = load_subject()
        offline = OSError("getaddrinfo failed")
        patches, runner, calls = self._download_env(subject, python=offline, curl=offline,
                                                    powershell=offline)
        with patches[0], patches[1], patches[2], patches[3], \
             self.assertRaises(subject.ThemeError) as caught:
            subject.fetch_refind_zip(runner=runner)
        self.assertIn("--refind-zip", str(caught.exception))
        self.assertIn("Nothing was changed", str(caught.exception))
        self.assertEqual(len(calls), 3 * len(subject.REFIND_ZIP_URLS))

    def test_download_on_linux_uses_python_only(self):
        subject = load_subject()
        patches, runner, calls = self._download_env(
            subject, python=OSError("offline"), curl=b"OFFICIAL", powershell=b"OFFICIAL", platform="linux")
        with patches[0], patches[1], patches[2], patches[3], self.assertRaises(subject.ThemeError):
            subject.fetch_refind_zip(runner=runner)
        self.assertEqual(set(calls), {"Python"})

    def test_arch_follows_the_os_not_the_python_build(self):
        subject = load_subject()
        self.assertEqual(subject.windows_efi_arch({"PROCESSOR_ARCHITECTURE": "AMD64"}), "x64")
        self.assertEqual(subject.windows_efi_arch({"PROCESSOR_ARCHITECTURE": "x86",
                                                   "PROCESSOR_ARCHITEW6432": "ARM64"}), "aa64")

    def test_installs_refind_as_a_new_first_boot_entry(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            runner, calls = self._runner(BCD_FIRMWARE.replace("refind_x64", "other"))
            uefi, secure, arch, fetch = self._ready(subject)
            with uefi, secure, arch, fetch:
                target = subject.install_refind_windows([esp], runner=runner)
            self.assertEqual(target, esp / "EFI" / "refind")
            self.assertEqual((target / "refind_x64.efi").read_bytes(), b"EFI-BINARY")
            self.assertEqual((target / "refind.conf").read_bytes(), b"timeout 20\n")
            self.assertTrue((target / "icons" / "os_win.png").is_file())
            self.assertFalse((target / "refind_ia32.efi").exists())
            self.assertFalse(any(Path(raw).rglob("escape.png")))
            marker = json.loads((target / subject.REFIND_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["loader"], r"\EFI\refind\refind_x64.efi")
            bitlocker = next(i for i, c in enumerate(calls) if c[0] == "powershell")
            first_change = next(i for i, c in enumerate(calls) if "/copy" in c)
            self.assertLess(bitlocker, first_change)
            self.assertEqual(self._bcd(calls)[1:], [
                ("/copy", "{bootmgr}", "/d", "rEFInd"),
                ("/set", NEW_ENTRY, "device", f"partition={target.drive}"),
                ("/set", NEW_ENTRY, "path", r"\EFI\refind\refind_x64.efi"),
                ("/set", "{fwbootmgr}", "displayorder", NEW_ENTRY, "/addfirst"),
            ])
            self.assertFalse(any("{bootmgr}" in c and "/set" in c for c in self._bcd(calls)))

    def test_failed_boot_entry_removes_everything_it_added(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            runner, calls = self._runner("", fail_on="/addfirst")
            uefi, secure, arch, fetch = self._ready(subject)
            with uefi, secure, arch, fetch, self.assertRaises(subject.ThemeError):
                subject.install_refind_windows([esp], runner=runner)
            self.assertFalse((esp / "EFI" / "refind").exists())
            self.assertIn(("/delete", NEW_ENTRY), self._bcd(calls))

    def test_bitlocker_that_cannot_be_paused_stops_before_the_boot_order(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            runner, calls = self._runner("", bitlocker="")
            uefi, secure, arch, fetch = self._ready(subject)
            with uefi, secure, arch, fetch, self.assertRaises(subject.ThemeError) as caught:
                subject.install_refind_windows([esp], runner=runner)
            self.assertIn("BitLocker", str(caught.exception))
            self.assertEqual([c[0] for c in self._bcd(calls)], ["/enum"])
            self.assertFalse((esp / "EFI" / "refind").exists())

    def test_secure_boot_or_legacy_bios_changes_nothing(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            runner, calls = self._runner()
            for uefi, secure, text in ((True, True, "shutdown /r /fw"), (False, False, "legacy")):
                with patch.object(subject, "windows_firmware_is_uefi", return_value=uefi), \
                     patch.object(subject, "windows_secure_boot_enabled", return_value=secure), \
                     self.assertRaises(subject.ThemeError) as caught:
                    subject.install_refind_windows([esp], runner=runner)
                self.assertIn(text, str(caught.exception))
            # Secure Boot on: only BitLocker is paused, ahead of the firmware change
            self.assertEqual([c[0] for c in calls], ["powershell"])
            self.assertIn("DisableKeyProtectors", calls[0][-1])
            self.assertFalse((esp / "EFI" / "refind").exists())

    def test_never_overwrites_a_folder_it_does_not_own(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            (esp / "EFI" / "refind").mkdir()
            (esp / "EFI" / "refind" / "notes.txt").write_text("mine")
            runner, calls = self._runner()
            uefi, secure, arch, fetch = self._ready(subject)
            with uefi, secure, arch, fetch, self.assertRaises(subject.ThemeError):
                subject.install_refind_windows([esp], runner=runner)
            self.assertEqual((esp / "EFI" / "refind" / "notes.txt").read_text(), "mine")
            self.assertEqual(calls, [])

    def test_full_esp_is_refused_before_any_change(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            runner, calls = self._runner()
            uefi, secure, arch, fetch = self._ready(subject)
            usage = subject.shutil._ntuple_diskusage(100, 99, 1)
            with uefi, secure, arch, fetch, patch.object(subject.shutil, "disk_usage", return_value=usage), \
                 self.assertRaises(subject.ThemeError) as caught:
                subject.install_refind_windows([esp], runner=runner)
            self.assertIn("MB free", str(caught.exception))
            self.assertEqual(calls, [])

    def test_rerun_only_puts_rEFInd_first_again(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            refind = Path(raw) / "EFI" / "refind"
            refind.mkdir(parents=True)
            (refind / subject.REFIND_MARKER).write_text(json.dumps({"loader": r"\EFI\refind\refind_x64.efi"}))
            runner, calls = self._runner(BCD_FIRMWARE)
            subject.ensure_refind_boot_entry(refind, runner=runner)
            self.assertEqual(self._bcd(calls)[1:], [
                ("/set", "{fwbootmgr}", "displayorder", "{11111111-2222-3333-4444-555555555555}", "/addfirst"),
            ])
            self.assertTrue(any(c[0] == "powershell" for c in calls))

            first = BCD_FIRMWARE.replace(
                "{9dea862c-5cdd-4e70-acc1-f32b344d4795}\r\n                        {11111111-2222-3333-4444-555555555555}",
                "{11111111-2222-3333-4444-555555555555}\r\n                        {9dea862c-5cdd-4e70-acc1-f32b344d4795}")
            runner, calls = self._runner(first)
            subject.ensure_refind_boot_entry(refind, runner=runner)
            self.assertEqual(len(self._bcd(calls)), 1)
            self.assertFalse(any(c[0] == "powershell" for c in calls))

    def test_damaged_marker_is_reported_and_changes_nothing(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            refind = Path(raw)
            runner, calls = self._runner(BCD_FIRMWARE)
            for content in ("{}", "not json", json.dumps({"loader": r"\EFI\Microsoft\Boot\bootmgfw.efi"})):
                (refind / subject.REFIND_MARKER).write_text(content)
                with self.assertRaises(subject.ThemeError):
                    subject.ensure_refind_boot_entry(refind, runner=runner)
            self.assertEqual(calls, [])

    def test_install_theme_installs_rEFInd_first_when_missing(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            theme = WindowsInstallTests._built_theme(self, subject, root)
            esp = self._esp(root)
            runner, calls = self._runner("")

            @subject.contextlib.contextmanager
            def esps(_runner):
                yield [esp]

            uefi, secure, arch, fetch = self._ready(subject)
            with uefi, secure, arch, fetch, patch.object(subject, "mounted_windows_esps", esps):
                refind = subject.install_theme_windows(theme, runner=runner)
            self.assertEqual(refind.resolve(), (esp / "EFI" / "refind").resolve())
            self.assertIn(b"include themes/ghoul-cyber/theme.conf", (refind / "refind.conf").read_bytes())
            self.assertTrue((refind / "themes" / "ghoul-cyber" / "background.png").is_file())

    def test_remove_deletes_only_what_it_installed(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = self._esp(Path(raw))
            refind = esp / "EFI" / "refind"
            refind.mkdir()
            (refind / subject.REFIND_MARKER).write_text(json.dumps({"loader": r"\EFI\refind\refind_x64.efi"}))
            runner, calls = self._runner(BCD_FIRMWARE)

            @subject.contextlib.contextmanager
            def esps(_runner):
                yield [esp]

            with patch.object(subject, "mounted_windows_esps", esps):
                subject.remove_refind_windows(runner=runner)
            self.assertFalse(refind.exists())
            self.assertTrue((esp / "EFI" / "Microsoft" / "Boot" / "bootmgfw.efi").is_file())
            self.assertIn(("/delete", "{11111111-2222-3333-4444-555555555555}"), self._bcd(calls))
            with patch.object(subject, "mounted_windows_esps", esps), self.assertRaises(subject.ThemeError):
                subject.remove_refind_windows(runner=runner)


class DependencyBootstrapTests(unittest.TestCase):
    def test_refreshes_databases_when_they_are_missing(self):
        subject = load_subject()
        calls = []

        def runner(command):
            calls.append(command)
            if "-S" in command:
                return subject.subprocess.CompletedProcess(
                    command, 1, "", "warning: database file for 'core' does not exist\n"
                    "error: target not found: python-pillow",
                )
            return subject.subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(subject.os, "geteuid", return_value=0, create=True):
            subject.bootstrap_linux_dependencies(("Pillow",), runner, manager="pacman")
        self.assertEqual([c[1] for c in calls], ["-S", "-Sy"])
        self.assertIn("python-pillow", calls[-1])

    def test_apt_refreshes_lists_and_keeps_debconf_quiet(self):
        subject = load_subject()
        calls = []

        def runner(command):
            calls.append(command)
            failed = "install" in command and len([c for c in calls if "install" in c]) == 1
            return subject.subprocess.CompletedProcess(command, 1 if failed else 0, "", "E: Unable to locate")

        with patch.object(subject.os, "geteuid", return_value=0, create=True):
            subject.bootstrap_linux_dependencies(("Pillow", "refind", "font"), runner, manager="apt-get")
        self.assertEqual(calls[0], ("env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y",
                                    "python3-pil", "refind", "fonts-dejavu-core"))
        self.assertEqual(calls[1][-2:], ("apt-get", "update"))
        self.assertEqual(calls[2], calls[0])

    def test_unpackaged_or_unknown_manager_fails_clearly(self):
        subject = load_subject()
        with self.assertRaisesRegex(subject.ThemeError, "rodsbooks"):
            subject.bootstrap_linux_dependencies(("refind",), lambda c: None, manager="zypper")
        with patch.object(subject, "linux_package_manager", return_value=None):
            with self.assertRaisesRegex(subject.ThemeError, "no supported package manager"):
                subject.bootstrap_linux_dependencies(("efibootmgr",), lambda c: None)

    def test_every_manager_knows_every_dependency(self):
        subject = load_subject()
        for name, manager in subject.LINUX_PACKAGE_MANAGERS.items():
            self.assertEqual(set(manager.names), {"Pillow", "efibootmgr", "lsblk", "findmnt", "font", "refind"},
                             name)


class RefindInstallTests(unittest.TestCase):
    def test_refuses_with_secure_boot_on(self):
        subject = load_subject()
        with patch.object(subject, "secure_boot_enabled", return_value=True):
            with self.assertRaisesRegex(subject.ThemeError, "Secure Boot"):
                subject.install_refind(lambda c: None, assume_yes=True)

    def test_declined_or_non_interactive_does_nothing(self):
        subject = load_subject()
        calls = []
        with patch.object(subject, "secure_boot_enabled", return_value=False):
            for kwargs in ({"ask": lambda q: "n"}, {"interactive": False},
                           {"ask": lambda q: (_ for _ in ()).throw(EOFError())}):
                with self.assertRaisesRegex(subject.ThemeError, "--install-refind"):
                    subject.install_refind(lambda c: calls.append(c), **kwargs)
        self.assertEqual(calls, [])

    def test_installs_package_then_runs_refind_install(self):
        subject = load_subject()
        calls = []

        def runner(command):
            calls.append(command)
            return subject.subprocess.CompletedProcess(command, 0, "", "")

        with (
            patch.object(subject, "secure_boot_enabled", return_value=None),
            patch.object(subject.shutil, "which", return_value=None),
            patch.object(subject, "linux_package_manager", return_value="dnf"),
            patch.object(subject.os, "geteuid", return_value=0, create=True),
        ):
            subject.install_refind(runner, ask=lambda q: "tak")
        self.assertEqual(calls, [("dnf", "install", "-y", "rEFInd"), ("refind-install",)])

    def test_linux_only_and_other_distros_need_no_windows(self):
        subject = load_subject()
        ubuntu = subject.BootEntry("0001", "ubuntu", "c", r"\EFI\ubuntu\shimx64.efi")
        with patch.object(subject, "_os_release_id", return_value="ubuntu"):
            self.assertEqual(subject.assign_boot_roles([ubuntu], choose_dev=None, non_interactive=True), {})
        cachy = subject.BootEntry("0002", "CachyOS", "d", r"\vmlinuz-linux-cachyos")
        with patch.object(subject, "_os_release_id", return_value="cachyos"):
            roles = subject.assign_boot_roles([cachy], choose_dev=None, non_interactive=True)
        self.assertEqual(set(roles), {"cachyos"})
        win = subject.BootEntry("0003", "Windows Boot Manager", "e", r"\EFI\Microsoft\Boot\bootmgfw.efi")
        with patch.object(subject, "_os_release_id", return_value="fedora"):
            roles = subject.assign_boot_roles([win, ubuntu], choose_dev=None, non_interactive=True)
        self.assertEqual(set(roles), {"win_dev", "win_game"})

    def test_extra_tools_are_installed_from_packages_and_optional(self):
        subject = load_subject()
        installed = set()
        calls = []

        def runner(command):
            calls.append(command)
            if command[:2] == ("pacman", "-S"):
                installed.update(command[4:])
            if command[:2] == ("pacman", "-Si"):
                return subject.subprocess.CompletedProcess(command, 0, f"Name            : {command[2]}\n", "")
            return subject.subprocess.CompletedProcess(command, 0, "", "")

        def exists(path):
            text = path.as_posix()
            return (("edk2-shell" in installed and text.endswith("x64/Shell_Full.efi"))
                    or ("memtest86+-efi" in installed and text == "/boot/memtest86+/memtest.efi"))

        with (
            patch.object(subject, "_root_file_exists", side_effect=lambda p, r: exists(p)),
            patch.object(subject.os, "geteuid", return_value=0, create=True),
        ):
            planned = subject.plan_extra_tools(("shell", "memtest"), Path("/boot"), runner, manager="pacman")
            self.assertEqual(planned, (("/usr/share/edk2-shell/x64/Shell_Full.efi", "shellx64.efi"),
                                       ("/boot/memtest86+/memtest.efi", "memtest86.efi")))
            # no package on this distribution, or the install fails: skipped, never fatal
            installed.clear()
            self.assertEqual(subject.plan_extra_tools(("shell",), Path("/x"), runner, manager="dnf"), ())
            failing = lambda c: subject.subprocess.CompletedProcess(c, 1, "", "error")  # noqa: E731
            self.assertEqual(subject.plan_extra_tools(("memtest",), Path("/x"), failing, manager="pacman"), ())

    def test_extra_tools_skip_a_package_that_is_only_provided(self):
        subject = load_subject()
        calls = []

        def runner(command):   # CachyOS: memtest86+-efi resolves to memtest86+ (BIOS only)
            calls.append(command)
            return subject.subprocess.CompletedProcess(command, 0, "Name            : memtest86+\n", "")

        fetched = []
        with (
            patch.object(subject, "_root_file_exists", return_value=False),
            patch.object(subject, "_extract_from_arch", side_effect=lambda pkg, member, dest, r: fetched.append(pkg)),
        ):
            self.assertEqual(subject.plan_extra_tools(("memtest",), Path("/boot"), runner, manager="pacman"), ())
        self.assertFalse([c for c in calls if c[:2] == ("pacman", "-S")])   # the substitute is never installed
        self.assertEqual(fetched, ["memtest86+-efi"])                        # the EFI file comes from Arch

    def test_arch_efi_fallback_verifies_before_extracting(self):
        subject = load_subject()
        import io
        import urllib.request
        calls = []

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(url, timeout=0):
            calls.append(("GET", url))
            if url.endswith("/json/"):
                return Reply(json.dumps({"filename": "memtest86+-efi-7.20-2-any.pkg.tar.zst"}).encode())
            return Reply(b"data")

        def runner(command):
            calls.append(command)
            ok = not (command[0] == "pacman-key" and bad_signature)
            return subject.subprocess.CompletedProcess(command, 0 if ok else 1, "", "" if ok else "BAD signature")

        with (
            patch.object(urllib.request, "urlopen", side_effect=urlopen),
            patch.object(subject.os, "geteuid", return_value=0, create=True),
        ):
            bad_signature = False
            subject._extract_from_arch("memtest86+-efi", "boot/memtest86+/memtest.efi",
                                       "/usr/share/ghoul-cyber/memtest86.efi", runner)
            order = [c[0] for c in calls if not (isinstance(c, tuple) and c[0] == "GET")]
            self.assertEqual(order, ["pacman-key", "bsdtar", "install"])
            calls.clear()
            bad_signature = True
            with self.assertRaisesRegex(subject.ThemeError, "signature"):
                subject._extract_from_arch("memtest86+-efi", "boot/memtest86+/memtest.efi",
                                           "/usr/share/ghoul-cyber/memtest86.efi", runner)
            self.assertFalse([c for c in calls if c[0] in {"bsdtar", "install"}])

    def test_extra_tools_in_the_privileged_plan_are_checked(self):
        subject = load_subject()
        plan = subject.DeploymentPlan(Path("/t"), Path("/boot/EFI/refind"), (),
                                      tools=(("/usr/share/efi-shell-x64/shellx64.efi", "shellx64.efi"),))
        again = subject.deployment_plan_from_json(subject.deployment_plan_to_json(plan), validate=False)
        self.assertEqual(again.tools, plan.tools)
        for source, dest in (("/etc/shadow.efi", "shellx64.efi"), ("/usr/share/x/../../etc/a.efi", "shellx64.efi"),
                             ("/usr/share/a.efi", "../../refind_x64.efi"), ("/usr/share/a.txt", "memtest86.efi")):
            bad = subject.deployment_plan_to_json(plan).replace(
                '"/usr/share/efi-shell-x64/shellx64.efi"', json.dumps(source)).replace(
                '"shellx64.efi"', json.dumps(dest))
            with self.assertRaises(subject.ThemeError, msg=(source, dest)):
                subject.deployment_plan_from_json(bad, validate=False)

    def test_finds_refind_installed_as_fallback_loader(self):
        """refind-install upgrades a rEFInd found in EFI/BOOT instead of creating EFI/refind."""
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            esp = Path(raw)
            boot = esp / "EFI" / "BOOT"
            boot.mkdir(parents=True)
            (boot / "BOOTX64.EFI").write_bytes(b"MZ")
            other = esp / "EFI" / "other"
            other.mkdir()
            (other / "BOOTX64.EFI").write_bytes(b"MZ")
            (other / "refind.conf").write_text("", encoding="utf-8")
            with patch.object(subject.os, "geteuid", return_value=0, create=True):
                with self.assertRaises(subject.ThemeError):      # a plain fallback loader is not rEFInd
                    subject.find_refind_dir(None, (esp / "EFI" / "refind", boot, other))
                (boot / "refind.conf").write_text("timeout 5\n", encoding="utf-8")
                self.assertEqual(subject.find_refind_dir(None, (esp / "EFI" / "refind", boot)), boot.resolve())
                proper = esp / "EFI" / "refind"
                proper.mkdir()
                (proper / "refind.conf").write_text("", encoding="utf-8")
                (proper / "refind_x64.efi").write_bytes(b"MZ")
                self.assertEqual(subject.find_refind_dir(None, (proper, boot)), proper.resolve())
            entry = subject.BootEntry("0001", "x", "p", "/vmlinuz", mount_points=("/boot",))
            candidates = subject._refind_candidates([entry])
            self.assertLess(candidates.index(Path("/boot/EFI/refind")), candidates.index(Path("/boot/EFI/BOOT")))

    def test_three_windows_choice_never_pairs_a_system_with_itself(self):
        subject = load_subject()
        wins = [subject.BootEntry(f"000{i}", "Windows Boot Manager", str(i),
                                  r"\EFI\Microsoft\Boot\bootmgfw.efi") for i in range(3)]
        roles = subject.assign_boot_roles(wins, choose_dev=lambda options: 2, non_interactive=False)
        self.assertIs(roles["win_dev"], wins[2])
        self.assertIsNot(roles["win_game"], wins[2])


class CardNumberTests(unittest.TestCase):
    @staticmethod
    def make_card(subject, text="03", colour=(255, 255, 255)):
        card = Image.new("RGB", (512, 512), (2, 2, 2))
        draw = ImageDraw.Draw(card)
        draw.rectangle((20, 20, 491, 491), outline=(240, 240, 240), width=3)
        draw.text((60, 40), "WINDOWS // DEV", font=subject.find_font(None, 22), fill=(230, 230, 230))
        draw.text((48, 440), text, font=subject.find_font(None, 22), fill=colour)
        draw.line((90, 458, 130, 458), fill=(200, 200, 200), width=2)  # the dashes
        return card

    def bright_pixels(self, image, box):
        raw = image.convert("RGB").crop(box).tobytes()
        return sum(1 for i in range(0, len(raw), 3) if max(raw[i:i + 3]) > 150)

    def test_detects_number_in_bottom_left(self):
        subject = load_subject()
        info = subject.detect_card_number(self.make_card(subject, colour=(255, 0, 60)))
        self.assertIsNotNone(info)
        x0, y0, x1, y1 = (round(v * 512) for v in info.box)
        self.assertTrue(40 <= x0 <= 56 and 430 <= y0 <= 452 and x1 < 90 and y1 <= 466, info.box)
        self.assertEqual(info.colour, (255, 0, 60))

    def test_erases_or_redraws_number_and_keeps_the_rest(self):
        subject = load_subject()
        card = self.make_card(subject)
        info = subject.detect_card_number(card)
        blank = subject.apply_card_number(card, info, None)
        self.assertEqual(self.bright_pixels(blank, (40, 425, 88, 470)), 0)
        self.assertGreater(self.bright_pixels(blank, (90, 455, 131, 461)), 30)   # dashes stay
        self.assertGreater(self.bright_pixels(blank, (0, 0, 512, 100)), 100)     # header stays
        renumbered = subject.apply_card_number(card, info, 7)
        again = subject.detect_card_number(renumbered)
        self.assertIsNotNone(again)
        self.assertAlmostEqual(again.box[0], info.box[0], delta=0.02)
        self.assertAlmostEqual(again.box[3], info.box[3], delta=0.02)

    def test_card_without_number_is_left_alone(self):
        subject = load_subject()
        card = Image.new("RGB", (256, 256), (0, 0, 0))
        self.assertIsNone(subject.detect_card_number(card))
        self.assertIs(subject.apply_card_number(card, None, 3), card)

    def test_numbering_order(self):
        subject = load_subject()
        options = subject.default_options()
        # Linux-only PC: its card gets 01
        self.assertEqual(subject.card_numbers(options, ("linux",))["linux"], 1)
        # author's PC: two Windows installs + CachyOS -> 01 / 02 / 03 as painted
        numbers = subject.card_numbers(options, ("win_dev", "win_game", "cachyos"))
        self.assertEqual((numbers["win_dev"], numbers["win_game"], numbers["cachyos"]), (1, 2, 3))
        # menu entries come first
        options["entries"] = ({"label": "Arch", "card": "arch", "loader": "\\vmlinuz-linux",
                               "volume": "", "options": "", "disabled": False},)
        self.assertEqual(subject.card_numbers(options, ("cachyos",))["arch"], 1)
        # custom order: cards left out get no number
        options["cards.order"] = ("cachyos", "win_game")
        self.assertEqual(subject.card_numbers(options, ()), {"cachyos": 1, "win_game": 2})
        options["cards.numbers"] = False
        self.assertEqual(subject.card_numbers(options, ()), {})

    def test_order_option_validation(self):
        subject = load_subject()
        options, errors, _ = subject.validate_options({"cards": {"order": ["linux", "cachyos"]}})
        self.assertEqual(errors, [])
        self.assertEqual(options["cards.order"], ("linux", "cachyos"))
        for bad in (["linux", "linux"], ["beos"], "linux"):
            _, errors, _ = subject.validate_options({"cards": {"order": bad}})
            self.assertEqual(len(errors), 1, bad)


class RowOptionsTests(unittest.TestCase):
    def test_visible_tiles_sizes_the_os_row_like_refind_does(self):
        subject = load_subject()
        options = subject.default_options()
        for resolution in (subject.Resolution(3840, 2160), subject.Resolution(1920, 1080)):
            self.assertEqual(subject.visible_tiles(options, resolution), 3)      # auto
            for wanted in (2, 3, 4, 5, 6):
                options["layout.visible_tiles"] = wanted
                big, _ = subject.icon_geometry(options, resolution)
                # rEFInd menu.c: MaxVisible = UGAWidth / (TileSize + 8) - 1
                self.assertEqual(resolution.width // (big + 8) - 1, wanted, (resolution, wanted))
            options["layout.visible_tiles"] = 0

    def test_scroll_arrows_hidden_by_default_and_old_configs_migrate(self):
        subject = load_subject()
        conf = subject.render_theme_conf(subject.default_options(), subject.Resolution(1920, 1080))
        self.assertIn("arrows", next(l for l in conf.splitlines() if l.startswith("hideui")))
        options, errors, _ = subject.validate_options({"layout": {"scroll_arrows": True},
                                                       "refind": {"hideui": ["arrows", "hints"]}})
        self.assertEqual(errors, [])
        conf = subject.render_theme_conf(options, subject.Resolution(1920, 1080))
        self.assertEqual(next(l for l in conf.splitlines() if l.startswith("hideui")), "hideui hints")

    def test_max_tools_keeps_the_most_important_ones(self):
        subject = load_subject()
        options = subject.default_options()
        options["refind.max_tools"] = 5
        self.assertEqual(subject.shown_tools(options), ("firmware", "reboot", "shutdown", "shell", "memtest"))
        conf = subject.render_theme_conf(options, subject.Resolution(1920, 1080))
        self.assertIn("showtools firmware, reboot, shutdown, shell, memtest", conf)


class ToolCardTests(unittest.TestCase):
    def test_every_tool_gets_the_same_frame_to_the_pixel(self):
        subject = load_subject()
        cards = []
        for size, frame, glyph in ((900, (60, 80, 840, 820), (300, 300, 600, 600)),
                                   (1024, (10, 10, 1013, 1013), (100, 400, 900, 600)),
                                   (700, (150, 90, 610, 640), (250, 200, 450, 500))):
            art = Image.new("RGBA", (size, size), (0, 0, 0, 255))
            draw = ImageDraw.Draw(art)
            draw.rectangle(frame, outline=(250, 250, 250, 255), width=size // 90)   # the artwork's own frame
            draw.ellipse(glyph, fill=(255, 0, 60, 255))
            cards.append(subject.tool_card(art, 240))
        band = int(240 * subject.TOOL_FRAME["band"]) - 3
        mask = Image.new("L", (240, 240), 255)
        ImageDraw.Draw(mask).rectangle((band, band, 239 - band, 239 - band), fill=0)
        frames = [Image.composite(c, Image.new("RGBA", c.size), mask).tobytes() for c in cards]
        self.assertTrue(all(f == frames[0] for f in frames))
        self.assertTrue(all(c.size == (240, 240) for c in cards))
        self.assertNotEqual(cards[0].tobytes(), cards[1].tobytes())   # the glyph itself is kept


class SkinTests(unittest.TestCase):
    def test_parse_hex_color(self):
        subject = load_subject()
        self.assertEqual(subject.parse_hex_color("#A020F0"), (160, 32, 240))
        with self.assertRaises(subject.ThemeError):
            subject.parse_hex_color("violet")

    def test_load_skin_reads_config_and_art(self):
        subject = load_subject()
        with tempfile.TemporaryDirectory() as raw:
            skins = Path(raw)
            (skins / "demo").mkdir()
            (skins / "demo" / "theme.json").write_text(
                json.dumps({"accent": "#2BB8FF", "title": "DEMO", "art_brightness": 0.5}),
                encoding="utf-8",
            )
            Image.new("RGB", (32, 18)).save(skins / "demo" / "art.png")
            skin = subject.load_skin("demo", skins)
            self.assertEqual(skin.accent, (43, 184, 255))
            self.assertEqual(skin.title, "DEMO")
            self.assertEqual(skin.art_brightness, 0.5)
            self.assertEqual(subject.list_skins(skins), ["demo"])
            with self.assertRaises(subject.ThemeError):
                subject.load_skin("missing", skins)

    def test_recolor_accent_moves_red_but_keeps_white_and_alpha(self):
        subject = load_subject()
        image = Image.new("RGBA", (2, 1))
        image.putpixel((0, 0), (255, 0, 60, 128))
        image.putpixel((1, 0), (240, 240, 240, 255))
        result = subject.recolor_accent(image, (124, 255, 58))
        red_r, red_g, red_b, red_a = result.getpixel((0, 0))
        self.assertGreater(red_g, red_r)
        self.assertEqual(red_a, 128)
        self.assertEqual(result.getpixel((1, 0)), (240, 240, 240, 255))


if __name__ == "__main__":
    unittest.main()
