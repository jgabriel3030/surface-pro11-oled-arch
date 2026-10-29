# Surface Pro 11 OLED/X Elite — October 2026 field-test record

Source: owner-operated tests using the first custom Arch Linux Ports AArch64
ISO built from this toolkit, flashed with BalenaEtcher to a USB drive.
All commands below were run from the live `root@archiso` console. **The
internal Windows NVMe disk was not modified or erased.**

| Component | Observed result | Classification |
| --- | --- | --- |
| USB UEFI boot | Booted to an Arch Linux shell on the internal OLED | Pass |
| OLED display | `/sys/class/drm/*/modes` showed `2880x1920` | Native mode detected |
| OLED brightness | `/sys/class/backlight/dp_aux_backlight/brightness` existed; max `4095`, initial `737`; changing the value visibly changed brightness | Manual control passes; KDE keys untested |
| Wi-Fi | `iw` showed `wlan0`, `iwctl` connected to the owner's network; ping/IP/DNS succeeded | Pass |
| Internal battery | `BAT1` reported `Charging`, `98`; `ADP1/online` returned `1` | Pass for reporting/charger detection |
| Touchscreen | SPI `045E:0C83 Touchscreen`, event6; reading `/dev/input/event6` produced events when finger moved | Raw input pass; gestures/calibration untested |
| Keyboard | Attached Surface keyboard operated the live shell | Pass |
| Internal NVMe | `/dev/nvme0n1` reported approximately 476.9 GiB and existing Windows partitions | Detection only; **not erased** |
| Graphics device | `/dev/dri/card0` and `renderD128` exposed, sysfs driver `msm_dpu` | DPU/display detected; **not a 3D acceleration pass** |
| Adreno GPU | Kernel loaded `qcom/gen70500_sqe.fw` and `qcom/gen70500_gmu.bin`, then failed missing `qcom/x1e80100/microsoft/qcdxkmsuc8380.mbn` (`-2`), with GMU timeout | **GPU init failed**; post-install firmware required |
| Audio | `/proc/asound/cards` returned no sound cards; aDSP missing `qcom/x1e80100/microsoft/Denali/qcadsp8380.mbn` (`-2`) | **Blocked**; never force-load aDSP while USB-booted |
| Video codec | Iris driver missing `qcom/x1e80100/microsoft/Denali/qcvss8380.mbn` (`-2`) | Hardware codec unverified |
| Bluetooth firmware | Kernel reported WCN7850, downloaded `qca/hmtbtfw20.tlv` and `qca/hmtnv20.bin`, and completed QCA UART setup | Initial firmware bring-up pass |
| Bluetooth userspace | Initial ISO had `bluez-utils` but not `bluez`; owner installed BlueZ 5.87-2 in live session and started `bluetooth.service`; `bluetoothctl list` was empty and `/sys/class/bluetooth/hci0/address` did not exist | **Unresolved**; Surface MAC setup/adapter registration requires testing |
| Live package hook | Installing BlueZ triggered a post-transaction `mkinitcpio` error for unreadable `/boot/vmlinuz-linux-sp11` | Live-USB hook issue; avoid ad-hoc boot repairs |
| 120 Hz, HDR, suspend/resume, cameras, Bluetooth pairing, audio playback, pen | Not independently tested | Unknown |

## Changes derived from these results (v2 toolkit)

1. Put `bluez`, `bluez-utils`, and `evtest` on the live USB, avoiding the
   owner's manual BlueZ package installation in future live sessions.
2. Add `sp11-cachy-hwcheck` for a **read-only**, one-command summary in both
   live USB and installed Arch; it distinguishes missing proprietary firmware
   and missing Bluetooth HCI interfaces from mere driver discovery.
3. Extend the post-install KDE package set with Bluedevil, PowerDevil,
   PipeWire/WirePlumber, ALSA tools, and optional `iptsd` if available.
4. Add a separate **installed-system-only**, interactively confirmed
   `sp11-cachy-postinstall --firmware` action delegating to the upstream
   `sp11-grab-fw`; never embed proprietary blobs in public source or an ISO.
5. Back up and restore enablement of Bluetooth and NetworkManager as well as
   SDDM during Cachy-style settings rollback.
6. Preserve the upstream Surface kernel, UKI/bootloader commands, and two-step
   human disk-approval requirement without automating disk erasure.

## Important unresolved risks

- Surface audio hardware speaker protection is incomplete. Do not play audio
  at high volume merely because a sound card appears after firmware install.
- Old upstream USB tests warned that loading aDSP firmware from live USB can
  cause USB disconnects or boot failures. The toolkit deliberately performs
  proprietary firmware setup only *after installed-system boot*.
- Bluetooth `hci0` was observed **in kernel startup messages** but was not
  available as a current controller to BlueZ. Missing/incorrect MAC fixup is
  a plausible explanation, **not established by this test**. Never hardcode
  the owner's personal device addresses into the public GitHub repository.
- Until actual Plasma + firmware tests pass, **do not treat the ISO as a
  production-ready Windows replacement**. Windows recovery media and complete
  backups should be prepared before any internal SSD modification.

Upstream project and hardware status: https://github.com/dwhinham/archiso-aarch64-sp11
