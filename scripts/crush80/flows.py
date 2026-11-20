"""The install, update, backup and recovery procedures. Each step that can fail says what state the board is in."""

import datetime
import hashlib
import json
import os
import time

from . import device, mcuimg, smp
from .mcumgr import Mcumgr, McumgrError
from .serialport import RawSerial

SLOT0 = 0x10000
FLASH_BACKUP_END = 0xFE000   # firmware refuses flash_mgmt access at and above this (RF calibration, MAC)
STOCK_STAGING = 0x80000
READ_CHUNK = 256


class FlowError(Exception):
    pass


class Ui:
    """All console interaction, so flows can be driven by tests."""

    def say(self, msg=""):
        print(msg, flush=True)

    def ask(self, prompt):
        return input(prompt + " ").strip().lower() in ("y", "yes")

    def pause(self, prompt):
        input(prompt + " ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def check_golden(repo):
    """Verify releases/ against releases/MANIFEST.sha256. A known-good image on disk is a precondition for flashing."""
    manifest = os.path.join(repo, "releases", "MANIFEST.sha256")
    if not os.path.exists(manifest):
        raise FlowError("releases/MANIFEST.sha256 is missing: no verified known-good image to fall back on")
    good = []
    with open(manifest) as f:
        lines = f.read().splitlines()
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        digest, name = line.split(None, 1)
        path = os.path.join(repo, "releases", name.strip())
        if not os.path.exists(path) or sha256_file(path) != digest:
            raise FlowError(f"releases/{name.strip()} does not match MANIFEST.sha256")
        mcuimg.parse(path)
        good.append(path)
    if not good:
        raise FlowError("releases/MANIFEST.sha256 lists no images")
    return good


def open_smp(port):
    return smp.SerialSMP(RawSerial(port))


def running_images(mgr):
    """Return (slot0, slot1_or_None) from `image list`."""
    slots = {s.slot: s for s in mgr.image_list()}
    if 0 not in slots:
        raise FlowError("`image list` reported no slot 0")
    return slots[0], slots.get(1)


def backup(ui, port, out_root):
    """Dump flash 0x0..0xFE000 to backups/<timestamp>/. A full dump can be restored with an SWS probe."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(out_root, stamp)
    os.makedirs(out)
    link = RawSerial(port)
    client = smp.SerialSMP(link)
    h = hashlib.sha256()
    ui.say(f"Reading flash 0x0-0x{FLASH_BACKUP_END:X} to {out}")
    try:
        with open(os.path.join(out, "flash.bin"), "wb") as f:
            for off in range(0, FLASH_BACKUP_END, READ_CHUNK):
                chunk = _retry(lambda: smp.flash_read(client, off, READ_CHUNK), what=f"read at 0x{off:X}")
                if len(chunk) != READ_CHUNK:
                    raise FlowError(f"short read at 0x{off:X}")
                f.write(chunk)
                h.update(chunk)
                if off % 0x10000 == 0:
                    ui.say(f"  0x{off:06X} / 0x{FLASH_BACKUP_END:X}")
    finally:
        link.close()
    meta = {"created": stamp, "range": [0, FLASH_BACKUP_END], "sha256": h.hexdigest()}
    with open(os.path.join(out, "flash.json"), "w") as f:
        json.dump(meta, f, indent=2)
    ui.say(f"Backup done. sha256 {meta['sha256']}")
    return out


def _retry(fn, what, attempts=3):
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except smp.SMPError as e:
            last = e
    raise FlowError(f"{what} failed {attempts} times: {last}")


def update(ui, repo, image_path, port=None, ports=device.find_ports):
    """Upload, trial-boot, verify and confirm a new app image. The old image stays one power cycle away."""
    image = mcuimg.parse(image_path)
    ui.say(f"Image {image.path}: {image.size} bytes, version {image.version}, sha256 {image.sha256[:16]}...")
    check_golden(repo)
    ui.say("Known-good release image verified.")

    port = port or device.wait_for_port(15, ports=ports)
    if not port:
        raise FlowError("no keyboard serial port found. Plug it in; if it is hung, run: crush80 recover")
    mgr = Mcumgr(port)
    mgr.echo()
    slot0, _ = running_images(mgr)
    if not slot0.confirmed:
        raise FlowError(
            f"the running image {slot0.hash[:12]} is an unconfirmed trial. Confirm it (crush80 confirm) "
            "or power-cycle to revert it, then run update again.")
    if slot0.hash == image.sha256:
        ui.say("This image is already running and confirmed. Nothing to do.")
        return
    old_hash = slot0.hash
    ui.say(f"Running: {old_hash[:12]} (confirmed). Uploading...")

    mgr.upload(image_path)
    _, slot1 = running_images(mgr)
    if slot1 is None or slot1.hash != image.sha256:
        raise FlowError("after upload, slot 1 does not hold the uploaded image. Nothing was changed; try again.")
    mgr.test(image.sha256)
    _, slot1 = running_images(mgr)
    if not slot1.pending:
        raise FlowError("the image was uploaded but is not marked for test boot. Nothing was changed.")

    ui.say("")
    ui.say("Uploaded and marked for ONE trial boot. Now:")
    ui.say("  1. Unplug the keyboard USB cable. 2. Wait 3 seconds. 3. Plug it back in.")
    ui.say("  If anything looks wrong afterwards: unplug and replug again. The previous image comes back.")
    new_port = device.wait_for_port(180, gone_first=True, ports=ports)
    if not new_port:
        raise FlowError(
            "no serial port after the replug. Unplug, wait 5 s, replug: the board reverts to the old image. "
            "Still dead? Run: crush80 recover")
    time.sleep(4)
    return _after_trial_boot(ui, new_port, image.sha256, old_hash)


def _after_trial_boot(ui, port, new_hash, old_hash):
    mgr = Mcumgr(port)
    try:
        mgr.echo()
        slot0, _ = running_images(mgr)
    except (McumgrError, FlowError) as e:
        raise FlowError(f"the board came up but does not answer mcumgr ({e}). Unplug and replug to revert, "
                        "then run: crush80 status") from e
    if slot0.hash == old_hash:
        raise FlowError("the board booted the OLD image: the new one failed to start and was reverted. "
                        "The keyboard is safe. Check the build before trying again.")
    if slot0.hash != new_hash:
        raise FlowError(f"running image {slot0.hash[:12]} is neither the old nor the new one. Run: crush80 status")
    ui.say("New image is running as a trial. Test the keyboard now (typing, Fn layer, USB serial).")
    if not ui.ask("Everything works and you want to make it permanent? [y/N]"):
        ui.say("Not confirmed. Unplug and replug to go back to the previous image.")
        return
    mgr.confirm(new_hash)
    slot0, _ = running_images(mgr)
    if not slot0.confirmed:
        raise FlowError("confirm was sent but the image is still unconfirmed. Run: crush80 status")
    ui.say("Confirmed. The new image is permanent.")


def confirm(ui, port):
    mgr = Mcumgr(port)
    slot0, _ = running_images(mgr)
    if slot0.confirmed:
        ui.say("Running image is already confirmed.")
        return
    mgr.confirm(slot0.hash)
    ui.say("Confirmed." if running_images(mgr)[0].confirmed else "Confirm did not take. Run: crush80 status")


def status(ui, port):
    mgr = Mcumgr(port)
    mgr.echo()
    for s in mgr.image_list():
        flags = [n for n, v in (("confirmed", s.confirmed), ("active", s.active), ("pending", s.pending)) if v]
        ui.say(f"slot {s.slot}: {s.hash[:16]}...  {' '.join(flags) or '-'}")


def recover(ui, repo, ports=device.find_ports):
    """Get a hung ZMK board into MCUboot serial recovery, then load the known-good image.

    A hung app answers SMP for about two seconds after USB enumerates, so the erase of the slot 0 header
    goes out the moment the port appears, before anything else.
    """
    golden = check_golden(repo)[0]
    ui.say(f"Known-good image: {os.path.basename(golden)}")
    ui.say("1. Unplug the keyboard.")
    ui.pause("2. Press Enter, then plug it in.")
    deadline = time.monotonic() + 60
    erased = False
    while time.monotonic() < deadline and not erased:
        found = ports()
        if len(found) != 1:
            time.sleep(0.05)
            continue
        try:
            link = RawSerial(found[0])
        except OSError:
            time.sleep(0.05)
            continue
        try:
            client = smp.SerialSMP(link)
            smp.flash_erase(client, SLOT0, 0x1000)
            erased = True
        except smp.SMPError:
            pass
        finally:
            link.close()
    if not erased:
        raise FlowError("could not reach the board in 60 s. Unplug for 10 s so it fully powers down, and retry.")
    ui.say("Slot 0 header erased. Unplug, wait 3 s, replug: the bootloader then waits for an upload.")
    port = device.wait_for_port(180, gone_first=True, ports=ports)
    if not port:
        raise FlowError("no serial port in recovery mode. Unplug for 10 s and replug.")
    time.sleep(3)
    mgr = Mcumgr(port)
    mgr.echo()
    ui.say("In recovery mode. Uploading the known-good image (no time pressure, no app is running)...")
    mgr.upload(golden)
    ui.say("Done. Unplug, wait 3 s, replug: the keyboard boots the known-good firmware.")


def has_backup(backups_root):
    if not os.path.isdir(backups_root):
        return False
    return any(os.path.exists(os.path.join(backups_root, d, "flash.json")) for d in os.listdir(backups_root))


def stock_restore(ui, repo, stock_path, port, commit):
    """Stage a stock firmware image in slot 1, verify it by read-back, optionally commit it over 0x0.

    The commit step erases the bootloader. It is the one operation in this project with a window in
    which a power loss leaves no bootable image. It runs only after a full flash backup exists.
    """
    if commit and not has_backup(os.path.join(repo, "backups")):
        raise FlowError("no flash backup in backups/. Run `./crush80 backup` first.")
    with open(stock_path, "rb") as f:
        data = f.read()
    if len(data) > 0x70000 or len(data) < 0x1000:
        raise FlowError("stock image size is outside 4 KB..448 KB")
    if data[0x20:0x24] != b"KNLT":
        raise FlowError("stock image has no KNLT boot marker at 0x20: not a Telink firmware image")
    digest = hashlib.sha256(data).hexdigest()
    ui.say(f"Stock image {stock_path}: {len(data)} bytes, sha256 {digest[:16]}...")

    link = RawSerial(port)
    client = smp.SerialSMP(link)
    try:
        sectors = (len(data) + 0xFFF) // 0x1000
        ui.say(f"Staging at 0x{STOCK_STAGING:X} ({sectors} sectors). The running firmware is not touched yet.")
        for i in range(sectors):
            _retry(lambda i=i: smp.flash_erase(client, STOCK_STAGING + i * 0x1000, 0x1000), "erase")
        for off in range(0, len(data), READ_CHUNK):
            chunk = data[off:off + READ_CHUNK]
            _retry(lambda off=off, chunk=chunk: smp.flash_write(client, STOCK_STAGING + off, chunk), "write")
        readback = hashlib.sha256()
        for off in range(0, len(data), READ_CHUNK):
            want = min(READ_CHUNK, len(data) - off)
            got = _retry(lambda off=off, want=want: smp.flash_read(client, STOCK_STAGING + off, want), "read")
            readback.update(got)
        if readback.hexdigest() != digest:
            raise FlowError("read-back of the staged image does not match the file. Nothing was committed.")
        ui.say("Staged image verified byte for byte.")
        if not commit:
            ui.say("Dry run: not committed. Re-run with --commit to replace the firmware.")
            return
        ui.say("")
        ui.say("COMMIT replaces the bootloader and app with the stock image. It takes a few seconds.")
        ui.say("Do not unplug, do not let the computer sleep, until stock firmware enumerates.")
        if not ui.ask("A full backup exists (crush80 backup) and USB power is stable. Commit? [y/N]"):
            ui.say("Cancelled. Staged image left in slot 1; the running firmware is intact.")
            return
        client.request(smp.OP_WRITE, smp.GROUP_FLASH_MGMT, smp.FLASH_COMMIT,
                       {"stg": STOCK_STAGING, "len": len(data)}, timeout=10.0)
    finally:
        link.close()
    ui.say("Commit accepted; the board resets itself. Waiting for stock firmware (320f:5055)...")
