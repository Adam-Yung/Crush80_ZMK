"""Command line for the Crush 80 install and upgrade procedures: ./crush80 --help"""

import argparse
import os
import sys

from . import device, flows, mcuimg
from .mcumgr import McumgrError

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_IMAGE = os.path.join(REPO, "dist", "crush80-zmk-app.signed.bin")


def _port(args):
    port = args.port or device.wait_for_port(10)
    if not port:
        raise flows.FlowError("no keyboard serial port found (is it plugged in, and running ZMK?)")
    return port


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crush80", description=__doc__)
    ap.add_argument("--port", help="serial port (default: auto-detect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="validate a signed image offline; touches nothing")
    p.add_argument("image", nargs="?", default=DEFAULT_IMAGE)
    sub.add_parser("golden", help="verify the known-good release images against releases/MANIFEST.sha256")
    sub.add_parser("status", help="what the board is running (read-only)")
    sub.add_parser("backup", help="dump the flash to backups/<timestamp>/ (read-only, ~3 min)")
    p = sub.add_parser("update", help="safe upgrade: upload, trial boot, verify, confirm")
    p.add_argument("image", nargs="?", default=DEFAULT_IMAGE)
    sub.add_parser("confirm", help="make the running trial image permanent")
    sub.add_parser("recover", help="hung or unresponsive board: force bootloader recovery, reload known-good image")
    p = sub.add_parser("stock-restore", help="replace ZMK with a stock firmware image (dry run unless --commit)")
    p.add_argument("image")
    p.add_argument("--commit", action="store_true", help="really replace the firmware; backup required")

    args = ap.parse_args(argv)
    ui = flows.Ui()
    try:
        if args.cmd == "check":
            img = mcuimg.parse(args.image)
            ui.say(f"OK  {img.path}\n    {img.size} bytes, version {img.version}, sha256 {img.sha256}")
        elif args.cmd == "golden":
            for path in flows.check_golden(REPO):
                ui.say(f"OK  {os.path.relpath(path, REPO)}")
        elif args.cmd == "status":
            flows.status(ui, _port(args))
        elif args.cmd == "backup":
            flows.backup(ui, _port(args), os.path.join(REPO, "backups"))
        elif args.cmd == "update":
            flows.update(ui, REPO, args.image, args.port)
        elif args.cmd == "confirm":
            flows.confirm(ui, _port(args))
        elif args.cmd == "recover":
            flows.recover(ui, REPO)
        elif args.cmd == "stock-restore":
            flows.stock_restore(ui, REPO, args.image, _port(args), args.commit)
    except (flows.FlowError, mcuimg.ImageError, McumgrError, OSError) as e:
        print(f"\nSTOPPED: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. The board is in whatever state the last printed step left it.", file=sys.stderr)
        return 130
    return 0
