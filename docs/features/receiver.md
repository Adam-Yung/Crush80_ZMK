# Wireless USB receiver

The bundled Wobkey receiver uses the proprietary 2.4 GHz link implemented by
the factory keyboard firmware. On an RGB-equipped stock board the dongle
typically enumerates as USB `320f:5088`.
This ZMK port currently supports USB-C and Bluetooth LE. The historical
2.4 GHz configuration contained placeholder constants and lacked a pairing
or report transport implementation.
[Wobkey pairing instructions](https://wiki.wobkey.com/en/products/crush-80/quick-start)
· [USB interface notes](https://github.com/Desz01ate/Wobkey_Crush_80_Patched_Firmware/blob/main/INVESTIGATION.md)

## Use USB while keeping the keyboard wireless

A separate BLE-to-USB HID receiver can pair to the keyboard as a Bluetooth
host and appear to the computer as an ordinary USB keyboard. Bluetooth HID
Remapper is a candidate on its supported nRF52840 boards. The project
describes it as experimental, and pairing and wake/reconnect with this Crush
80 build still need hardware verification.
[Bluetooth HID Remapper setup](https://github.com/jfedor2/hid-remapper/blob/master/BLUETOOTH.md)

For a trial, use an unused ZMK Bluetooth profile, put the receiver into pairing
mode and pair the keyboard to it. Unplug the keyboard's own USB cable or select
Bluetooth output before testing. Check normal typing, modifiers, key release
after a disconnect and wake/reconnect with the receiver moved to another USB
host.

## Verify the factory hardware before a stock-protocol port

On a keyboard still running Wobkey firmware, verify that the receiver pairs and
types normally. Record the keyboard model and PCB revision, receiver USB ID
and the board or chip markings if accessible. This distinguishes receiver
revisions before selecting an implementation. A stock-compatible port needs
evidence for pairing, reconnect and HID report framing and a test that the B91
can switch cleanly between the factory radio path and Bluetooth LE.
