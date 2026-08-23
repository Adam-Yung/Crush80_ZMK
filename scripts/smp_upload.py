#!/usr/bin/env python3
"""
SMP image uploader that works even when the serial port is flooded with log output.
Filters SMP response frames (0x06 0x09 prefix) from the noise.
"""

import serial
import struct
import base64
import hashlib
import time
import sys
import os
import threading
import cbor2

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem1101"
IMAGE = sys.argv[2] if len(sys.argv) > 2 else "dist/crush80-zmk-app.signed.bin"
BAUD = 115200
CHUNK_SIZE = 512
MAX_RETRIES = 5
TIMEOUT = 8

class SMPSerial:
    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baud, timeout=0.05)
        self.ser.dtr = True
        self.ser.rts = True
        self.seq = 0
        self.response_buf = b""
        self.responses = {}
        self.lock = threading.Lock()
        self.running = True
        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()
        time.sleep(0.5)

    def _reader(self):
        """Continuously read serial, extract SMP frames from log noise."""
        buf = b""
        while self.running:
            try:
                data = self.ser.read(4096)
                if not data:
                    continue
                buf += data
                # Look for SMP frames: 0x06 0x09 ... \n
                while b"\x06\x09" in buf:
                    idx = buf.index(b"\x06\x09")
                    # Find end of frame (newline)
                    nl = buf.find(b"\n", idx)
                    if nl == -1:
                        buf = buf[idx:]  # keep from frame start
                        break
                    frame = buf[idx+2:nl]
                    buf = buf[nl+1:]
                    # Decode base64 SMP response
                    try:
                        raw = base64.b64decode(frame)
                        if len(raw) >= 8:
                            op, flags, length, group, seq, cmd_id = struct.unpack(">BBHHBB", raw[:8])
                            payload = raw[8:8+length] if length <= len(raw)-8 else raw[8:]
                            with self.lock:
                                self.responses[seq] = (op, group, cmd_id, payload)
                    except Exception:
                        pass
                # Trim buffer to prevent unbounded growth
                if len(buf) > 65536:
                    buf = buf[-4096:]
            except serial.SerialException:
                time.sleep(0.1)
            except Exception:
                time.sleep(0.01)

    def send(self, op, group, cmd_id, payload_dict):
        """Send SMP command, return response dict or None."""
        self.seq = (self.seq + 1) % 256
        seq = self.seq
        payload = cbor2.dumps(payload_dict)
        hdr = struct.pack(">BBHHBBBB", op, 0, len(payload), 0, group, seq, 0, cmd_id)
        raw = hdr + payload
        frame = b"\x06\x09" + base64.b64encode(raw) + b"\n"
        
        # Clear any old response for this seq
        with self.lock:
            self.responses.pop(seq, None)
        
        self.ser.write(frame)
        self.ser.flush()
        
        # Wait for response
        start = time.time()
        while time.time() - start < TIMEOUT:
            with self.lock:
                if seq in self.responses:
                    op, grp, cid, data = self.responses.pop(seq)
                    try:
                        return cbor2.loads(data)
                    except:
                        return {"raw": data}
            time.sleep(0.05)
        return None

    def close(self):
        self.running = False
        self.ser.close()


def upload_image(smp, image_path):
    """Upload image using MCUmgr image upload protocol."""
    with open(image_path, "rb") as f:
        image_data = f.read()
    
    total = len(image_data)
    sha = hashlib.sha256(image_data).digest()
    offset = 0
    
    print(f"Uploading {total} bytes ({total//1024} KB)...")
    
    while offset < total:
        chunk = image_data[offset:offset+CHUNK_SIZE]
        
        payload = {
            "off": offset,
            "data": chunk,
            "len": total,
        }
        if offset == 0:
            payload["sha"] = sha
            payload["image"] = 0
        
        for retry in range(MAX_RETRIES):
            resp = smp.send(2, 1, 0, payload)  # op=write, group=img(1), cmd=upload(0)
            if resp is not None:
                if "rc" in resp and resp["rc"] != 0:
                    print(f"\nError at offset {offset}: rc={resp['rc']}")
                    return False
                new_off = resp.get("off", offset + len(chunk))
                offset = new_off
                break
            else:
                if retry < MAX_RETRIES - 1:
                    sys.stdout.write("R")
                    sys.stdout.flush()
                    time.sleep(0.5)
        else:
            print(f"\nFailed at offset {offset} after {MAX_RETRIES} retries")
            return False
        
        pct = offset * 100 // total
        sys.stdout.write(f"\r  {offset//1024}/{total//1024} KB ({pct}%)")
        sys.stdout.flush()
    
    print(f"\r  {total//1024}/{total//1024} KB (100%) - Done!")
    return True


def confirm_image(smp):
    """Mark the uploaded image for test boot."""
    # List images to get hash
    resp = smp.send(0, 1, 0, {})  # op=read, group=img(1), cmd=state(0)
    if resp is None:
        print("Failed to list images")
        return False
    
    images = resp.get("images", [])
    for img in images:
        if img.get("slot") == 1:
            hash_val = img.get("hash")
            if hash_val:
                # Test the image
                resp2 = smp.send(2, 1, 0, {"confirm": False, "hash": hash_val})
                if resp2 is not None:
                    print("Image marked for test boot")
                    return True
    print("Could not find slot 1 image to confirm")
    return False


def reset(smp):
    """Reset the device."""
    resp = smp.send(2, 0, 5, {})  # op=write, group=os(0), cmd=reset(5)
    if resp is not None:
        print("Reset command sent")
    else:
        print("Reset sent (no response - normal)")


def main():
    print(f"Connecting to {PORT}...")
    smp = SMPSerial(PORT, BAUD)
    
    # Test connectivity
    print("Testing SMP echo...")
    resp = smp.send(2, 0, 0, {"d": "test"})
    if resp:
        print(f"  Echo OK: {resp}")
    else:
        print("  No echo response (log flood may be heavy, continuing anyway...)")
    
    # Upload
    if not upload_image(smp, IMAGE):
        smp.close()
        sys.exit(1)
    
    # Confirm for test boot
    print("Confirming image for test boot...")
    confirm_image(smp)
    
    # Reset
    print("Resetting...")
    reset(smp)
    
    smp.close()
    print("\nDone! Keyboard should reboot with new firmware.")


if __name__ == "__main__":
    main()
