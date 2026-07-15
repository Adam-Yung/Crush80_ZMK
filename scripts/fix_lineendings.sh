#!/bin/bash
set -euo pipefail
for f in \
  /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/build.sh \
  /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/flash.sh \
  /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/setup.sh; do
  sed -i 's/\r//' "$f"
  echo "LF: $f"
done
