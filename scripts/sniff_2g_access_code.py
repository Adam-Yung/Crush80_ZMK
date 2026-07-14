#!/usr/bin/env python3
"""
Wobkey Crush 80 — 2.4GHz Access Code Sniffer
Raspberry Pi 3B + nRF24L01+ module

Wiring (RPi 3B GPIO header):
  nRF24L01+  →  RPi GPIO
  VCC        →  Pin 17 (3.3V)   ← IMPORTANT: 3.3V NOT 5V
  GND        →  Pin 20 (GND)
  CE         →  Pin 22 (GPIO 25)
  CSN        →  Pin 24 (GPIO 8 / CE0)
  SCK        →  Pin 23 (GPIO 11 / SCLK)
  MOSI       →  Pin 19 (GPIO 10 / MOSI)
  MISO       →  Pin 21 (GPIO 9 / MISO)
  IRQ        →  not connected (optional)

Install dependencies:
  sudo apt-get install python3-pip python3-dev
  pip3 install pyrf24

How to use:
  1. Plug Wobkey 2.4G dongle into PC USB
  2. Switch keyboard to 2.4G mode (press the 2.4G mode key)
  3. Run: python3 crush80_sniffer.py
  4. Press several keys on the keyboard (spacebar, Enter, etc.)
  5. The script will print the access code when it finds consistent packets

What the output means:
  ACCESS CODE: 0x12345678  <-- this 4-byte value goes into crush80_tpll.c
  CHANNELS:    [17, 35, 72, 90]  <-- RF channels used for hopping

Why this works:
  Telink TPLL (the Crush 80's 2.4G protocol) uses the same physical layer
  as nRF24L01+ Enhanced ShockBurst. The "address" in nRF24 is the "access code"
  in TPLL — both are a sync word that identifies the transmitter.

  In promiscuous mode, the nRF24 treats the first 4 bytes after the preamble
  as the address. By scanning all channels and looking for consistent patterns
  that appear when we press keys, we can find the access code.
"""

import time
import struct
import sys
from collections import Counter

try:
    from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS
except ImportError:
    print("Install pyrf24: pip3 install pyrf24")
    print("Or: sudo pip3 install pyrf24")
    sys.exit(1)

# ============================================================
# nRF24L01+ configuration
# ============================================================

CE_PIN  = 25   # GPIO 25 = BCM pin 25 = physical pin 22
CSN_PIN = 0    # SPI device 0 (CS0 = GPIO 8)

# Channels to scan — Telink TPLL HID keyboards typically use
# a small set of channels, often in the 0-80 range.
# Common sets seen in Telink keyboards: [17, 35, 72, 90] or [10, 30, 50, 70]
SCAN_CHANNELS = list(range(0, 84, 1))  # scan all 84 channels

# Promiscuous-mode address — the nRF24 can't truly sniff arbitrary addresses,
# but by setting an all-0xAA or all-0x55 address, it will capture any packet
# that has enough matching bits after the preamble. This is the MouseJack technique.
PROMISCUOUS_ADDR = [0xAA, 0xAA, 0xAA, 0xAA, 0xAA]

# ============================================================
# TPLL packet format (Telink Primary Link Layer, 1 Mbps)
#
# [preamble 1B] [access code 4B] [PCF 9b] [payload Nb] [CRC 2B]
#
# PCF (Packet Control Field):
#   bits [8:3] = payload length (6 bits, 0-32)
#   bit  [2]   = No-ACK flag
#   bits [1:0] = PID (2-bit rolling counter, 0-3)
#
# HID report payload (keyboard):
#   [report_id 1B] [modifier 1B] [reserved 1B] [keys 6B] = 9 bytes
# ============================================================

def setup_radio():
    """Initialize nRF24L01+ in promiscuous/sniffing mode."""
    radio = RF24(CE_PIN, CSN_PIN)

    if not radio.begin():
        print("ERROR: nRF24L01+ not found. Check wiring.")
        print("  VCC must be 3.3V (not 5V)")
        print("  CE  → GPIO 25 (pin 22)")
        print("  CSN → GPIO 8  (pin 24)")
        sys.exit(1)

    radio.setPALevel(RF24_PA_LOW)
    radio.setDataRate(RF24_1MBPS)          # Telink TPLL uses 1 Mbps
    radio.setPayloadSize(32)               # max payload
    radio.setAutoAck(False)               # no auto-ack in sniff mode
    radio.disableCRC()                     # disable CRC check (we want raw data)
    radio.setAddressWidth(5)              # 5-byte address width

    # Open pipe 0 with promiscuous address
    radio.openReadingPipe(0, bytes(PROMISCUOUS_ADDR))

    print(f"nRF24L01+ initialized. Chip model: {'nRF24L01+' if radio.isPVariant() else 'nRF24L01'}")
    return radio


def scan_channel(radio, channel, duration_ms=50):
    """
    Listen on one channel for the given duration.
    Returns list of raw payloads received.
    """
    radio.setChannel(channel)
    radio.startListening()
    time.sleep(duration_ms / 1000.0)
    radio.stopListening()

    packets = []
    while radio.available():
        payload = radio.read(32)
        packets.append(bytes(payload))

    return packets


def extract_address_candidate(payload):
    """
    In promiscuous mode with address 0xAAAAAA..., the first 4 bytes after
    the preamble are captured. These are the potential access code bytes.
    
    TPLL packet structure after our 5-byte "address" filter:
    Bytes 0-3: part of actual TPLL access code
    Byte  4:   PCF high byte (contains payload length)
    ...

    We look for packets where byte 4 (PCF) has a plausible payload length:
    HID keyboard report = 9 bytes, so PCF[8:3] = 9, giving PCF = 0x48 or nearby.
    """
    if len(payload) < 6:
        return None

    # PCF byte — check if payload length field is 8-12 (HID keyboard size)
    pcf_hi = payload[4]
    length = (pcf_hi >> 2) & 0x3F  # bits [8:3] of 9-bit PCF, upper 6 bits in byte 4

    if 8 <= length <= 12:
        # This looks like a HID keyboard packet!
        # Bytes 0-3 are our candidate access code
        return struct.unpack('<I', payload[0:4])[0]

    return None


def find_active_channels(radio, num_passes=3):
    """
    Scan all channels multiple times to find which ones have activity
    from the keyboard. Returns channels with packet counts > threshold.
    """
    print(f"\nScanning {len(SCAN_CHANNELS)} channels for keyboard activity...")
    print(">>> PRESS KEYS ON THE KEYBOARD NOW <<<\n")

    channel_hits = Counter()

    for pass_num in range(num_passes):
        sys.stdout.write(f"\rPass {pass_num+1}/{num_passes}: scanning...")
        sys.stdout.flush()

        for ch in SCAN_CHANNELS:
            packets = scan_channel(radio, ch, duration_ms=30)
            if packets:
                channel_hits[ch] += len(packets)

    print()
    active = [(ch, cnt) for ch, cnt in channel_hits.items() if cnt >= 2]
    active.sort(key=lambda x: -x[1])
    return active


def sniff_access_code(radio, channels, duration_sec=10):
    """
    On the known active channels, collect packets and look for a consistent
    access code pattern. The real access code will appear in most packets.
    """
    print(f"\nListening on channels {[c for c,_ in channels]} for {duration_sec}s...")
    print(">>> KEEP PRESSING KEYS ON THE KEYBOARD <<<\n")

    address_candidates = Counter()
    channel_set = [ch for ch, _ in channels]
    deadline = time.time() + duration_sec

    while time.time() < deadline:
        for ch in channel_set:
            packets = scan_channel(radio, ch, duration_ms=20)
            for pkt in packets:
                addr = extract_address_candidate(pkt)
                if addr is not None:
                    address_candidates[addr] += 1
                    sys.stdout.write(f"\r  Candidate 0x{addr:08X}: {address_candidates[addr]} hits")
                    sys.stdout.flush()

    print()
    return address_candidates


def main():
    print("=" * 60)
    print("Wobkey Crush 80 — 2.4G Access Code Sniffer")
    print("=" * 60)
    print()
    print("Before running:")
    print("  1. Plug the Wobkey 2.4G dongle into a USB port")
    print("  2. Switch the keyboard to 2.4G mode")
    print("     (press the 2.4G mode key, or Fn+Tab depending on layout)")
    print("  3. Wait for the keyboard LED to confirm 2.4G connection")
    print()
    input("Press Enter when the keyboard is in 2.4G mode and connected...")

    radio = setup_radio()

    # Phase 1: find active channels
    active_channels = find_active_channels(radio, num_passes=5)

    if not active_channels:
        print("\nNo keyboard activity detected on any channel!")
        print("Check:")
        print("  - Keyboard is in 2.4G mode (not BT or USB)")
        print("  - Dongle is plugged in and paired")
        print("  - nRF24L01+ wiring (VCC=3.3V, not 5V)")
        return

    print(f"\nActive channels found:")
    for ch, cnt in active_channels[:8]:
        print(f"  Channel {ch:3d} ({2400+ch} MHz): {cnt} packets")

    # Phase 2: collect access code candidates
    top_channels = active_channels[:4]  # focus on most active
    candidates = sniff_access_code(radio, top_channels, duration_sec=15)

    if not candidates:
        print("\nNo HID-shaped packets captured. Try pressing more keys.")
        return

    # The real access code is the one that appears most consistently
    print("\n" + "=" * 60)
    print("TOP ACCESS CODE CANDIDATES:")
    print("=" * 60)
    for addr, count in candidates.most_common(5):
        print(f"  0x{addr:08X}  ({count} occurrences)")

    best_addr, best_count = candidates.most_common(1)[0]
    channel_list = [ch for ch, _ in top_channels]

    print()
    print("=" * 60)
    print("RESULT — add these to crush80_tpll.c:")
    print("=" * 60)
    print(f"  ACCESS_CODE  = 0x{best_addr:08X}")
    print(f"  CHANNELS     = {channel_list}")
    print()
    print("If the top candidate appears much more than others, it's correct.")
    print("If there's a tie, run the scan again with the keyboard actively typing.")


if __name__ == "__main__":
    main()
