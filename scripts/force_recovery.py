#!/usr/bin/env python3
"""
Corrupt slot 0 image header to force MCUboot into serial recovery mode.

This sends ONE tiny flash_mgmt erase command (group 64, cmd 0) to erase
the first sector of slot 0 (address 0x10000). After this, MCUboot will
see no valid application and enter serial recovery on next boot.

Then you can upload new firmware at leisure with no time pressure:
  mcumgr --conntype serial --connstring "dev=/dev/cu.usbmodem1101,baud=115200" image upload firmware.signed.bin

Usage:
  1. Plug in keyboard
  2. Run: python3 scripts/force_recovery.py
  3. Unplug, wait 2s, replug
  4. MCUboot enters recovery (no app runs)
  5. Upload new firmware with mcumgr normally
"""

import sys
import os
import glob
import struct
import base64
import time

try:
    import serial
except ImportError:
    os.system(f"{sys.executable} -m pip install pyserial -q")
    import serial

try:
    import cbor2
except ImportError:
    os.system(f"{sys.executable} -m pip install cbor2 -q")
    import cbor2


def crc16_ccitt(data):
    crc = 0x0000
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_smp_frame(op, group, cmd_id, payload_dict):
    """Build a complete SMP serial frame."""
    cbor_data = cbor2.dumps(payload_dict)
    
    # SMP header: op(1) flags(1) len(2) group(2) seq(1) cmd_id(1)
    header = struct.pack("!BBHHBB", op, 0, len(cbor_data), group, 0, cmd_id)
    msg = header + cbor_data
    
    # CRC
    crc = crc16_ccitt(msg)
    pkt = struct.pack(">H", len(msg) + 2) + msg + struct.pack(">H", crc)
    
    # Base64 encode
    b64 = base64.b64encode(pkt)
    
    # Frame with SMP serial markers
    frame = b"\x06\x09" + b64 + b"\n"
    return frame


def main():
    # Find port
    ports = glob.glob('/dev/cu.usbmodem*')
    if not ports:
        print("ERROR: No keyboard found. Plug it in first.")
        sys.exit(1)
    
    port = ports[0]
    print(f"=== FORCE MCUboot RECOVERY MODE ===")
    print(f"Port: {port}")
    print(f"")
    print(f"This will erase the slot 0 image header at 0x10000.")
    print(f"After next power cycle, MCUboot will enter serial recovery.")
    print(f"")
    
    # Build the erase command: flash_mgmt group 64, cmd 0 (erase)
    # Erase one sector (4096 bytes) at offset 0x10000 (slot 0 start)
    payload = {"off": 0x10000, "len": 4096}
    frame = build_smp_frame(op=2, group=64, cmd_id=0, payload_dict=payload)
    
    print(f"Sending flash_mgmt erase command (off=0x10000, len=4096)...")
    
    # Open serial and send
    try:
        s = serial.Serial(port, 115200, timeout=3)
        s.dtr = True
        time.sleep(0.2)
        
        # Drain any pending data
        s.reset_input_buffer()
        
        # Send the erase command
        s.write(frame)
        s.flush()
        
        # Wait for response (look for SMP frame in response)
        time.sleep(1)
        response = s.read(4096)
        s.close()
        
        # Check if we got any SMP response
        if b"\x06\x09" in response:
            # Try to parse the response
            idx = response.index(b"\x06\x09")
            nl = response.find(b"\n", idx)
            if nl > idx:
                frame_b64 = response[idx + 2:nl]
                try:
                    raw = base64.b64decode(frame_b64)
                    pkt_len = struct.unpack(">H", raw[0:2])[0]
                    smp_msg = raw[2:2 + pkt_len - 2]
                    cbor_data = smp_msg[8:]
                    resp = cbor2.loads(cbor_data)
                    rc = resp.get("rc", -1)
                    if rc == 0:
                        print(f"SUCCESS! Erase command accepted (rc=0).")
                    else:
                        print(f"WARNING: Got response rc={rc}")
                except Exception as e:
                    print(f"Got SMP response (couldn't fully parse: {e})")
                    print(f"This likely means the command was received.")
        else:
            print(f"No clear SMP response detected in {len(response)} bytes.")
            print(f"The command may still have been processed.")
        
        print(f"")
        print(f"=== NEXT STEPS ===")
        print(f"1. UNPLUG the keyboard, wait 2 seconds")
        print(f"2. REPLUG — MCUboot should enter serial recovery")
        print(f"   (keyboard won't type — this is expected!)")
        print(f"3. Upload new firmware:")
        print(f"   ~/go/bin/mcumgr --conntype serial --connstring \\")
        print(f"     \"dev={port},baud=115200\" image upload \\")
        print(f"     dist/crush80-zmk-app.signed.MACMODE-WORKING.bin")
        print(f"4. After upload completes, unplug/replug to boot new firmware")
        
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
