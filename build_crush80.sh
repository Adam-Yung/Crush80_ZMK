#!/bin/bash
export PATH=/usr/bin:/usr/local/bin:/home/adyung/.local/bin:$PATH
export ZEPHYR_SDK_INSTALL_DIR=/home/adyung/zephyr-sdk-0.17.0

cd /home/adyung/Projects/crush80/rainy75-zmk

printf 'CONFIG_ZMK_KEYBOARD_NAME="Crush 80"\nCONFIG_ZMK_STUDIO=n\nCONFIG_RAINY_RGB=n\nCONFIG_LED_STRIP_B91_SPI=n\nCONFIG_LED_STRIP_B91_SPI_PC2_POWER=n\n' > /tmp/crush80_name.conf

CONF=/home/adyung/Projects/crush80/rainy75-zmk/conf/app.conf
EXTRA="$CONF;/tmp/crush80_name.conf"

west build -s zmk-src/app -b crush80 -d build-crush80 --pristine \
  -- \
  -DEXTRA_CONF_FILE="$EXTRA" \
  -DDTC_OVERLAY_FILE=/home/adyung/Projects/crush80/rainy75-zmk/conf/mcumgr.overlay \
  -DBOARD_ROOT=/home/adyung/Projects/crush80/rainy75-zmk/zmk

echo "BUILD6_EXIT:$?"
