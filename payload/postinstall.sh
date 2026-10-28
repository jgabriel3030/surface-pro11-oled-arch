#!/usr/bin/env bash
# Runs only after first boot into installed Arch. Never partitions a disk.
set -euo pipefail

STATE=/var/lib/sp11-cachy
MANIFEST="$STATE/config-backup-manifest"
FILES=(
    /etc/systemd/zram-generator.conf
    /etc/sysctl.d/90-sp11-cachy-memory.conf
    /etc/modprobe.d/sp11-cachy-battery.conf
    /etc/xdg/kdeglobals
)
PACKAGES=(
    plasma-meta sddm plasma-nm plasma-pa konsole dolphin
    xdg-desktop-portal-kde zram-generator
)

usage() {
    echo 'Usage: sudo sp11-cachy-postinstall --dry-run | --apply | --rollback'
}

require_system() {
    if (( EUID != 0 )); then
        echo 'Run as root via sudo.' >&2
        exit 1
    fi
    if [[ $(uname -m) != aarch64 ]] || ! pacman --version >/dev/null 2>&1; then
        echo 'This script supports installed AArch64 Arch Linux only.' >&2
        exit 1
    fi
    if ! pacman -Q linux-sp11 >/dev/null 2>&1; then
        echo 'Refusing to tune a system without the Surface linux-sp11 kernel.' >&2
        exit 1
    fi
    if [[ -d /run/archiso ]]; then
        echo 'Boot the newly installed Arch system first; do not configure the live ISO.' >&2
        exit 1
    fi
}

backup_config() {
    if [[ -f $MANIFEST ]]; then
        echo "Keeping original configuration backup: $STATE"
        return
    fi
    install -d -m 700 "$STATE/original"
    : > "$MANIFEST"
    chmod 600 "$MANIFEST"
    for destination in "${FILES[@]}"; do
        if [[ -e $destination ]]; then
            printf 'PRESENT %s\n' "$destination" >> "$MANIFEST"
            install -d "$STATE/original$(dirname "$destination")"
            cp -a -- "$destination" "$STATE/original$destination"
        else
            printf 'ABSENT %s\n' "$destination" >> "$MANIFEST"
        fi
    done
    if systemctl is-enabled --quiet sddm.service; then
        printf 'ENABLED /usr/lib/systemd/system/sddm.service\n' >> "$MANIFEST"
    else
        printf 'DISABLED /usr/lib/systemd/system/sddm.service\n' >> "$MANIFEST"
    fi
}

apply_config() {
    require_system
    echo 'Installing KDE Plasma and ZRAM using the configured Arch Linux Ports repositories.'
    echo 'Pacman may also perform a full system update. Review its transaction before agreeing.'
    pacman -Syu --needed "${PACKAGES[@]}"
    backup_config
    install -d -m 755 /etc/systemd /etc/sysctl.d /etc/modprobe.d /etc/xdg
    printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\nswap-priority = 100\n' \
        > /etc/systemd/zram-generator.conf
    printf 'vm.swappiness = 100\nvm.vfs_cache_pressure = 50\n' \
        > /etc/sysctl.d/90-sp11-cachy-memory.conf
    printf 'blacklist qcom_battmgr\n' > /etc/modprobe.d/sp11-cachy-battery.conf
    printf '[General]\nColorScheme=BreezeDark\n[Icons]\nTheme=breeze-dark\n' > /etc/xdg/kdeglobals
    systemctl enable sddm.service NetworkManager.service
    if pacman -Si iptsd >/dev/null 2>&1; then
        echo 'Optional touchscreen/pen userspace: iptsd is available. Install and enable it if necessary.'
    else
        echo 'Check the upstream iptsd/touchscreen guidance; package not found in current repos.'
    fi
    echo 'Installed KDE and conservative ZRAM tuning; original configuration backed up.'
    echo 'Run sudo sp11-grab-fw if you have not already, then REBOOT.'
    echo 'Cameras and USB4 remain unsupported in the pinned upstream release.'
}

rollback_config() {
    require_system
    if [[ ! -f $MANIFEST ]]; then
        echo 'No recorded configuration to roll back.' >&2
        exit 1
    fi
    echo 'Restoring configuration files and prior SDDM enablement. Packages are NOT removed.'
    while read -r state destination; do
        case "$state" in
            PRESENT)
                # Only ever touch the four paths this script is allowed to manage.
                if [[ ! " ${FILES[*]} " == *" $destination "* ]]; then
                    echo "Invalid backup path: $destination" >&2
                    exit 1
                fi
                cp -a -- "$STATE/original$destination" "$destination"
                ;;
            ABSENT)
                if [[ ! " ${FILES[*]} " == *" $destination "* ]]; then
                    echo "Invalid backup path: $destination" >&2
                    exit 1
                fi
                rm -f -- "$destination"
                ;;
            ENABLED) systemctl enable sddm.service ;;
            DISABLED) systemctl disable sddm.service ;;
            *) echo "Unrecognized backup record: $state" >&2; exit 1 ;;
        esac
    done < "$MANIFEST"
    echo 'Configuration restored. Reboot. Plasma packages, kernel, and firmware were not rolled back.'
}

case "${1:---dry-run}" in
    --dry-run)
        echo 'DRY RUN: this script will NOT modify the system.'
        printf 'Would upgrade/install packages: %s\n' "${PACKAGES[*]}"
        echo 'Would back up and write four configuration files:'
        printf '  %s\n' "${FILES[@]}"
        echo 'Would enable SDDM and NetworkManager; no kernel or bootloader changes.'
        echo 'Requires first-boot internet, sudo, linux-sp11, and a separate sp11-grab-fw run.'
        ;;
    --apply) apply_config ;;
    --rollback) rollback_config ;;
    *) usage >&2; exit 2 ;;
esac
