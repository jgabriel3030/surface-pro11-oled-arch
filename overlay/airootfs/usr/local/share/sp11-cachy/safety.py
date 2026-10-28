#!/usr/bin/env python3
"""Read-only Surface hardware and NVMe checks, plus interactive consent gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys


class UnsafeTarget(ValueError):
    pass


def children(device: dict):
    yield device
    for child in device.get("children") or []:
        yield from children(child)


def check_disk(blocks: list[dict], requested: str) -> dict:
    """Pure disk policy; tests can inject lsblk responses without real hardware."""
    if not re.fullmatch(r"/dev/nvme\d+n\d+", requested):
        raise UnsafeTarget("Only a complete internal /dev/nvme*n* disk is supported (not a partition)")
    matching = [disk for disk in blocks if disk.get("path") == requested]
    if len(matching) != 1:
        raise UnsafeTarget("The requested disk was not uniquely found in lsblk")
    disk = matching[0]
    if disk.get("type") != "disk" or disk.get("ro") not in (False, 0, "0"):
        raise UnsafeTarget("Device is not a writable whole disk")
    if disk.get("rm") not in (False, 0, "0") or disk.get("tran") == "usb":
        raise UnsafeTarget("Removable or USB storage is not an approved target")
    if disk.get("tran") not in ("nvme", None, ""):
        raise UnsafeTarget("Disk connection type is not NVMe")
    if not str(disk.get("serial") or "").strip():
        raise UnsafeTarget("NVMe serial is unavailable; refuse to approve an unidentified disk")
    if not isinstance(disk.get("size"), int) or disk["size"] < 16 * 1024**3:
        raise UnsafeTarget("Disk capacity is missing or implausibly small")
    for component in children(disk):
        mounts = component.get("mountpoints") or []
        if isinstance(mounts, str):
            mounts = [mounts]
        if any(m for m in mounts) or component.get("mountpoint"):
            raise UnsafeTarget("Disk or a partition is mounted; unmount and re-check before continuing")
    return disk


def approval_phrase(disk: dict) -> str:
    identity = f"{disk['path']}|{disk['serial']}|{disk['size']}"
    code = hashlib.sha256(identity.encode()).hexdigest()[:8].upper()
    return f"ERASE {disk['path']} {code}"


def surface_model_matches(model: str, compatible: str) -> bool:
    combined = model.lower().replace("\x00", " ") + " " + compatible.lower().replace("\x00", " ")
    return bool(re.search(r"surface\s+pro\s+11|microsoft,denali", combined))


def hardware_identity() -> tuple[str, str]:
    names = ("/sys/firmware/devicetree/base/model", "/proc/device-tree/model",
             "/sys/class/dmi/id/product_name")
    compat_names = ("/sys/firmware/devicetree/base/compatible", "/proc/device-tree/compatible")

    def read(path: str) -> str:
        try:
            return Path(path).read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return ""

    return " ".join(read(p) for p in names), " ".join(read(p) for p in compat_names)


def live_blocks() -> list[dict]:
    output = subprocess.check_output(
        ["lsblk", "--json", "--bytes", "--output",
         "NAME,PATH,TYPE,MODEL,SERIAL,SIZE,RM,RO,TRAN,MOUNTPOINTS"], text=True
    )
    return json.loads(output)["blockdevices"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", required=True, help="The complete internal NVMe device e.g. /dev/nvme0n1")
    parser.add_argument("--approve", action="store_true", help="Require typed, device-specific consent")
    args = parser.parse_args(argv)
    try:
        if platform.machine() != "aarch64":
            raise UnsafeTarget("This is not a native AArch64 boot session")
        model, compatible = hardware_identity()
        if not surface_model_matches(model, compatible):
            raise UnsafeTarget("Device tree does not identify a Surface Pro 11/Denali; refusing to proceed")
        target = os.path.realpath(args.disk)
        if target != args.disk:
            raise UnsafeTarget("Use the canonical NVMe path, not a symlink")
        mode = os.stat(target).st_mode
        if not stat.S_ISBLK(mode):
            raise UnsafeTarget("Target is not a real block device")
        disk = check_disk(live_blocks(), target)
        print(f"Surface identity: {model.strip() or compatible.strip()}")
        print(f"Target: {disk['path']}  Model: {disk.get('model') or 'unknown'}")
        print(f"Serial: {disk['serial']}  Capacity: {disk['size'] / (1024**3):.1f} GiB")
        print("Windows and all partitions on the SELECTED drive may be lost in archinstall.")
        print("IMPORTANT: This gate does not lock archinstall to this drive. Inspect its disk screen separately.")
        if not args.approve:
            print("Read-only preflight PASS. No install or disk change was performed.")
            return 0
        if not sys.stdin.isatty():
            raise UnsafeTarget("Destructive-install approval requires an interactive terminal")
        expected = approval_phrase(disk)
        print(f"To launch the INTERACTIVE installer, type exactly: {expected}")
        if input("Approval: ").strip() != expected:
            raise UnsafeTarget("Approval text did not match; installer will NOT launch")
        print("Approval accepted. Continue to review partitions in archinstall separately.")
        return 0
    except (UnsafeTarget, OSError, KeyError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
