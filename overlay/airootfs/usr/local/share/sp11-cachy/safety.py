#!/usr/bin/env python3
"""Read-only Surface dual-boot checks, plus interactive consent gate.

This program NEVER changes a partition table, filesystem or EFI entry.
The user must still select MANUAL partitioning in archinstall.
"""
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


ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
MSR_GUID = "e3c9e316-0b5c-4db8-817d-f92df00215ae"
WINDOWS_GUID = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
RECOVERY_GUID = "de94bba4-06d1-4d40-a16a-bfd50179d6ac"
MIN_FREE_GIB = 140


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
    return f"DUALBOOT {disk['path']} {code}"


def check_dualboot_layout(disk: dict, table: dict) -> float:
    """Require the observed Windows layout and a large gap before recovery.

    Fails closed for layouts that differ from this user's verified Surface.
    ``sfdisk --json`` provides GPT partition types and sector offsets even
    though ``lsblk`` does not report unallocated space.
    """
    pt = table.get("partitiontable", {})
    if pt.get("device") != disk["path"] or pt.get("label") != "gpt":
        raise UnsafeTarget("Expected GPT partition table on the identified internal NVMe")
    sectorsize = pt.get("sectorsize")
    if not isinstance(sectorsize, int) or sectorsize < 512 or sectorsize > 4096:
        raise UnsafeTarget("Unrecognized GPT sector size")
    parts = pt.get("partitions", [])
    if len(parts) != 4:
        raise UnsafeTarget("Expected exactly four untouched Windows partitions; inspect manually")
    expected = (ESP_GUID, MSR_GUID, WINDOWS_GUID, RECOVERY_GUID)
    for number, guid in enumerate(expected, 1):
        part = parts[number - 1]
        if (part.get("node") != f"{disk['path']}p{number}" or
                str(part.get("type", "")).lower() != guid):
            raise UnsafeTarget(f"Windows partition {number} identity or type changed")
        if not isinstance(part.get("start"), int) or not isinstance(part.get("size"), int):
            raise UnsafeTarget("Missing GPT sector information")
    if not (240 * 1024**2 <= parts[0]["size"] * sectorsize <= 1024**3):
        raise UnsafeTarget("EFI partition size differs from inspected Windows layout")
    if not (12 * 1024**2 <= parts[1]["size"] * sectorsize <= 32 * 1024**2):
        raise UnsafeTarget("Microsoft reserved partition size changed")
    if parts[2]["size"] * sectorsize < 250 * 1024**3:
        raise UnsafeTarget("Windows data partition is unexpectedly small")
    if not (1024**3 <= parts[3]["size"] * sectorsize <= 4 * 1024**3):
        raise UnsafeTarget("Windows recovery partition size changed")
    observed = {p.get("path"): p for p in disk.get("children") or []}
    for number, fstype in ((1, "vfat"), (3, "ntfs"), (4, "ntfs")):
        info = observed.get(f"{disk['path']}p{number}", {})
        if str(info.get("fstype", "")).lower() != fstype:
            raise UnsafeTarget(f"Partition {number} filesystem is not {fstype}; stop")
    windows_end = parts[2]["start"] + parts[2]["size"]
    recovery_begin = parts[3]["start"]
    if recovery_begin <= windows_end:
        raise UnsafeTarget("No gap between Windows C: and its recovery partition")
    gap_gib = (recovery_begin - windows_end) * sectorsize / 1024**3
    if gap_gib < MIN_FREE_GIB:
        raise UnsafeTarget(f"Only {gap_gib:.1f} GiB unallocated; need at least {MIN_FREE_GIB}")
    return gap_gib


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
         "NAME,PATH,TYPE,MODEL,SERIAL,SIZE,RM,RO,TRAN,MOUNTPOINTS,FSTYPE"], text=True
    )
    return json.loads(output)["blockdevices"]


def live_table(disk: str) -> dict:
    return json.loads(subprocess.check_output(["sfdisk", "--json", disk], text=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", required=True, help="The complete internal NVMe device e.g. /dev/nvme0n1")
    parser.add_argument("--approve", action="store_true", help="Require typed dual-boot consent")
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
        gap = check_dualboot_layout(disk, live_table(target))
        print(f"Surface identity: {model.strip() or compatible.strip()}")
        print(f"Target: {disk['path']}  Model: {disk.get('model') or 'unknown'}")
        print(f"Serial: {disk['serial']}  Capacity: {disk['size'] / (1024**3):.1f} GiB")
        print(f"Verified Windows EFI/MSR/C:/Recovery layout and {gap:.1f} GiB free gap.")
        print("ONLY create a Linux ext4 root partition in the unallocated gap.")
        print("Mount existing Windows EFI at /boot WITHOUT formatting it.")
        print("IMPORTANT: This gate CANNOT lock archinstall to a safe partition layout.")
        print("Selecting automatic disk layout, formatting EFI, or touching Windows WILL destroy data.")
        if not args.approve:
            print("Read-only preflight PASS. No install or disk change was performed.")
            return 0
        if not sys.stdin.isatty():
            raise UnsafeTarget("Destructive-install approval requires an interactive terminal")
        expected = approval_phrase(disk)
        print("Backups, Windows recovery media, and disk review are required first.")
        print(f"To launch the INTERACTIVE MANUAL-PARTITION installer, type: {expected}")
        if input("Approval: ").strip() != expected:
            raise UnsafeTarget("Approval text did not match; installer will NOT launch")
        print("Approval accepted. Continue to review partitions in archinstall separately.")
        return 0
    except (UnsafeTarget, OSError, KeyError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
