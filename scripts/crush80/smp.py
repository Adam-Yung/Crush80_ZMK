"""SMP over serial (MCUmgr), minimal: enough to drive the custom flash_mgmt group (id 64).

Serial framing: each frame is base64( len(2, BE) + smp_message + crc16(smp_message) ), split into
lines of at most 124 base64 chars; the first line starts with 0x06 0x09, the rest with 0x04 0x14.
"""

import base64
import struct
import time

from . import cbor

OP_READ, OP_WRITE = 0, 2
GROUP_FLASH_MGMT = 64
FLASH_ERASE, FLASH_WRITE, FLASH_READ, FLASH_COMMIT = 0, 1, 2, 3

_LINE_B64 = 124
_START, _CONT = b"\x06\x09", b"\x04\x14"


class SMPError(Exception):
    pass


def crc16_ccitt(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_message(op, group, cmd, seq, payload):
    body = cbor.dumps(payload)
    return struct.pack(">BBHHBB", op, 0, len(body), group, seq, cmd) + body


def encode_frame(message):
    packet = struct.pack(">H", len(message) + 2) + message + struct.pack(">H", crc16_ccitt(message))
    b64 = base64.b64encode(packet)
    lines = []
    for i in range(0, len(b64), _LINE_B64):
        lines.append((_START if i == 0 else _CONT) + b64[i:i + _LINE_B64] + b"\n")
    return b"".join(lines)


def parse_message(message):
    """Return (seq, payload) from a raw SMP message."""
    if len(message) < 8:
        raise SMPError("short SMP message")
    length = struct.unpack(">H", message[2:4])[0]
    seq = message[6]
    return seq, cbor.loads(message[8:8 + length])


class FrameParser:
    """Pulls complete SMP responses out of a byte stream that may also carry console log text."""

    def __init__(self):
        self._buf = b""

    def feed(self, data):
        """Return [(seq, payload)] for each complete, CRC-valid response now available."""
        self._buf += data
        out = []
        while True:
            start = self._buf.find(_START)
            if start < 0:
                self._buf = self._buf[-1:]  # a lone 0x06 may be the first half of a start marker
                break
            result, used = self._frame_at(start)
            if used == 0:  # incomplete: keep the bytes and wait for more
                self._buf = self._buf[start:]
                break
            self._buf = self._buf[used:]
            if result is not None:
                out.append(result)
        return out

    def _frame_at(self, start):
        """Try to decode one frame beginning at `start`. Returns (result_or_None, bytes_consumed)."""
        pos, b64 = start, b""
        while True:
            end = self._buf.find(b"\n", pos)
            if end < 0:
                return None, 0
            b64 += self._buf[pos + 2:end]
            pos = end + 1
            try:
                packet = base64.b64decode(b64, validate=True)
            except ValueError:
                return None, pos  # garbage between a stray marker and its newline: drop it
            if len(packet) >= 4:
                total = struct.unpack(">H", packet[:2])[0]
                if len(packet) - 2 >= total:
                    msg = packet[2:total]
                    crc = struct.unpack(">H", packet[total:total + 2])[0]
                    if crc != crc16_ccitt(msg):
                        return None, pos
                    try:
                        return parse_message(msg), pos
                    except (SMPError, ValueError):
                        return None, pos
            if len(self._buf) - pos < 2:
                return None, 0
            if not self._buf.startswith(_CONT, pos):
                return None, pos


class SerialSMP:
    """Request/response client. `port` needs write(bytes), flush() and read(n) with a short timeout."""

    def __init__(self, port, clock=time.monotonic):
        self._port = port
        self._parser = FrameParser()
        self._seq = 0
        self._clock = clock

    def request(self, op, group, cmd, payload, timeout=5.0):
        """Send one request, return the decoded response map, or raise SMPError on timeout."""
        self._seq = (self._seq + 1) & 0xFF
        seq = self._seq
        self._port.write(encode_frame(build_message(op, group, cmd, seq, payload)))
        self._port.flush()
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            for got_seq, body in self._parser.feed(self._port.read(4096)):
                if got_seq == seq:
                    return body
        raise SMPError(f"no response to group {group} cmd {cmd} within {timeout}s")

    def flash(self, cmd, payload, timeout=5.0):
        op = OP_READ if cmd == FLASH_READ else OP_WRITE
        body = self.request(op, GROUP_FLASH_MGMT, cmd, payload, timeout)
        rc = body.get("rc", 0)
        if rc != 0:
            raise SMPError(f"flash_mgmt cmd {cmd} failed: rc={rc}")
        return body


def flash_read(smp, offset, length):
    return smp.flash(FLASH_READ, {"off": offset, "len": length})["data"]


def flash_erase(smp, offset, length):
    smp.flash(FLASH_ERASE, {"off": offset, "len": length}, timeout=10.0)


def flash_write(smp, offset, data):
    smp.flash(FLASH_WRITE, {"off": offset, "data": data})
