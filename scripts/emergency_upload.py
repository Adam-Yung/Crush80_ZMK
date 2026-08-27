#!/usr/bin/env python3
"""
Emergency upload for Crush80 — gets firmware through before system hangs.
Previously achieved 96% in one burst. Just keep retrying until 100%.
"""
import glob, os, sys, time, subprocess, select

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    REPO_DIR, "dist", "crush80-zmk-app.signed.MACMODE-WORKING.bin")
MCUMGR = os.path.expanduser("~/go/bin/mcumgr")
STALL_TIMEOUT = 8

if not os.path.exists(IMAGE):
    print(f"ERROR: {IMAGE} not found"); sys.exit(1)

IMAGE_SIZE = os.path.getsize(IMAGE)

def detect_port():
    ports = glob.glob('/dev/cu.usbmodem*')
    return ports[0] if ports else None

def wait_for_port(timeout=120):
    for _ in range(timeout * 5):
        p = detect_port()
        if p: return p
        time.sleep(0.2)
    return None

def wait_for_disconnect(timeout=60):
    for _ in range(timeout * 5):
        if not detect_port(): return True
        time.sleep(0.2)
    return False

def upload_burst(port):
    import serial
    s = serial.Serial(port, 115200, timeout=0.1)
    s.dtr = True
    time.sleep(0.1)
    s.close()
    time.sleep(0.3)

    conn = f"dev={port},baud=115200,mtu=256"
    proc = subprocess.Popen(
        [MCUMGR, "--conntype", "serial", "--connstring", conn,
         "image", "upload", "-w", "1", "-t", "4", IMAGE],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    last_time = time.time()
    best = 0.0

    while True:
        ret = proc.poll()
        if ret is not None:
            out = proc.stdout.read().decode(errors='replace')
            if "100.00%" in out: return (True, 100.0)
            return (False, best)

        ready = select.select([proc.stdout], [], [], 1.0)
        if ready[0]:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, 'read1') else os.read(proc.stdout.fileno(), 4096)
            if chunk:
                text = chunk.decode(errors='replace')
                for tok in text.replace('\r', ' ').split():
                    if '%' in tok:
                        try:
                            v = float(tok.replace('%',''))
                            if v > best:
                                best = v
                                last_time = time.time()
                                kb = int(v * IMAGE_SIZE / 100 / 1024)
                                sys.stdout.write(f"\r    {v:.1f}% ({kb}/{IMAGE_SIZE//1024} KB)  ")
                                sys.stdout.flush()
                        except: pass

        if time.time() - last_time > STALL_TIMEOUT:
            proc.kill(); proc.wait()
            return (False, best)

def main():
    print(f"Emergency upload: {os.path.basename(IMAGE)} ({IMAGE_SIZE//1024} KB)")
    print(f"Keep doing unplug/replug cycles. Target: 100%.\n")

    cycle = 0
    best_ever = 0.0

    while True:
        cycle += 1
        port = detect_port()
        if not port:
            print("  Plug in keyboard..." if cycle == 1 else "  Replug keyboard...")
            port = wait_for_port()
            if not port: print("ERROR: timeout"); sys.exit(1)

        print(f"\n  Cycle {cycle} (best: {best_ever:.1f}%) — port {port}")
        ok, pct = upload_burst(port)
        best_ever = max(best_ever, pct)

        if ok:
            print(f"\n\n  === 100% DONE! Unplug, wait 2s, replug. ===")
            return

        print(f"\n    Stalled at {pct:.1f}%. Best ever: {best_ever:.1f}%")
        print("  UNPLUG now, wait 2s, replug.")
        wait_for_disconnect()
        time.sleep(2)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nAborted."); sys.exit(0)
