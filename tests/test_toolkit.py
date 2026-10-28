"""Unit tests intentionally use synthetic files/devices; no disk actions."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolkit

SAMPLE_COMMAND = (
    "printf '%s clk_ignore_unused pd_ignore_unused arm64.nopauth systemd.mask=tpm2.target\\n' "
    '"$(sed -n \'s/^options //p\' /boot/loader/entries/*.conf | head -1)" '
    "> /etc/kernel/cmdline"
)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.base = Path(self.context.name)
        self.source = self.base / "source"
        self.profile = self.source / "configs/releng"
        (self.profile / "airootfs/root").mkdir(parents=True)
        (self.source / "scripts").mkdir()
        (self.profile / "profiledef.sh").write_text(
            'iso_name="archlinux-sp11"\nfile_permissions=(\n  ["/root"]="0:0:750"\n)\n'
        )
        (self.profile / "airootfs/root/sp11.json").write_text(json.dumps({
            "kernels": ["linux-sp11"],
            "bootloader_config": {"bootloader": "Systemd-boot", "uki": False},
            "packages": ["linux-sp11-uki", "sp11-grab-fw"],
            "custom_commands": [SAMPLE_COMMAND, "linux-sp11-mkuki"],
        }))
        (self.profile / "packages.aarch64").write_text("base\nlinux-sp11\n")
        (self.profile / "pacman.conf").write_text("[core]\n")
        (self.source / "scripts/build-iso.sh").write_text("#!/bin/bash\n")

    def stage(self):
        with patch.object(toolkit, "check_source", return_value=(self.source, 123456789)):
            return toolkit.prepare(self.source, self.base / "stage")

    def test_prepare_and_verify_keep_surface_boot_sequence(self):
        staged = self.stage()
        manifest = toolkit.verify(staged)
        self.assertEqual(manifest["upstream_commit"], toolkit.LOCK["upstream_commit"])
        preset = json.loads((staged / "configs/releng/airootfs/root/sp11.json").read_text())
        self.assertEqual(preset["custom_commands"][:2], [SAMPLE_COMMAND, "linux-sp11-mkuki"])
        self.assertEqual(preset["kernels"], ["linux-sp11"])
        self.assertFalse(preset["bootloader_config"]["uki"])
        payload = (staged / "configs/releng/airootfs/usr/local/share/sp11-cachy/postinstall.sh").read_bytes()
        self.assertIn(base64.b64encode(payload).decode(), preset["custom_commands"][2])
        self.assertNotIn("plasma", (staged / "configs/releng/packages.aarch64").read_text())

    def test_upstream_dangling_service_symlink_preserved(self):
        service = self.profile / "airootfs/etc/systemd/system/multi-user.target.wants"
        service.mkdir(parents=True)
        (service / "sshd.service").symlink_to("/usr/lib/systemd/system/sshd.service")
        staged = self.stage()
        copied = staged / "configs/releng/airootfs/etc/systemd/system/multi-user.target.wants/sshd.service"
        self.assertTrue(copied.is_symlink())
        self.assertEqual(copied.readlink().as_posix(), "/usr/lib/systemd/system/sshd.service")
        toolkit.verify(staged)

    def test_prepare_never_overwrites_existing_output(self):
        self.stage()
        with patch.object(toolkit, "check_source", return_value=(self.source, 1234)):
            with self.assertRaises(FileExistsError):
                toolkit.prepare(self.source, self.base / "stage")

    def test_stage_tampering_fails_verification(self):
        stage = self.stage()
        profile = stage / "configs/releng/profiledef.sh"
        profile.write_text(profile.read_text() + "# tampered\n")
        with self.assertRaisesRegex(ValueError, "modification"):
            toolkit.verify(stage)

    def test_changed_boot_commands_fail_at_prepare(self):
        path = self.profile / "airootfs/root/sp11.json"
        payload = json.loads(path.read_text())
        payload["custom_commands"][1] = "generic-kernel-hook"
        path.write_text(json.dumps(payload))
        with patch.object(toolkit, "check_source", return_value=(self.source, 1234)):
            with self.assertRaisesRegex(ValueError, "custom commands"):
                toolkit.prepare(self.source, self.base / "stage")

    def test_build_is_preview_only_by_default(self):
        stage = self.stage()
        image = "ironrobin/archports-aarch64@sha256:" + "a" * 64
        with patch.object(toolkit.subprocess, "run", side_effect=AssertionError("Docker executed")):
            cmd = toolkit.build(stage, image)
        self.assertIn("--privileged", cmd)
        self.assertIn(image, cmd)
        self.assertFalse((stage / "out").exists())

    def test_mutable_build_image_refused(self):
        stage = self.stage()
        with self.assertRaisesRegex(ValueError, "immutable"):
            toolkit.build(stage, "ironrobin/archports-aarch64:latest")

    def test_source_pin_rejects_different_commit(self):
        with patch.object(toolkit, "command", return_value="f" * 40):
            with self.assertRaisesRegex(ValueError, "Expected upstream"):
                toolkit.check_source(self.source)

    def test_shell_scripts_parse(self):
        repo = Path(__file__).resolve().parents[1]
        for script in (
            repo / "payload/postinstall.sh",
            repo / "overlay/airootfs/usr/local/bin/sp11-cachy-preflight",
            repo / "overlay/airootfs/usr/local/bin/sp11-cachy-install",
        ):
            subprocess.run(["bash", "-n", str(script)], check=True)

    def test_install_wrapper_only_launches_interactive_archinstall(self):
        wrapper = (Path(__file__).resolve().parents[1] /
                   "overlay/airootfs/usr/local/bin/sp11-cachy-install").read_text()
        self.assertIn('exec archinstall --config /root/sp11.json', wrapper)
        for forbidden in ("wipefs", "sgdisk", "parted", "mkfs", "dd if=", "--noconfirm"):
            self.assertNotIn(forbidden, wrapper)


if __name__ == "__main__":
    unittest.main()
