#!/usr/bin/env python3
"""Recovery flash for Crush 80 when SMP is unresponsive.
Waits for keyboard USB to appear after plug-in, then uploads immediately."""
import glob, time, subprocess, sys, os

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(REPO_DIR, "dist", "crush80-zmk-app.signed.bin")
MCUMGR = os.path.expanduser("~/go/bin/mcumgr")

if not os.path.exists(IMAGE):
    print(f"ERROR: {IMAGE} not found. Run: bash build.sh --skip-bridge --skip-mcuboot")
    sys.exit(1)

print("=== Crush 80 Recovery Flash ===")
print(f"Image: {IMAGE}")
print()
print("1. Unplug the keyboard")
print("2. Press Enter when ready")
print("3. Plug the keyboard back in")
input("\nPress Enter to start waiting...")

print("\nWaiting for keyboard USB port...")
found_at = None
for i in range(120):
    ports = glob.glob('/dev/cu.usbmodem*')
    if ports:
        if found_at is None:
            found_at = time.time()
            print(f"  Port appeared: {ports[0]}")
        elif time.time() - found_at > 2.5:
            port = ports[0]
            print(f"  Port stable! Starting upload...")
            break
    else:
        found_at = None
    time.sleep(0.5)
else:
    print("ERROR: Timeout waiting for keyboard")
    sys.exit(1)

conn = f"dev={port},baud=115200"
r = subprocess.run([MCUMGR, "--conntype", "serial", "--connstring", conn,
    "image", "upload", IMAGE], timeout=300)
if r.returncode != 0:
    print("Upload failed!")
    sys.exit(1)

print("\nUpload complete! Running test+reset+confirm...")
# Get hash
r = subprocess.run([MCUMGR, "--conntype", "serial", "--connstring", conn,
    "image", "list"], capture_output=True, text=True, timeout=15)
lines = r.stdout.split('\n')
in_slot1 = False
hash_val = None
for line in lines:
    if 'slot=1' in line: in_slot1 = True
    elif in_slot1 and 'hash:' in line:
        hash_val = line.strip().split('hash:')[1].strip()
        break
    elif in_slot1 and 'slot=0' in line: break

if hash_val:
    subprocess.run([MCUMGR, "--conntype", "serial", "--connstring", conn,
        "image", "test", hash_val], timeout=15)
    subprocess.run([MCUMGR, "--conntype", "serial", "--connstring", conn,
        "reset"], timeout=10)
    print("Waiting 12s for MCUboot swap...")
    time.sleep(12)
    subprocess.run([MCUMGR, "--conntype", "serial", "--connstring", conn,
        "image", "confirm", ""], timeout=15)
    print("\nDone! Firmware recovered and confirmed.")
else:
    print("WARNING: Could not find slot 1 hash. Manual confirm needed after reboot.")
