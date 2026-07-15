#!/bin/bash
# Build script for Wobkey Crush 80 ZMK firmware
# Run from: /home/adyung/Projects/crush80/rainy75-zmk (WSL Ubuntu 24.04)
#
# Prerequisites (one-time, needs sudo):
#   sudo apt-get install -y protobuf-compiler
#
# Usage:
#   /bin/bash /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/build_crush80.sh

export PATH=/usr/bin:/usr/local/bin:/home/adyung/.local/bin:$PATH
export ZEPHYR_SDK_INSTALL_DIR=/home/adyung/zephyr-sdk-0.17.0

cd /home/adyung/Projects/crush80/rainy75-zmk

# Sync latest board files from Windows repo
WIN_REPO=/mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware
cp -r "$WIN_REPO/zmk/boards/crush80/"* zmk/boards/crush80/
cp -r "$WIN_REPO/zmk/drivers/led/"*   zmk/drivers/led/
echo "Board files synced."

CONF="$WIN_REPO/conf/app.conf"
OVERLAY=/home/adyung/Projects/crush80/rainy75-zmk/conf/mcumgr.overlay

# Overrides:
#   ZMK_KEYBOARD_NAME  — rename from "Rainy 75 Pro"
#   RAINY_RGB=n        — disable Rainy 75 WS2812 engine (Crush 80 uses AW20216S)
#   LED_STRIP_B91_SPI=n — disable PSPI/WS2812 driver (not used on Crush 80)
#
# NOTE: ZMK_STUDIO requires protobuf-compiler.
#   Install with: sudo apt-get install -y protobuf-compiler
#   Then remove the CONFIG_ZMK_STUDIO=n line below.
printf 'CONFIG_ZMK_KEYBOARD_NAME="Crush 80"\nCONFIG_ZMK_STUDIO=n\nCONFIG_RAINY_RGB=n\nCONFIG_LED_STRIP_B91_SPI=n\n' > /tmp/crush80_name.conf

west build -s zmk-src/app -b crush80 -d build-crush80 --pristine \
  -- \
  -DEXTRA_CONF_FILE="$CONF;/tmp/crush80_name.conf" \
  -DDTC_OVERLAY_FILE="$OVERLAY" \
  -DBOARD_ROOT=/home/adyung/Projects/crush80/rainy75-zmk/zmk

echo "BUILD_EXIT:$?"
