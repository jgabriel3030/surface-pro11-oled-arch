# Surface Pro 11 OLED AArch64 — Cachy-style Arch toolkit

**Experimental, dual-boot-only v3 source (not yet boot-tested).** The October 2026 GitHub Actions build
successfully produced a bootable AArch64 ISO. A Surface Pro 11 OLED/X Elite
booted that image into the live console, and the owner verified Wi-Fi,
touchscreen events, battery charging, and native 2880×1920 display output.
The **new v3 dual-boot ISO requires a fresh ARM64 build and independent boot test**.
Bluetooth controller discovery and nearby device scans were also verified on the
live image after local MAC setup. Adreno acceleration, audio, Bluetooth pairing
and sleep have NOT passed independent testing.

This toolkit creates a customized edition of
[dwhinham/archiso-aarch64-sp11](https://github.com/dwhinham/archiso-aarch64-sp11)
for a **Surface Pro 11 Wi-Fi-only OLED with Snapdragon X Elite**, using Arch Linux Ports
AArch64. It installs a **KDE Plasma desktop and selected CachyOS-like defaults**
*after the first boot*. It is not official CachyOS: no official CachyOS AArch64
release is used or claimed.

## What is preserved

- The upstream `linux-sp11` kernel, device trees, firmware packages,
  repository keys, boot flags, and systemd-boot.
- The original kernel command-line custom command stays unchanged. The second
  upstream command generates UKIs for all Surface variants, so **v3 replaces it
  with one Wi-Fi OLED-only UKI builder** to respect the existing 260 MB Windows
  EFI partition. It measures capacity before writing and preserves Windows
  Boot Manager. This is a new, untested installation modification.
- The upstream live console installer stays intact. KDE is deliberately *not*
  added to the live image or installed during `archinstall`: the upstream
  maintainer warns that doing so can cause package conflicts.
- Proprietary firmware is **never redistributed**. After installing, run
  `sp11-grab-fw` yourself on the installed system.

The overlay contributes: (1) read-only checks of the existing four Windows GPT
partitions and a 140+ GiB unallocated gap, followed by typed dual-boot approval;
(2) an OLED-only UKI generation script and kernel-update hook; (3) a post-boot
setup script and a **read-only hardware check** embedded into the installed
system by added `archinstall` custom commands; (4) BlueZ and `evtest` on the
live USB; and (5) tests and build provenance. See [FIELD_TESTS.md](FIELD_TESTS.md)
for exactly what was observed on the real Surface.

**Start with the complete, device-specific [DUAL_BOOT_GUIDE.md](DUAL_BOOT_GUIDE.md).**
The preflight script does not control archinstall's menu: automatic partitioning
or incorrect manual formatting can still destroy Windows.

## Fast path: build the ISO automatically on GitHub

1. Put these toolkit source files in a **new GitHub repository**.
2. Open **Actions → Build Surface Pro 11 ISO → Run workflow**.
3. The ARM64 runner checks the source lock, runs the unit tests, fetches the
   locked upstream, resolves the current builder image to an immutable digest,
   builds using the upstream `mkarchiso`, verifies and uploads the ISO plus its
   provenance receipt. No installation or partitioning happens in CI.
4. Download the workflow artifact named
   `surface-pro11-oled-aarch64-cachy-style-v3-dualboot`, verify its SHA-256
   against `build-receipt.json`, and boot-test it before any disk changes.

Because the upstream repositories are rolling, an identical repo revision and
container **do not guarantee an identical package set or byte-identical ISO**.
The receipt records the exact ISO hash and build image so you can audit builds.
For strict reproducibility, a future iteration must snapshot package
repositories and dependency versions as well.

## Local AArch64 build

Requirements: native ARM64 Linux, Python 3.10+, `git`, Docker with privileged
container support, internet access, and adequate free disk space.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B toolkit.py prepare --output work/sp11-staged
python3 -B toolkit.py verify --staged work/sp11-staged

# Look up the actual image digest from your ARM64 host:
docker pull ironrobin/archports-aarch64:latest
docker image inspect --format '{{index .RepoDigests 0}}' ironrobin/archports-aarch64:latest

# Use the EXACT image@sha256:... printed above, not the mutable :latest tag.
# This command previews the build and makes no changes:
python3 -B toolkit.py build --staged work/sp11-staged \
  --container-image 'ironrobin/archports-aarch64@sha256:YOUR_64_HEX_DIGEST'

# Then add --execute to really build in privileged Docker:
python3 -B toolkit.py build --staged work/sp11-staged \
  --container-image 'ironrobin/archports-aarch64@sha256:YOUR_64_HEX_DIGEST' --execute
```

Your ISO and build receipt will appear under `work/sp11-staged/out/` and
`work/sp11-staged/build-receipt.json`. You may stage a local upstream checkout
instead of cloning with `--source /path/to/archiso-aarch64-sp11`; it must be at
the exact commit in `lock.json` and completely clean. The builder never silently
overwrites an existing staging directory.

## Install on the Surface — preserve Windows

**The old erase-Windows instructions and commands are obsolete.** Use
[DUAL_BOOT_GUIDE.md](DUAL_BOOT_GUIDE.md) for the complete sequence, including
backups, preflight, careful manual partitioning, boot verification and recovery.

The expected disk is `/dev/nvme0n1`, with the existing 260 MB FAT32 EFI p1,
16 MB Windows MSR p2, ~324.67 GB NTFS Windows C: p3, **150 GB unallocated**,
and 2 GB Windows Recovery p4. Preserve p1–p4. Create only a new Linux ext4
root partition in the unallocated gap; reuse EFI p1 at `/boot` **without
formatting**. The custom UKI builder writes only the Wi-Fi OLED image and
refuses to fill the EFI partition below a 64 MiB free reserve. Never let
archinstall generate an automatic partition layout.

First run the read-only command:

```sh
sp11-cachy-preflight --disk /dev/nvme0n1
```

After backup, recovery USB, preflight success, and review of the full guide:

```sh
sp11-cachy-install --dual-boot --disk /dev/nvme0n1
```

This requests `DUALBOOT /dev/nvme0n1 <device-specific-code>` and then launches
interactive archinstall. **It cannot prevent a mistaken archinstall selection.**
Stop and share a photo of the final partition summary before confirming writes.

Once installation and Windows boot verification have succeeded, boot the new
**command-line** Arch system and get online with `nmtui`.
   First run `sp11-cachy-hwcheck` to see what's missing. Extract/install the
   GPU and other proprietary firmware only **after booting the installed
   system**, not from the live USB:

```sh
sudo sp11-cachy-postinstall --firmware
sudo reboot
```

This command requires a separate interactive confirmation before delegating
to the upstream `sp11-grab-fw` utility. Reboot and rerun `sp11-cachy-hwcheck`;
verify that the Adreno GPU no longer reports firmware load failures before
proceeding. **No proprietary firmware files are built into or published with
the ISO.** Some firmware, especially aDSP, has caused live-USB instability.

Install Plasma and Cachy-style defaults only once the firmware checks look
   appropriate for the installed system:

```sh
sudo sp11-cachy-postinstall --dry-run
sudo sp11-cachy-postinstall --apply
sudo reboot
```

The first command is read-only. The second confirms its own pacman transaction
and installs Plasma, SDDM, Bluetooth desktop components, PipeWire, and ZRAM.
If `iptsd` is available in the configured repositories, the script also
installs it; touchscreen calibration and pen gestures still need device-level
verification. `archinstall` injects the setup and audit commands into the
target without running them prematurely.
If the command is missing, **stop and diagnose the archinstall logs**.

**Bluetooth MAC addresses:** Edit `/etc/sp11-mac.conf` in the installed OS
using the real addresses obtained from your own Windows installation, following
the pinned upstream Surface guide. Do not commit private MAC addresses to this
public GitHub repository, invent generic MACs, or assume that a healthy
`bluetooth.service` means the Bluetooth adapter has registered. Surface-specific
MAC fixup and real device pairing must be verified separately.

**Audio caution:** Qualcomm audio DSP firmware was absent from the live image.
The Surface project limits speaker volume because full hardware speaker
protection is not yet implemented. Keep speakers muted until the correct
Surface ALSA UCM profiles and safe volume limits have been confirmed.

## KDE and performance choices

| Component | Toolkit choice |
| --- | --- |
| Desktop | KDE Plasma / Breeze Dark, Wayland-capable session |
| Login manager | SDDM enabled |
| Networking | NetworkManager, BlueZ and KDE's Bluedevil controls |
| Live diagnostics | `sp11-cachy-hwcheck`, `evtest`, `bluetoothctl` |
| Audio stack | PipeWire/WirePlumber and upstream Surface ALSA UCM profiles; firmware separately |
| Memory | `zram-generator`, Zstandard, virtual swap at half RAM |
| Swapping | `vm.swappiness=100`, cache pressure 50 |
| Display/GPU | Keep upstream Qualcomm/Adreno stack and `sp11-grab-fw` |
| Kernel and scheduler | Keep `linux-sp11` kernel; no unsupported CachyOS kernel patches |
| Power | Plasma power management, no forced high-performance governor/TLP |
| Surface battery | Block duplicate `qcom_battmgr` driver per upstream Surface SAM guidance |

Expected from pinned upstream: NVMe, OLED brightness, GPU (after firmware),
Wi-Fi, Bluetooth (with MAC fixup), attached keyboard, touch/pen, speakers/mic
(speaker-protection caveat), and suspend are reported working to varying
degrees. **Our independent live-USB test found GPU and audio firmware missing,
and Bluetooth firmware booting but no adapter registered in BlueZ.** USB-C is
partial; USB4 dock/Thunderbolt and cameras remain unsupported in the pinned
release. Do not depend on a USB4 dock for setup.

## Rollback and recovery

- `sudo sp11-cachy-postinstall --rollback` restores any original versions of
  its **four config files**, and the prior enabled states of SDDM,
  NetworkManager, and Bluetooth. It does not
  uninstall KDE or downgrade packages, firmware or kernel. Reboot afterward.
- A console remains available if KDE fails: use a virtual terminal or SSH,
  and inspect `journalctl -b -u sddm` and `pacman -Q linux-sp11`.
- For Linux boot recovery, boot the original known-good Surface ISO and consult
  the maintainer's bootloader/UKI guidance. The toolkit has not implemented an
  unattended EFI repair tool.
- If Linux fails to boot, use the Surface UEFI boot menu to select the
  preserved Windows Boot Manager, and diagnose Linux separately. Do not
  format any Windows partition as a repair attempt. Keep official Surface
  recovery USB and external Windows backups as disaster recovery.

## Verification performed and remaining work

- Unit tests cover source pin and boot preset guards, profile preservation,
  fail-closed dual-boot GPT and free-space policy, human confirmation,
  OLED-only UKI embedding, manifest integrity, strict build-container digest
  and default build preview behavior.
- Integration staging was performed against the actual locked upstream source;
  `toolkit.py verify` passed. The copier deliberately preserves upstream's
  absolute/dangling systemd symlinks.
- The first ISO **was built on the native ARM64 GitHub runner and USB-booted
  successfully on the OLED Surface**. See `FIELD_TESTS.md` for the observed
  hardware results and the precise missing Qualcomm firmware paths.
- The v2 update added BlueZ and `evtest` to the live environment and
  read-only hardware reporting without altering the Surface kernel or consent
  flow. The existing live image's manual `pacman` install of BlueZ triggered an
  `mkinitcpio` hook error because `/boot/vmlinuz-linux-sp11` was not readable
  in live mode; the package still installed, but this is **not** a reason to
  run boot-image repair commands on the USB. Bundling BlueZ at ISO build time
  avoids that manual install during testing.
- **Still not done:** build and boot-test v3, verify the new single-UKI writer
  against the actual installed `linux-sp11` package and 260 MB ESP, independently verify the real
  post-install Arch Plasma transaction and firmware extraction, validate
  `archinstall` custom-command execution, or test hardware 3D acceleration,
  Bluetooth pairing, audio safety, 120 Hz, cameras, or suspend/resume.
  Keep Windows/recovery backups until these have been evaluated.

## Credits

Surface enablement is the work of [Dale Whinham](https://github.com/dwhinham),
[archiso-aarch64](https://codeberg.org/ironrobin/archiso-aarch64), Arch Linux
Ports, kernel and device contributors. This toolkit is an optional, independent
overlay, **not affiliated with or endorsed by upstream**. Review all upstream
license and attribution obligations before redistributing derived images.
