#!/usr/bin/env bash
# Build ONLY the Wi-Fi-only OLED UKI. Never overwrite Windows boot files.
set -euo pipefail

esp=/boot
pkgbase=linux-sp11
dtb_name=qcom/x1e80100-microsoft-denali-oled.dtb
target="$esp/EFI/Linux/$pkgbase-oled.efi"
reserve=$((64 * 1024 * 1024))  # Leave space for Windows EFI updates.

if [[ "$(uname -m)" != aarch64 ]] || ! mountpoint -q "$esp"; then
    echo 'Refusing UKI build: require mounted /boot on native ARM64' >&2
    exit 1
fi
if [[ "$(findmnt -n -M "$esp" -o FSTYPE)" != vfat ]] ||
   [[ ! -f "$esp/EFI/Microsoft/Boot/bootmgfw.efi" ]]; then
    echo 'Refusing UKI build: existing Windows FAT32 ESP not detected' >&2
    exit 1
fi

kver=
for f in /usr/lib/modules/*/pkgbase; do
    [[ -r "$f" && "$(<"$f")" == "$pkgbase" ]] || continue
    kver=${f%/pkgbase}
    kver=${kver##*/}
done
[[ -n "$kver" ]] || { echo 'linux-sp11 kernel missing' >&2; exit 1; }
initrd="$esp/initramfs-$pkgbase.img"
dtb="/usr/lib/modules/$kver/dtb/$dtb_name"
kernel="/usr/lib/modules/$kver/vmlinuz"
for file in "$initrd" "$dtb" "$kernel" /etc/kernel/cmdline; do
    [[ -r "$file" ]] || { echo "Missing $file; stopping before EFI writes" >&2; exit 1; }
done

# ukify creates the candidate on the root filesystem, not on Windows' small ESP.
work=$(mktemp -d /var/tmp/sp11-cachy-uki.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
osrel=$(printf 'ID=arch\nPRETTY_NAME=Arch Linux (Surface Pro 11 OLED Wi-Fi)\nVERSION_ID=%s\n' "$kver")
ukify build \
    --uname="$kver" \
    --hwids= \
    --linux="$kernel" \
    --initrd="$initrd" \
    --cmdline=@/etc/kernel/cmdline \
    --os-release="$osrel" \
    --devicetree="$dtb" \
    --output="$work/$pkgbase-oled.efi"

candidate_size=$(stat -c %s "$work/$pkgbase-oled.efi")
available=$(df -B1 --output=avail "$esp" | tail -n 1 | tr -d '[:space:]')
if (( available < candidate_size + reserve )); then
    echo "Refusing EFI write: only $available bytes free; UKI needs $candidate_size plus $reserve reserve" >&2
    echo 'Windows boot files are untouched. A larger boot partition plan is needed.' >&2
    exit 1
fi

install -d "$esp/EFI/Linux"
install -m 0644 "$work/$pkgbase-oled.efi" "$target.new"
mv -f -- "$target.new" "$target"
echo "Installed only $target; preserved Windows Boot Manager and >=64 MiB free reserve"
