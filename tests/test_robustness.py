"""Randomised robustness tests ("fuzzing") for the builder.

Contract checked here: whatever a user (or a broken file) throws at the tool,
it either works or stops with a clear message -- never a raw traceback, never
a half-written theme, never an unsafe theme.conf.

    FUZZ_ROUNDS=500 FUZZ_SEED=123 python -m pytest tests/test_robustness.py

A failing case prints its seed, so it can be replayed exactly.
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_build_and_deploy_theme import load_subject, write_synthetic_assets  # noqa: E402

ROUNDS = int(os.environ.get("FUZZ_ROUNDS", "25"))
SEED = int(os.environ.get("FUZZ_SEED", str(random.randrange(1 << 30))))

NASTY_TEXT = [
    "", " ", "a" * 10_000, '"', '\\', "{", "}", "\n", "\r\n", "\t", "\x00", "\x1b[31m",
    "../../etc/passwd", "C:\\Windows\\System32", "%s%n", "${HOME}", "$(reboot)", "`id`",
    "死神核", "リナクス", "🔥💀", "\u202eevil", "\ufeffbom", "é" * 300, "null", "true", "0x41",
]


def rand_scalar(rng: random.Random, depth: int = 0):
    kind = rng.randrange(12 if depth < 3 else 9)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.choice([0, -1, 1, 2**31, -(2**63), 10**30, rng.randint(-1000, 1000)])
    if kind == 3:
        return rng.choice([0.0, -0.0, 1e308, -1e308, 1e-308, math.nan, math.inf, -math.inf,
                           rng.uniform(-5, 5)])
    if kind in (4, 5, 6):
        return rng.choice(NASTY_TEXT)
    if kind == 7:
        return "".join(chr(rng.randrange(1, 0x2FFFF)) for _ in range(rng.randrange(0, 40)))
    if kind == 8:
        return rng.choice(["#FF003C", "#fff", "#GGGGGG", "FF003C", "#12345678", "red", "#00ff00"])
    if kind in (9, 10):
        return [rand_scalar(rng, depth + 1) for _ in range(rng.randrange(0, 6))]
    return {rng.choice(["a", "label", "card", "loader", "", "\x00"]): rand_scalar(rng, depth + 1)
            for _ in range(rng.randrange(0, 5))}


def rand_value_for(subject, spec, rng: random.Random):
    """Mostly plausible values for an option, sometimes boundary or garbage."""
    roll = rng.random()
    if roll < 0.25:
        return rand_scalar(rng)
    kind = spec.kind
    if kind == "bool":
        return rng.choice([True, False])
    if kind in {"int", "float"}:
        lo, hi = spec.minimum, spec.maximum
        value = rng.choice([lo, hi, lo - 1, hi + 1, rng.uniform(lo, hi)])
        return int(value) if kind == "int" and rng.random() < 0.8 else value
    if kind == "choice":
        return rng.choice(list(spec.choices) + ["", "4000x3000"])
    if kind in {"multi", "order"}:
        items = list(spec.choices)
        rng.shuffle(items)
        picked = items[: rng.randrange(0, len(items) + 1)]
        if rng.random() < 0.15:
            picked.append(rng.choice(items + ["bogus"]))
        return picked
    if kind in {"text", "color"}:
        return rng.choice(NASTY_TEXT + ["", "CachyOS", "#A020F0", "#FF003C"])
    if kind == "lines":
        return [rng.choice(NASTY_TEXT) for _ in range(rng.randrange(0, 7))]
    if kind == "entries":
        entries = []
        for _ in range(rng.randrange(0, 20)):
            entry = {
                "label": rng.choice(["Windows 11", "Arch", "", "x" * 41] + NASTY_TEXT),
                "card": rng.choice(list(subject.ENTRY_CARDS) + ["beos", ""]),
                "loader": rng.choice([
                    "\\EFI\\Microsoft\\Boot\\bootmgfw.efi", "/vmlinuz-linux", "\\EFI\\..\\x.efi",
                    "\\\\EFI", "EFI/no-leading-slash.efi", "\\EFI\\a b\\c.efi"] + NASTY_TEXT),
                "volume": rng.choice(["", "ESP", "af082e06-e080-47ed-b3e8-450398c9ec9e"] + NASTY_TEXT),
                "options": rng.choice(["", "quiet splash", "root=UUID=1234 rw"] + NASTY_TEXT),
                "disabled": rng.choice([True, False, "yes", 1]),
            }
            for key in list(entry):
                if rng.random() < 0.1:
                    del entry[key]
            entries.append(entry if rng.random() > 0.05 else rand_scalar(rng))
        return entries
    return rand_scalar(rng)


def rand_config(subject, rng: random.Random) -> object:
    if rng.random() < 0.05:
        return rand_scalar(rng)          # not even an object
    flat = {}
    for spec in subject.OPTION_SPECS:
        if rng.random() < 0.45:
            flat[spec.key] = rand_value_for(subject, spec, rng)
    for _ in range(rng.randrange(0, 3)):
        flat[rng.choice(["layout.nope", "hud", "zzz", "_comment", "version", "theme"])] = rand_scalar(rng)
    if rng.random() < 0.5:
        return subject.nest_options({k: v for k, v in flat.items() if "." in k}) | {
            k: v for k, v in flat.items() if "." not in k}
    return flat


def assert_safe_theme_conf(test: unittest.TestCase, text: str, where: str) -> None:
    depth = 0
    for line in text.splitlines():
        test.assertFalse(re.search(r"[\x00-\x08\x0b-\x1f\x7f]", line), f"{where}: control char in {line!r}")
        test.assertLessEqual(len(line), 600, f"{where}: absurd line")
        test.assertEqual(line.count('"') % 2, 0, f"{where}: unbalanced quotes in {line!r}")
        depth += line.count("{") - line.count("}")
        test.assertIn(depth, (0, 1), f"{where}: bad nesting at {line!r}")
    test.assertEqual(depth, 0, f"{where}: unclosed menuentry")


def random_image(rng: random.Random):
    mode = rng.choice(["1", "L", "LA", "P", "RGB", "RGBA", "I", "F", "CMYK"])
    w = rng.choice([1, 2, 3, 17, 64, 255, 512, 1000, rng.randrange(1, 1400)])
    h = rng.choice([1, 2, 3, 17, 64, 255, 512, 1000, rng.randrange(1, 1400), w])
    base = Image.new("RGB", (w, h), tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(base)
    for _ in range(rng.randrange(0, 30)):
        x0, y0 = rng.randrange(w), rng.randrange(h)
        box = (x0, y0, x0 + rng.randrange(1, max(2, w // 3)), y0 + rng.randrange(1, max(2, h // 3)))
        colour = tuple(rng.randrange(256) for _ in range(3))
        (draw.rectangle if rng.random() < 0.7 else draw.ellipse)(box, fill=colour)
    if rng.random() < 0.3:
        noise = Image.effect_noise((w, h), rng.uniform(10, 120)).convert("RGB")
        base = Image.blend(base, noise, rng.random())
    return base.convert(mode) if mode != "RGB" else base


class RobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject = load_subject()
        print(f"\n[fuzz] seed={SEED} rounds={ROUNDS}")

    def rng(self, salt: str) -> random.Random:
        return random.Random(f"{SEED}-{salt}")

    # ---- configuration --------------------------------------------------
    def test_validate_options_never_crashes_and_is_idempotent(self):
        s, rng = self.subject, self.rng("validate")
        for i in range(ROUNDS * 20):
            raw = rand_config(s, rng)
            with self.subTest(case=i, seed=SEED):
                options, errors, _warnings = s.validate_options(raw)
                self.assertEqual(set(options), set(s.OPTION_BY_KEY))
                again, errors2, _ = s.validate_options(s.nest_options(options))
                self.assertEqual(errors2, [], f"validated options do not re-validate: {raw!r:.300}")
                self.assertEqual(again, options)
                res = s.parse_resolution(options["layout.resolution"])
                assert_safe_theme_conf(self, s.render_theme_conf(options, res), f"case {i}")
                s.card_numbers(options, rng.choice([(), ("linux",), ("win_dev", "win_game", "cachyos")]))

    def test_save_and_load_round_trip(self):
        s, rng = self.subject, self.rng("roundtrip")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "boot-config.json"
            for i in range(ROUNDS * 4):
                options, _errors, _ = s.validate_options(rand_config(s, rng))
                with self.subTest(case=i, seed=SEED):
                    s.save_options(options, path, theme=rng.choice([None, "night-city"]))
                    self.assertEqual(s.load_options(path), options)
                    self.assertFalse((Path(raw) / "boot-config.json.tmp").exists())

    def test_broken_config_files_fail_cleanly(self):
        s, rng = self.subject, self.rng("files")
        samples = [b"", b"{", b"\xff\xfe\x00garbage", b"\xef\xbb\xbf{}", b"[]", b"null", b"42",
                   b'{"layout": {"resolution": "1920x1080"}', b'{"a":' * 5000,
                   json.dumps({"layout": {"icon_size": 10**400}}).encode()]
        for _ in range(ROUNDS):
            samples.append(bytes(rng.randrange(256) for _ in range(rng.randrange(0, 400))))
            samples.append(json.dumps(rand_config(s, rng), allow_nan=True).encode("utf-8", "surrogatepass"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "cfg.json"
            for i, data in enumerate(samples):
                path.write_bytes(data)
                with self.subTest(case=i, seed=SEED):
                    try:
                        s.load_options(path)
                    except s.ThemeError:
                        pass
            with self.assertRaises(s.ThemeError):
                s.load_options(Path(raw))                     # a directory
            with self.assertRaises(s.ThemeError):
                s.load_options(Path(raw) / "missing.json")

    # ---- card numbers ---------------------------------------------------
    def test_card_numbers_are_consecutive(self):
        s, rng = self.subject, self.rng("numbers")
        for i in range(ROUNDS * 10):
            options, _e, _w = s.validate_options(rand_config(s, rng))
            detected = tuple(rng.choice(s.NUMBERED_CARDS + ("bogus",)) for _ in range(rng.randrange(0, 5)))
            numbers = s.card_numbers(options, detected)
            with self.subTest(case=i, seed=SEED):
                self.assertTrue(set(numbers) <= set(s.NUMBERED_CARDS))
                self.assertEqual(sorted(numbers.values()), list(range(1, len(numbers) + 1)))

    def test_number_detection_survives_any_image(self):
        s, rng = self.subject, self.rng("images")
        for i in range(ROUNDS * 3):
            image = random_image(rng)
            with self.subTest(case=i, seed=SEED, mode=image.mode, size=image.size):
                info = s.detect_card_number(image)
                if info is None or rng.random() < 0.3:
                    info = s.CardNumber(
                        box=tuple(rng.choice([-1.0, 0.0, 0.5, 1.0, 2.0, rng.random()]) for _ in range(4)),
                        colour=tuple(rng.randrange(256) for _ in range(3)),
                        background=tuple(rng.randrange(256) for _ in range(3)),
                        stroke=rng.choice([0.0, 0.1, 5.0, -1.0]),
                        glow=rng.random() < 0.5,
                        ink=rng.choice([0, 150, 255]),
                    )
                out = s.apply_card_number(image, info, rng.choice([None, 0, 1, 7, 42, 99, 100]))
                self.assertEqual((out.size, out.mode), (image.size, image.mode))

    def test_detect_systems_never_raises(self):
        s, rng = self.subject, self.rng("systems")

        def runner(*_args, **_kwargs):
            roll = rng.random()
            if roll < 0.3:
                raise rng.choice([OSError("no efibootmgr"), subprocess.TimeoutExpired("x", 1),
                                  PermissionError("denied"), FileNotFoundError("x")])
            stdout = rng.choice([None, "", "garbage", "Boot0000* Windows Boot Manager\n" * rng.randrange(5),
                                 bytes(8).decode()])
            return subprocess.CompletedProcess(["efibootmgr"], 0, stdout=stdout, stderr="")

        for i in range(ROUNDS * 4):
            with self.subTest(case=i, seed=SEED):
                found = s.detect_systems(runner)
                self.assertTrue(set(found) <= set(s.NUMBERED_CARDS))

    def test_system_output_parsers_fail_cleanly(self):
        """efibootmgr / lsblk / PowerShell / plan JSON differ on every PC."""
        s, rng = self.subject, self.rng("parsers")
        efi_lines = [
            "BootCurrent: 0002", "Timeout: 0 seconds", "BootOrder: 0000,0001",
            "Boot0000* Windows Boot Manager\tHD(1,GPT,04957f85-f857-464f-864c-a149a8caec1e,0x800,0x32000)/"
            "File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)",
            "Boot0001* CachyOS\tHD(1,GPT,8cbb789f-09e4-464f-864c-a149a8caec1e,0x800,0x32000)/File(\\vmlinuz-linux-cachyos)",
            "Boot0002* UEFI Misc Device\tPciRoot(0x0)/Pci(0x3,0x0)", "Boot0003 HD(,GPT,,)/File()", "Boot*",
        ]
        lsblk_good = {"blockdevices": [{"path": "/dev/vda", "type": "disk", "children": [
            {"path": "/dev/vda1", "type": "part", "partuuid": "04957f85-f857-464f-864c-a149a8caec1e",
             "label": "EFI", "partlabel": "EFI", "size": 1, "mountpoints": ["/boot"]}]}]}
        for i in range(ROUNDS * 6):
            lines = [rng.choice(efi_lines + NASTY_TEXT) for _ in range(rng.randrange(0, 12))]
            if rng.random() < 0.3:
                lines = [line[: rng.randrange(len(line) + 1)] for line in lines]
            lsblk = rng.choice([json.dumps(lsblk_good), "", "{", "null", "[]",
                                json.dumps({"blockdevices": rand_scalar(rng)}),
                                json.dumps({"blockdevices": [rand_scalar(rng)]})])
            with self.subTest(case=i, seed=SEED):
                for call in (lambda: s.parse_efibootmgr("\n".join(lines)),
                             lambda: s.parse_lsblk(lsblk),
                             lambda: s.deployment_plan_from_json(rng.choice(
                                 ["", "{}", "[]", json.dumps(rand_config(s, rng)), "{" * 3000]))):
                    try:
                        call()
                    except s.ThemeError:
                        pass

                def ps_runner(*_a, **_k):
                    out = rng.choice(["", "[]", "{}", "null", "garbage", json.dumps(rand_scalar(rng)),
                                      json.dumps([{"DiskNumber": 0, "PartitionNumber": 1, "DriveLetter": ""}]),
                                      json.dumps({"DiskNumber": "x", "PartitionNumber": None})])
                    return subprocess.CompletedProcess(["powershell"], rng.choice([0, 0, 1]), stdout=out, stderr="")
                try:
                    s.list_windows_esps(ps_runner)
                except s.ThemeError:
                    pass

    # ---- whole program ----------------------------------------------------
    def make_skin(self, skins: Path, name: str, rng: random.Random) -> None:
        folder = skins / name
        folder.mkdir(parents=True)
        roll = rng.random()
        if roll < 0.15:
            (folder / "theme.json").write_bytes(bytes(rng.randrange(256) for _ in range(50)))
        elif roll < 0.3:
            (folder / "theme.json").write_text(json.dumps(rand_scalar(rng)), encoding="utf-8")
        else:
            config = {"accent": rng.choice(["#A020F0", "#GG0000", "", "#fff"]),
                      "title": rng.choice(NASTY_TEXT), "kanji": rng.choice(NASTY_TEXT),
                      "tagline": rng.choice(NASTY_TEXT),
                      "art_brightness": rng.choice([1.0, 0.0, -3, 99, "bright", None])}
            (folder / "theme.json").write_text(json.dumps(config), encoding="utf-8")
        art = rng.random()
        if art < 0.6:
            random_image(rng).convert("RGB").save(folder / "art.jpg")
        elif art < 0.8:
            (folder / "art.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(rng.randrange(256) for _ in range(64)))
        for stem in ("selection_item_linux", "card_linux", "selection_box"):
            roll = rng.random()
            if roll < 0.25:
                random_image(rng).convert("RGBA").save(folder / f"{stem}.png")
            elif roll < 0.35:
                (folder / f"{stem}.png").write_bytes(b"not an image")

    def test_cli_never_crashes(self):
        s, rng = self.subject, self.rng("cli")
        resolutions = ["1920x1080", "1280x720", "192x108", "3840x2160", "1920x1200", "abc", "0x0",
                       "99984x56241", "7680x4320"]
        for i in range(max(3, ROUNDS // 3)):
            with tempfile.TemporaryDirectory() as raw, self.subTest(case=i, seed=SEED):
                root = Path(raw)
                source, skins, out = root / "src", root / "themes", root / "out" / "ghoul-cyber"
                source.mkdir()
                write_synthetic_assets(source)
                if rng.random() < 0.2:
                    victim = rng.choice(sorted(source.iterdir()))
                    victim.write_bytes(b"broken" if rng.random() < 0.5 else b"")
                skins.mkdir()
                theme = rng.choice(["ghoul-cyber", "demo", "missing", "../evil", "DEMO"])
                self.make_skin(skins, "demo", rng)
                config = root / "cfg.json"
                config.write_text(json.dumps(rand_config(s, rng)), encoding="utf-8")
                argv = ["--build-only", "--theme", theme, "--source-dir", str(source),
                        "--output-dir", str(out), "--cpu", "CPU", "--ram", "RAM", "--gpu", "GPU",
                        "--nvme", "1 TB", "--config", str(config),
                        "--resolution", rng.choice(resolutions)]
                old_skins = s.SKINS_DIR
                s.SKINS_DIR = skins
                try:
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                        try:
                            code = s.main(argv)
                        except SystemExit as exc:      # argparse rejects a bad flag value
                            code = exc.code
                finally:
                    s.SKINS_DIR = old_skins
                self.assertIn(code, (0, 2), err.getvalue()[-500:])
                if code == 0:
                    s.validate_theme(out, s.parse_resolution(
                        json.loads((out / "install-state.json").read_text())["resolution"]))
                else:
                    self.assertNotIn("Traceback", err.getvalue())

    def test_preview_never_crashes(self):
        s, rng = self.subject, self.rng("preview")
        themes = ["ghoul-cyber", *s.list_skins()]
        for i in range(max(3, ROUNDS // 3)):
            options, _e, _w = s.validate_options(rand_config(s, rng))
            with self.subTest(case=i, seed=SEED):
                try:
                    image = s.render_preview(rng.choice(themes), options, width=rng.choice([320, 640, 1280]))
                except s.ThemeError:
                    continue
                self.assertEqual(image.width in (320, 640, 1280), True)


if __name__ == "__main__":
    unittest.main()
