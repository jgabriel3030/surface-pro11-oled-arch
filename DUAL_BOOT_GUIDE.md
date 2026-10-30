# Dual boot — Surface Pro 11 OLED, Snapdragon X Elite, **Wi-Fi only**

**State: preparation guide for experimental v3 ISO. Not a verified production
installer.** This guide is customized for the owner's confirmed Windows disk
layout on October 30, 2026. It is designed to **keep Windows 11 ARM and its
recovery partition**, not replace them. Do not proceed to an actual installation
until the v3 GitHub Actions build is complete and the new ISO boots the Surface.

The correct device tree is `qcom/x1e80100-microsoft-denali-oled.dtb`, **not**
the 5G OLED or LCD variant. The kernel is the pinned upstream `linux-sp11`.

## 1. Before installation (in Windows)

1. **Back up personal files to a separate physical disk or verified cloud
   backup**. Create and test the official Microsoft Surface recovery USB as a
   Windows disaster-recovery fallback. Know your Microsoft account password.
2. The owner previously verified **C: is fully decrypted**. Reconfirm in an
   Administrator PowerShell session with `manage-bde -status C:`. It must say
   `Fully Decrypted`. If not, stop and wait. Do not assume "Protection Off"
   means a drive is decrypted; earlier it was still encrypted.
3. Open Disk Management and confirm the following **Disk 0** arrangement.
   Windows labels GiB as "GB" here. **All numbered partitions stay intact:**

   | Order | Linux device | Windows label | Size | Action |
   | --- | --- | --- | --- | --- |
   | 1 | `/dev/nvme0n1p1` | EFI System Partition, FAT32 | 260 MB | **KEEP; reuse at `/boot`, never format** |
   | 2 | `/dev/nvme0n1p2` | Microsoft reserved | 16 MB | **KEEP untouched** |
   | 3 | `/dev/nvme0n1p3` | Windows C:, NTFS | 324.67 GB | **KEEP untouched** |
   | gap | not numbered yet | Unallocated | 150.00 GB | **ONLY place to create Linux** |
   | 4 | `/dev/nvme0n1p4` | Windows recovery, NTFS | 2.00 GB | **KEEP untouched** |

4. The 150 GB was already freed by shrinking C: from Windows. **Leave it
   UNALLOCATED. Do not make a new NTFS partition, format it, or delete recovery.**
   An earlier live read-only test showed about **227 MiB available on the
   existing 260 MB EFI partition**, before Linux installation. This is tight;
   the new installer handles only one Wi-Fi OLED UKI and refuses a build if
   space is inadequate. Nothing guarantees that the final UKI fits.

## 2. Build/flash and boot the experimental v3 USB

1. Open [GitHub Actions for the owner's Surface repo](https://github.com/jgabriel3030/surface-pro11-oled-arch/actions/workflows/build-surface-iso.yml)
   and run **Build Surface Pro 11 ISO** after the new dual-boot revision is
   committed. Only download the artifact named
   `surface-pro11-oled-aarch64-cachy-style-v3-dualboot`; an older v2 image
   does **not** include this dual-boot-specific installer guard.
2. Download the `.iso`, `build-receipt.json`, and manifest. Compare the ISO
   SHA-256 against `iso_sha256` in the receipt before writing the USB.
3. Flash the ISO with **Balena Etcher** to a separate USB drive. This erases
   the **USB drive only**. Do not select the Surface internal SSD.
4. On the Surface, disable Secure Boot as required by the pinned upstream
   install guide. Shut down, hold **Volume Up + Power** to open Surface UEFI,
   select Boot Configuration and swipe the **USB Storage** entry to boot.
   Linux can take a few minutes to display the console. If it fails, stop;
   do not alter internal Windows partitions.
5. Verify working keyboard, Wi-Fi, display and touchscreen on the new v3 USB.
   On a live USB, do not apply audio DSP firmware.

## 3. Read-only disk verification (in live Linux)

First identify the disk and its partitions. These commands do not write data:

```sh
lsblk -o NAME,PATH,SIZE,FSTYPE,TYPE,MODEL,SERIAL,MOUNTPOINTS
sfdisk --json /dev/nvme0n1
sp11-cachy-preflight --disk /dev/nvme0n1
```

The preflight requires native ARM64 Surface hardware, a genuine internal NVMe
with a serial number, exactly four Windows partitions of expected types and
sizes, no NVMe partitions mounted, and at least 140 GiB of unallocated space
**between Windows C: and the recovery partition**. It performs **no writes**.
If anything differs, **STOP** and share photos/output before installing.

## 4. Launch the *manual* Linux installation

**Only when you have checked the backup and recovery USB** and the preflight
passes, run:

```sh
sp11-cachy-install --dual-boot --disk /dev/nvme0n1
```

The wrapper asks you to type a device-specific string beginning with
`DUALBOOT /dev/nvme0n1`. This approval starts interactive `archinstall` with
the pinned `/root/sp11.json` preset. **It does not constrain archinstall's
disk actions.** A wrong choice in archinstall could still erase Windows.

### Choose disk configuration very carefully

- Select **manual partitioning** on `/dev/nvme0n1`, *never* an automatic,
  best-effort, wipe-disk or erase-disk layout.
- **Create exactly one new ext4 Linux partition** using the existing 150 GB
  unallocated gap; set mountpoint `/`. The Linux partition will probably
  receive number `p5`, because the four Windows partition numbers are taken.
  This is normal: physical order and numeric order need not match.
- **Reuse** existing `/dev/nvme0n1p1` as the EFI System Partition mounted
  at `/boot`. **Disable formatting of p1**. If archinstall offers no way to
  mount p1 without formatting, **stop**, do not improvise.
- Preserve `/dev/nvme0n1p2` (MSR), `/dev/nvme0n1p3` (NTFS C:), and
  `/dev/nvme0n1p4` (Windows Recovery) with **no mountpoint and NO format**.
- For the first test installation, keep the root partition unencrypted and
  skip a separate swap partition. The postinstall setup can configure zram.
- Keep the preset **systemd-boot**, `linux-sp11` kernel, repos, custom
  commands, and **UKI option disabled** exactly as supplied. Set a username,
  passwords, timezone, locale. Keep NetworkManager; **do not choose a desktop
  profile** in archinstall (install KDE later once firmware is ready).

**Before you press the final Install/Confirm button:** inspect the installer
summary. It must say only the **new Linux ext4 partition** will be formatted.
If it mentions formatting the existing EFI partition, wiping `/dev/nvme0n1`,
Windows C:, MSR, or recovery, **cancel**. Take a photo of the summary and ask
for a second review. This is a critical pause point.

### Tiny Windows EFI partition caveat

The original upstream installer builds boot images for every Surface model.
That is not safe to assume on this device's existing 260 MB EFI partition.
The v3 preset instead builds only `EFI/Linux/linux-sp11-oled.efi`, and checks
remaining FAT32 space with a 64 MiB Windows reserve before placing it. A
package hook aims to preserve this behavior on upgrades. **Both changes still
require an actual installed-system test.** If the build reports insufficient
EFI space or missing kernel paths, **stop**: do not delete Windows EFI files,
recovery, or arbitrarily resize/move partitions. We will evaluate a separate
Linux boot partition approach before proceeding further.

## 5. Verify BOTH operating systems before installing KDE

1. After installation, reboot with the USB removed. Use the Surface UEFI
   menu to verify that **Windows Boot Manager still boots Windows normally**.
   Also test the new Arch/Linux boot option. A missing boot-menu entry may
   require bootloader troubleshooting; it is not permission to erase EFI.
2. In installed Linux, connect Wi-Fi using `nmtui` if necessary. Confirm
   the installed system is native AArch64 and run:

   ```sh
   uname -m
   lsblk -f
   sp11-cachy-hwcheck
   ```

3. Set **your real factory Wi-Fi and Bluetooth MAC addresses** in
   `/etc/sp11-mac.conf` locally following the pinned upstream Surface guide.
   The live USB fix does **not** automatically persist into the installed
   system. **Do not publish device addresses to GitHub.** Bluetooth controller
   discovery and nearby-device scanning passed on the live USB, but pairing
   remains untested.
4. Run the proprietary firmware installer **only from the installed Linux
   system**, with its separate confirmation, then reboot:

   ```sh
   sudo sp11-cachy-postinstall --firmware
   sudo reboot
   sp11-cachy-hwcheck
   ```

5. If the hardware check and GPU firmware status look healthy, preview and
   install Plasma and CachyOS-like defaults:

   ```sh
   sudo sp11-cachy-postinstall --dry-run
   sudo sp11-cachy-postinstall --apply
   sudo reboot
   ```

   This is **Arch Linux Ports AArch64 with a KDE/Cachy-inspired configuration**,
   not an official CachyOS ARM release.

## 6. Cautions and rollback

- **Audio:** start with speakers muted; the Surface audio path still has
  limited hardware speaker protection. Do not test high volume.
- **Hardware:** camera, USB4 docks, GPU firmware, audio, suspend/resume,
  and pen calibration may need additional work and validation.
- **Secure Boot:** upstream currently requires it disabled for this test ISO.
  Changing UEFI or TPM settings can trigger recovery prompts on protected
  Windows. Fully decrypting C: first avoids that specific BitLocker lockout;
  do not re-enable device encryption until both boot paths are stable and a
  recovery key is safely backed up.
- **Linux configuration rollback**:
  `sudo sp11-cachy-postinstall --rollback` restores certain configs/service
  states; it does **not** uninstall Linux, undo partition changes or rebuild
  Windows partitions.
- **Windows recovery:** the goal is that the old Windows boot entry and
  recovery partition remain intact. Keep offline backups and the recovery USB
  even after Windows boots. Never delete the original ESP or the Windows
  recovery partition to make Linux fit.

## References

- [Pinned upstream Surface Arch installer](https://github.com/dwhinham/archiso-aarch64-sp11)
- [Microsoft Surface UEFI settings](https://learn.microsoft.com/en-us/surface/manage-surface-uefi-settings)
- [ArchWiki: Dual boot with Windows](https://wiki.archlinux.org/title/Dual_boot_with_Windows)
- [ArchWiki: systemd-boot / XBOOTLDR](https://wiki.archlinux.org/title/Systemd-boot)
- [ArchWiki: Unified kernel images](https://wiki.archlinux.org/title/Unified_kernel_image)

These instructions are explicitly for the **observed Wi-Fi OLED model and
disk layout**; re-check everything if Windows partitioning changes.
