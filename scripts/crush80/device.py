"""Find the keyboard and tell which firmware it is running."""

import glob
import time

STOCK_USB = "320f:5055"   # stock Wobkey firmware
ZMK_USB = "1d50:615e"     # ZMK app, OTA bridge and MCUboot serial recovery

PORT_GLOBS = ("/dev/cu.usbmodem*", "/dev/ttyACM*")


def find_ports():
    ports = []
    for pattern in PORT_GLOBS:
        ports += sorted(glob.glob(pattern))
    return ports


def wait_for_port(timeout, gone_first=False, poll=0.25, sleep=time.sleep, clock=time.monotonic, ports=find_ports):
    """Wait until exactly one serial port is present. With gone_first, require it to vanish first
    (the unplug) so a stale port from before the unplug is never mistaken for the reboot."""
    deadline = clock() + timeout
    if gone_first:
        while ports() and clock() < deadline:
            sleep(poll)
        if clock() >= deadline:
            return None
    while clock() < deadline:
        found = ports()
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise RuntimeError(f"several serial devices present ({', '.join(found)}); unplug the others")
        sleep(poll)
    return None
