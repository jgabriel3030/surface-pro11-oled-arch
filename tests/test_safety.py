"""Fail-closed disk policy and interactive approval tests."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import patch

SAFETY_PATH = (Path(__file__).resolve().parents[1] /
               "overlay/airootfs/usr/local/share/sp11-cachy/safety.py")
spec = importlib.util.spec_from_file_location("sp11_safety", SAFETY_PATH)
safety = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safety)


def disk():
    return {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk",
            "size": 512 * 1024**3, "serial": "SURFACE123456", "model": "Surface NVMe",
            "rm": False, "ro": False, "tran": "nvme", "mountpoints": [None],
            "children": [{"path": "/dev/nvme0n1p1", "type": "part", "mountpoints": [None]}]}


class SafetyTests(unittest.TestCase):
    def test_valid_internal_nvme(self):
        self.assertEqual(safety.check_disk([disk()], "/dev/nvme0n1")["serial"], "SURFACE123456")

    def test_partitions_are_not_accepted(self):
        with self.assertRaisesRegex(safety.UnsafeTarget, "complete internal"):
            safety.check_disk([disk()], "/dev/nvme0n1p1")

    def test_usb_and_removable_rejected(self):
        for update in ({"tran": "usb"}, {"rm": True}):
            target = disk()
            target.update(update)
            with self.subTest(update=update), self.assertRaises(safety.UnsafeTarget):
                safety.check_disk([target], target["path"])

    def test_mounted_partition_rejected(self):
        target = disk()
        target["children"][0]["mountpoints"] = ["/mnt/windows"]
        with self.assertRaisesRegex(safety.UnsafeTarget, "mounted"):
            safety.check_disk([target], target["path"])

    def test_readonly_missing_serial_and_tiny_device_rejected(self):
        for update in ({"ro": True}, {"serial": ""}, {"size": 1024}):
            target = disk()
            target.update(update)
            with self.subTest(update=update), self.assertRaises(safety.UnsafeTarget):
                safety.check_disk([target], target["path"])

    def test_fingerprint_depends_on_physical_disk(self):
        original = safety.approval_phrase(disk())
        other = disk()
        other["serial"] = "DIFFERENT1234"
        self.assertNotEqual(original, safety.approval_phrase(other))
        self.assertTrue(original.startswith("ERASE /dev/nvme0n1 "))

    def test_device_tree_requires_surface_pro_11(self):
        self.assertTrue(safety.surface_model_matches("Microsoft Surface Pro 11 OLED", ""))
        self.assertTrue(safety.surface_model_matches("", "qcom,x1e80100\x00microsoft,denali-oled"))
        self.assertFalse(safety.surface_model_matches("Lenovo laptop", "qcom,x1e80100"))

    def test_non_interactive_approval_blocked(self):
        class FakeStdin:
            def isatty(self): return False

        patches = [
            patch.object(safety.platform, "machine", return_value="aarch64"),
            patch.object(safety, "hardware_identity", return_value=("Microsoft Surface Pro 11", "")),
            patch.object(safety, "live_blocks", return_value=[disk()]),
            patch.object(safety.os.path, "realpath", side_effect=lambda s: s),
            patch.object(safety.os, "stat", return_value=type("Stat", (), {"st_mode": stat.S_IFBLK})()),
            patch.object(safety.sys, "stdin", FakeStdin()),
            patch.object(safety.sys, "stdout", io.StringIO()),
            patch.object(safety.sys, "stderr", io.StringIO()),
        ]
        for p in patches: p.start()
        try:
            self.assertEqual(safety.main(["--disk", "/dev/nvme0n1", "--approve"]), 1)
        finally:
            for p in reversed(patches): p.stop()


if __name__ == "__main__":
    unittest.main()
