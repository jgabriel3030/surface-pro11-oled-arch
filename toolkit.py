#!/usr/bin/env python3
"""Pinned upstream ISO overlay builder; never partitions or erases disks."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
LOCK = json.loads((ROOT / "lock.json").read_text())
DIGEST_IMAGE = re.compile(r"^[a-zA-Z0-9._/-]+@sha256:[a-fA-F0-9]{64}$")
KERNEL_PARAMS = "clk_ignore_unused pd_ignore_unused arm64.nopauth systemd.mask=tpm2.target"
LIVE_HARDWARE_PACKAGES = ("bluez", "bluez-utils", "evtest")


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def filehash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_source(source: Path) -> tuple[Path, int]:
    source = source.resolve(strict=True)
    actual = command("git", "rev-parse", "HEAD", cwd=source)
    if actual != LOCK["upstream_commit"]:
        raise ValueError(f"Expected upstream {LOCK['upstream_commit']}, got {actual}")
    if command("git", "status", "--porcelain", "--untracked-files=all", cwd=source):
        raise ValueError("Upstream checkout is dirty; use a clean pinned checkout")
    for path in ("configs/releng/profiledef.sh", "configs/releng/airootfs/root/sp11.json",
                 "configs/releng/pacman.conf", "scripts/build-iso.sh"):
        if not (source / path).is_file():
            raise ValueError(f"Upstream source is missing {path}")
    return source, int(command("git", "show", "-s", "--format=%ct", "HEAD", cwd=source))


def add_permissions(profile: Path) -> None:
    data = profile.read_text()
    begin = data.find("file_permissions=(")
    end = data.find("\n)", begin)
    if begin < 0 or end < 0:
        raise ValueError("Unexpected upstream profile permissions syntax")
    new = (
        '\n  ["/usr/local/bin/sp11-cachy-preflight"]="0:0:755"'
        '\n  ["/usr/local/bin/sp11-cachy-install"]="0:0:755"'
        '\n  ["/usr/local/bin/sp11-cachy-hwcheck"]="0:0:755"'
        '\n  ["/usr/local/share/sp11-cachy/safety.py"]="0:0:644"'
        '\n  ["/usr/local/share/sp11-cachy/postinstall.sh"]="0:0:755"'
    )
    profile.write_text(data[:end] + new + data[end:])


def add_live_hardware_packages(packages_file: Path) -> None:
    """Add diagnostic utilities without changing the upstream kernel/profile."""
    data = packages_file.read_text()
    current = {line.split("#", 1)[0].strip() for line in data.splitlines()}
    missing = [name for name in LIVE_HARDWARE_PACKAGES if name not in current]
    if missing:
        packages_file.write_text(data.rstrip("\n") +
                                 "\n\n# Surface OLED hardware verification\n" +
                                 "\n".join(missing) + "\n")


def embedded_command(script: Path, destination: str) -> str:
    encoded = base64.b64encode(script.read_bytes()).decode("ascii")
    return (f"install -Dm755 /dev/null {destination} && "
            f"printf '%s' '{encoded}' | base64 -d > {destination} && "
            f"chmod 755 {destination}")


def modify_preset(path: Path, postinstall: Path, hwcheck: Path) -> None:
    preset = json.loads(path.read_text())
    if preset.get("kernels") != ["linux-sp11"]:
        raise ValueError("Surface kernel changed upstream; stop and review")
    boot = preset.get("bootloader_config", {})
    if boot.get("bootloader") != "Systemd-boot" or boot.get("uki") is not False:
        raise ValueError("Surface boot setup changed upstream; stop and review")
    original = preset.get("custom_commands", [])
    if len(original) != 2 or original[1] != "linux-sp11-mkuki" or KERNEL_PARAMS not in original[0]:
        raise ValueError("Surface custom commands changed upstream; stop and review")
    # Archinstall runs custom commands inside the new system. Embed an auditable,
    # local post-boot script without installing GUI packages during archinstall.
    preset["custom_commands"].append(
        embedded_command(postinstall, "/usr/local/sbin/sp11-cachy-postinstall")
    )
    preset["custom_commands"].append(
        embedded_command(hwcheck, "/usr/local/bin/sp11-cachy-hwcheck")
    )
    path.write_text(json.dumps(preset, indent=2) + "\n")


def tracked_files(staged: Path) -> dict[str, str]:
    """Hash the entire staged tree, not merely the obvious boot-critical files."""
    files = {}
    for entry in sorted(staged.rglob("*")):
        relative = entry.relative_to(staged)
        if relative.parts[0] == "out" or relative.name in ("toolkit-manifest.json", "build-receipt.json"):
            continue
        if entry.is_symlink():
            # The upstream image intentionally has service-enable links and
            # absolute links interpreted inside the live ISO root filesystem.
            files[relative.as_posix()] = "symlink:" + os.readlink(entry)
        elif entry.is_file():
            files[relative.as_posix()] = filehash(entry)
    return files


def prepare(source: Path, output: Path) -> Path:
    source, epoch = check_source(source)
    output = output.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("Staging directory and upstream source must be separate")
    if output.exists():
        raise FileExistsError(f"Will not overwrite existing staging path: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, output, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "out", "__pycache__"))
    releng = output / "configs/releng"
    shutil.copytree(ROOT / "overlay/airootfs", releng / "airootfs", dirs_exist_ok=True)
    share = releng / "airootfs/usr/local/share/sp11-cachy"
    shutil.copy2(ROOT / "payload/postinstall.sh", share / "postinstall.sh")
    add_permissions(releng / "profiledef.sh")
    add_live_hardware_packages(releng / "packages.aarch64")
    modify_preset(releng / "airootfs/root/sp11.json", share / "postinstall.sh",
                  releng / "airootfs/usr/local/bin/sp11-cachy-hwcheck")
    manifest = {
        "schema": 1,
        "upstream_commit": LOCK["upstream_commit"],
        "source_date_epoch": epoch,
        "reproducibility_note": LOCK["reproducibility_note"],
        "files": tracked_files(output),
    }
    (output / "toolkit-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return output


def verify(staged: Path) -> dict:
    manifest = json.loads((staged / "toolkit-manifest.json").read_text())
    if manifest.get("upstream_commit") != LOCK["upstream_commit"]:
        raise ValueError("Manifest upstream commit differs from lock")
    actual = tracked_files(staged)
    if set(actual) != set(manifest["files"]):
        raise ValueError("Files were added to or removed from the staged source")
    for path, expected in manifest["files"].items():
        if actual[path] != expected:
            raise ValueError(f"Stage modification detected: {path}")
    preset = json.loads((staged / "configs/releng/airootfs/root/sp11.json").read_text())
    commands = preset.get("custom_commands", [])
    if len(commands) != 4 or commands[1] != "linux-sp11-mkuki" or KERNEL_PARAMS not in commands[0]:
        raise ValueError("Upstream kernel setup commands were altered")
    script = (staged / "configs/releng/airootfs/usr/local/share/sp11-cachy/postinstall.sh").read_bytes()
    if base64.b64encode(script).decode("ascii") not in commands[2]:
        raise ValueError("Installed post-boot script does not match the ISO payload")
    hwcheck = (staged / "configs/releng/airootfs/usr/local/bin/sp11-cachy-hwcheck").read_bytes()
    if base64.b64encode(hwcheck).decode("ascii") not in commands[3]:
        raise ValueError("Installed hardware audit does not match the ISO payload")
    packages = set((staged / "configs/releng/packages.aarch64").read_text().splitlines())
    if not set(LIVE_HARDWARE_PACKAGES).issubset(packages):
        raise ValueError("Live hardware verification packages are missing")
    if preset.get("bootloader_config", {}).get("uki") is not False:
        raise ValueError("Unsupported bootloader preset")
    return manifest


def build(staged: Path, image: str, execute: bool = False) -> list[str]:
    if not DIGEST_IMAGE.fullmatch(image):
        raise ValueError("Builder image MUST use an immutable @sha256:64-hex digest")
    manifest = verify(staged)
    staged = staged.resolve()
    args = ["docker", "run", "--rm", "--privileged", "--platform", "linux/arm64",
            "--mount", f"type=bind,source={staged},target=/build", "--workdir", "/build",
            "--env", f"SOURCE_DATE_EPOCH={manifest['source_date_epoch']}",
            image, "/build/scripts/build-iso.sh"]
    if execute:
        if sys.platform != "linux" or os.uname().machine != "aarch64":
            raise OSError("Build requires native ARM64 Linux and privileged Docker")
        subprocess.run(args, check=True)
        images = list((staged / "out").glob("*.iso"))
        if len(images) != 1:
            raise ValueError(f"Expected one built ISO, found {len(images)}")
        receipt = {"source_commit": LOCK["upstream_commit"], "builder_image": image,
                   "source_date_epoch": manifest["source_date_epoch"],
                   "iso_filename": images[0].name, "iso_sha256": filehash(images[0]),
                   "live_packages_sha256": filehash(staged / "configs/releng/packages.aarch64"),
                   "note": "Package repositories are rolling; byte-identical builds not guaranteed"}
        (staged / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare", help="Stage pinned Surface ISO source plus KDE installer tools")
    prep.add_argument("--source", type=Path, help="Optional clean upstream checkout at locked commit")
    prep.add_argument("--output", type=Path, required=True)
    ver = sub.add_parser("verify", help="Check staged hashes and Surface boot invariants")
    ver.add_argument("--staged", type=Path, required=True)
    bld = sub.add_parser("build", help="Preview ISO build; --execute runs privileged Docker")
    bld.add_argument("--staged", type=Path, required=True)
    bld.add_argument("--container-image", required=True)
    bld.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if args.source is not None:
                out = prepare(args.source, args.output)
            else:
                with tempfile.TemporaryDirectory(prefix="sp11-locked-source-") as tmp:
                    repo = Path(tmp) / "upstream"
                    subprocess.run(["git", "clone", "--no-checkout", LOCK["upstream_url"], str(repo)], check=True)
                    subprocess.run(["git", "-C", str(repo), "checkout", "--detach", LOCK["upstream_commit"]], check=True)
                    out = prepare(repo, args.output)
            print(f"Prepared: {out}")
        elif args.action == "verify":
            print(f"Verified: {verify(args.staged)['upstream_commit']}")
        else:
            cmd = build(args.staged, args.container_image, args.execute)
            print("Executed:" if args.execute else "PREVIEW — no build or disk actions:")
            print(shlex.join(cmd))
    except (OSError, ValueError, subprocess.CalledProcessError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
