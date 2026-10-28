# Surface Pro 11 OLED AArch64 — Cachy-style Arch toolkit

**Experimental prototype. Source staging and automated tests work; an actual
ARM64 ISO build and boot on the Surface have NOT yet been performed.**

This toolkit creates a customized edition of
[dwhinham/archiso-aarch64-sp11](https://github.com/dwhinham/archiso-aarch64-sp11)
for a **Surface Pro 11 OLED with Snapdragon X Elite**, using Arch Linux Ports
AArch64. It installs a **KDE Plasma desktop and selected CachyOS-like defaults**
*after the first boot*. It is not official CachyOS: no official CachyOS AArch64
release is used or claimed.

## What is preserved

- The upstream `linux-sp11` kernel, device trees, firmware packages,
  repository keys, boot flags, systemd-boot and Surface-specific UKI generation.
- The original two `archinstall` custom commands stay unchanged and in order.
- The upstream live console installer stays intact. KDE is deliberately *not*
  added to the live image or installed during `archinstall`: the upstream
  maintainer warns that doing so can cause package conflicts.
- Proprietary firmware is **never redistributed**. After installing, run
  `sp11-grab-fw` yourself on the installed system.

The overlay contributes three things: (1) preflight and typed disk approval,
(2) a small post-boot setup script embedded into the installed system by an
added `archinstall` custom command, and (3) tests and build provenance.

## Fast path: build the ISO automatically on GitHub

1. Put these toolkit source files in a **new GitHub repository**.
2. Open **Actions → Build Surface Pro 11 ISO → Run workflow**.
3. The ARM64 runner checks the source lock, runs the unit tests, fetches the
   locked upstream, resolves the current builder image to an immutable digest,
   builds using the upstream `mkarchiso`, verifies and uploads the ISO plus its
   provenance receipt. No installation or partitioning happens in CI.
4. Download the workflow artifact, verify its SHA-256 against
   `build-receipt.json`, and boot-test it before deciding to erase Windows.

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

## Install on the Surface — two separate consent points

1. **Before even booting Linux:** back up everything on Windows. Save any
   BitLocker/device-encryption recovery key. Prepare and test an official
   Surface Windows recovery USB. Erasing Windows also erases the on-device
   Windows recovery partition. A recovery USB and backups are the real rollback.
2. Follow the upstream boot process precisely: disable Secure Boot in Surface
   UEFI; flash the ISO with Balena Etcher or a raw write (not Ventoy/Rufus);
   hold Volume Up while rebooting, open UEFI Boot Configuration, and **swipe**
   USB Storage to boot. A black screen for 2–3 minutes can be normal.
3. From the live console, inspect `lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,TYPE`.
   Then run `sp11-cachy-preflight --disk /dev/nvme0n1`, substituting the real
   **internal NVMe whole-device** path. If a safety check fails, stop.
4. Run `sp11-cachy-install --disk /dev/nvme0n1` with that same disk path.
   Approval requires typing `ERASE <device> <device-specific-code>` exactly.
   **This command itself never partitions/wipes**; after approval it opens the
   standard interactive `archinstall` with `/root/sp11.json`.
5. **Review the selected disk AGAIN inside archinstall.** The approval wrapper
   cannot lock archinstall to the chosen disk. If the selected disk differs,
   cancel. For the easiest Windows replacement, use FAT32 EFI mounted at
   `/boot`, `ext4` mounted at `/`, and follow the installer prompts. Do not
   alter the preset's packages, bootloader, custom commands, or disabled UKI
   setting. Do **not** choose a desktop profile here.
6. Boot the installed **command-line** Arch system and get online with `nmtui`.
   Run `sudo sp11-grab-fw` to install proprietary GPU/other firmware. Then:

```sh
sudo sp11-cachy-postinstall --dry-run
sudo sp11-cachy-postinstall --apply
sudo reboot
```

The first command is read-only. The second confirms its own pacman transaction
and installs Plasma, SDDM, desktop tools and ZRAM. `archinstall` injects the
`sp11-cachy-postinstall` script into the target without running it prematurely.
If the command is missing, **stop and diagnose the archinstall logs**.

## KDE and performance choices

| Component | Toolkit choice |
| --- | --- |
| Desktop | KDE Plasma / Breeze Dark, Wayland-capable session |
| Login manager | SDDM enabled |
| Networking | NetworkManager plus Plasma network and audio controls |
| Memory | `zram-generator`, Zstandard, virtual swap at half RAM |
| Swapping | `vm.swappiness=100`, cache pressure 50 |
| Display/GPU | Keep upstream Qualcomm/Adreno stack and `sp11-grab-fw` |
| Kernel and scheduler | Keep `linux-sp11` kernel; no unsupported CachyOS kernel patches |
| Power | Plasma power management, no forced high-performance governor/TLP |
| Surface battery | Block duplicate `qcom_battmgr` driver as upstream recommends |

Expected from pinned upstream: NVMe, OLED brightness, GPU (after firmware),
Wi-Fi, Bluetooth, attached keyboard, touch/pen, speakers/mic, and suspend are
reported working to varying degrees. USB-C is partial; USB4 dock/Thunderbolt
and cameras remain **unsupported**. This toolkit has not independently tested
all capabilities on an OLED unit. Do not depend on a USB4 dock for setup.

## Rollback and recovery

- `sudo sp11-cachy-postinstall --rollback` restores any original versions of
  its **four config files**, and the prior SDDM-enabled state. It does not
  uninstall KDE or downgrade packages, firmware or kernel. Reboot afterward.
- A console remains available if KDE fails: use a virtual terminal or SSH,
  and inspect `journalctl -b -u sddm` and `pacman -Q linux-sp11`.
- For Linux boot recovery, boot the original known-good Surface ISO and consult
  the maintainer's bootloader/UKI guidance. The toolkit has not implemented an
  unattended EFI repair tool.
- For a *full* pre-install rollback, restore Windows using the official Surface
  recovery USB and your backup. A configuration rollback cannot resurrect
  erased Windows partitions.

## Verification performed and remaining work

- Unit tests cover source pin and boot preset guards, profile preservation,
  fail-closed disk policy, required human confirmation, manifest integrity,
  strict build-container digest and default build preview behavior.
- Integration staging was performed against the actual locked upstream source;
  `toolkit.py verify` passed. The copier deliberately preserves upstream's
  absolute/dangling systemd symlinks.
- **Not done:** build a complete ISO on an ARM64 runner, boot test on a Surface,
  verify actual Plasma package availability in the ARM repository at install
  time, test `archinstall` hook execution on hardware, test all OLED functions.
  Treat the first image as experimental until those steps pass.

## Credits

Surface enablement is the work of [Dale Whinham](https://github.com/dwhinham),
[archiso-aarch64](https://codeberg.org/ironrobin/archiso-aarch64), Arch Linux
Ports, kernel and device contributors. This toolkit is an optional, independent
overlay, **not affiliated with or endorsed by upstream**. Review all upstream
license and attribution obligations before redistributing derived images.
