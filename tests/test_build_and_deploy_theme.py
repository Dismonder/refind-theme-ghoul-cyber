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
                subject.THEME_CONF,
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


if __name__ == "__main__":
    unittest.main()
