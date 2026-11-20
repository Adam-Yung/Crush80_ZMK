"""Raw 115200 8N1 serial port on macOS/Linux with the standard library only (no pyserial)."""

import fcntl
import os
import select
import struct
import termios


class RawSerial:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[1] = attrs[3] = 0                       # iflag, oflag, lflag: raw
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # cflag
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 0, 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        # The firmware ignores the port until the host raises DTR.
        fcntl.ioctl(self.fd, termios.TIOCMBIS, struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))

    def write(self, data):
        view = memoryview(data)
        while view:
            _, writable, _ = select.select([], [self.fd], [], 2.0)
            if not writable:
                raise OSError("serial write stalled for 2 s")
            view = view[os.write(self.fd, view):]

    def flush(self):
        termios.tcdrain(self.fd)

    def read(self, n, timeout=0.05):
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return b""
        try:
            return os.read(self.fd, n)
        except BlockingIOError:
            return b""

    def close(self):
        os.close(self.fd)
