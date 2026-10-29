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
SERVICES=(sddm.service NetworkManager.service bluetooth.service)
PACKAGES=(
    plasma-meta sddm plasma-nm plasma-pa konsole dolphin
    xdg-desktop-portal-kde zram-generator powerdevil
    bluez bluez-utils bluedevil
    pipewire pipewire-alsa pipewire-pulse wireplumber alsa-utils
)

usage() {
    echo 'Usage: sudo sp11-cachy-postinstall --dry-run | --firmware | --apply | --rollback'
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
    local service
    for service in "${SERVICES[@]}"; do
        if systemctl is-enabled --quiet "$service"; then
            printf 'ENABLED %s\n' "$service" >> "$MANIFEST"
        else
            printf 'DISABLED %s\n' "$service" >> "$MANIFEST"
        fi
    done
}

install_firmware() {
    require_system
    if ! command -v sp11-grab-fw >/dev/null 2>&1; then
        echo 'Missing upstream sp11-grab-fw helper; stop and check the Surface repository.' >&2
        exit 1
    fi
    if [[ ! -t 0 ]]; then
        echo 'Firmware installation requires interactive confirmation on a terminal.' >&2
        exit 1
    fi
    echo 'This will run the upstream Surface firmware extractor/downloader.'
    echo 'The proprietary GPU, audio DSP and video-codec files are NOT part of the ISO.'
    echo 'DO NOT perform this step from a live USB; the aDSP can disrupt USB boot.'
    read -r -p 'Type INSTALL SURFACE FIRMWARE to continue: ' approval
    if [[ $approval != 'INSTALL SURFACE FIRMWARE' ]]; then
        echo 'Firmware installation cancelled.'
        return 1
    fi
    sp11-grab-fw
    echo 'Reboot and confirm Adreno GPU firmware initializes BEFORE starting KDE.'
    echo 'Speaker protection is incomplete: keep output muted until safe UCM limits are confirmed.'
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
    # The upstream Surface SAM battery reports richer data. Blacklist only
    # the duplicate Qualcomm battery provider, per the pinned upstream README.
    printf 'blacklist qcom_battmgr\n' > /etc/modprobe.d/sp11-cachy-battery.conf
    printf '[General]\nColorScheme=BreezeDark\n[Icons]\nTheme=breeze-dark\n' > /etc/xdg/kdeglobals
    systemctl enable "${SERVICES[@]}"
    if pacman -Si iptsd >/dev/null 2>&1; then
        echo 'Installing optional Surface touchscreen/pen userspace (iptsd).'
        pacman -S --needed iptsd
        echo 'Verify iptsd device/service configuration before relying on pen or gestures.'
    else
        echo 'Check the upstream iptsd/touchscreen guidance; package not found in current repos.'
    fi
    echo 'Installed KDE, Bluetooth, PipeWire, and conservative ZRAM tuning.'
    echo 'Run sp11-cachy-hwcheck; GPU/audio firmware must be installed separately.'
    echo 'If needed: sudo sp11-cachy-postinstall --firmware, then REBOOT.'
    echo 'Do not test speakers at high volume: hardware speaker protection is incomplete.'
    echo 'Configure /etc/sp11-mac.conf using your REAL Wi-Fi/Bluetooth MACs from Windows.'
    echo 'Do not put your personal MAC addresses into a public GitHub repository.'
    echo 'Cameras and USB4 remain unsupported in the pinned upstream release.'
}

rollback_config() {
    require_system
    if [[ ! -f $MANIFEST ]]; then
        echo 'No recorded configuration to roll back.' >&2
        exit 1
    fi
    echo 'Restoring configuration files and prior service enablement. Packages are NOT removed.'
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
            ENABLED|DISABLED)
                case " ${SERVICES[*]} " in
                    *" $destination "*) ;;
                    *) echo "Invalid service backup: $destination" >&2; exit 1 ;;
                esac
                if [[ $state == ENABLED ]]; then
                    systemctl enable "$destination"
                else
                    systemctl disable "$destination"
                fi
                ;;
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
        printf 'Would enable services: %s\n' "${SERVICES[*]}"
        echo 'No kernel, bootloader, partition or firmware changes from --apply.'
        echo 'Use --firmware separately, after booting installed Arch (never from USB).'
        ;;
    --firmware) install_firmware ;;
    --apply) apply_config ;;
    --rollback) rollback_config ;;
    *) usage >&2; exit 2 ;;
esac
