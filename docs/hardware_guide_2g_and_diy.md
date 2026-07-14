# 2.4 GHz Sniffing + LG Flex Smart Control: Hardware Guide

## Part 1: What to Buy (Under $50 Budget)

You already have: Arduino, breadboard, Raspberry Pi 3B, IR LED from Arduino kit.  
You need: nRF24L01+ modules.

### Recommended Purchase

**nRF24L01+PA+LNA modules with external SMA antenna — pack of 4**  
Search Amazon for: "nRF24L01 PA LNA SMA antenna 4 pack"  
Target price: $10–14 for a pack of 4  
Example listing: UCCKEYI 4-piece NRF24L01+ PA LNA (~$12)

**Why the PA+LNA version (not the basic $2 ones):**
- The basic nRF24L01+ modules have a documented power noise problem on Raspberry Pi's 3.3V rail, causing random failures mid-scan. The PA+LNA version has onboard voltage regulation that fixes this.
- The external antenna gives you 5–10x better receive sensitivity — critical for sniffing an unknown signal you're not currently tuned to.
- At ~$3 each in a 4-pack, the price difference is negligible.

**Do NOT buy**: the tiny 8-pin PCB-mount nRF24L01+ without an antenna — those will give you intermittent failures that are hard to debug.

**Optional but recommended ($8–12):** An ESP32-WROOM-32 development board  
This gives you: WiFi + Bluetooth for LG TV control over the network, IR blaster projects, and future wireless builds. The Arduino can do IR but the ESP32 is cleaner for combined WiFi + IR work. Not needed for the keyboard sniffing — the RPi handles that.

**Total budget used:** $12–24. You stay well under $50.

---

## Part 2: Sniffing the Crush 80 2.4 GHz Access Code

### How It Works

The Wobkey Crush 80 uses Telink TPLL — a protocol that is physically identical to the nRF24L01+ Enhanced ShockBurst protocol. The nRF24L01+ can receive TPLL packets without any firmware modification. The keyboard's "access code" is the 4-byte sync word embedded in every transmitted packet. Once you capture a packet, you have the code.

### Hardware Setup: nRF24L01+ → Raspberry Pi 3B

The RPi 3B has hardware SPI on GPIO pins 8–11. Wire as follows (no breadboard needed — just 7 Dupont female-to-female jumper wires):

```
nRF24L01+ Pin     →  RPi 3B Pin (BCM numbering)
─────────────────────────────────────────────────
VCC (3.3V)        →  Pin 17  (3.3V power)
GND               →  Pin 20  (Ground)
CE                →  Pin 22  (GPIO 25)
CSN               →  Pin 24  (GPIO 8 / SPI0_CE0)
SCK               →  Pin 23  (GPIO 11 / SPI0_CLK)
MOSI              →  Pin 19  (GPIO 10 / SPI0_MOSI)
MISO              →  Pin 21  (GPIO 9  / SPI0_MISO)
IRQ               →  (leave unconnected)
```

The nRF24L01+ module has 2 rows of 4 pins each. Pin 1 is GND (marked with a square pad or a notch). Looking at the module from the antenna side with pins facing down:

```
  [ antenna ]
  [  module  ]
  GND  VCC
  CE   CSN
  SCK  MOSI
  MISO IRQ
```

**Important:** Use the RPi's 3.3V pin (Pin 17), never 5V. The nRF24L01+ is a 3.3V device.

**Stability tip:** Solder or clip a 10µF electrolytic capacitor between VCC and GND on the nRF24L01+ module. This filters power rail noise and prevents dropouts. Not strictly required with the PA+LNA version, but it takes 30 seconds and eliminates a whole category of debugging.

### Software Setup on Raspberry Pi

```bash
# 1. Enable SPI on the RPi (required once)
sudo raspi-config
# → Interface Options → SPI → Enable → Finish → reboot

# 2. Install pyrf24 library
sudo apt-get update
sudo apt-get install python3-pip
pip3 install pyrf24

# 3. Copy the sniffer script to the RPi
# Option A: SSH copy from your main machine
scp /mnt/c/Users/adyung/Documents/Adam/Wobkey_Crush_80_Patched_Firmware/scripts/sniff_2g_access_code.py pi@raspberrypi.local:~/

# Option B: Create it directly on the RPi
# (the script is at scripts/sniff_2g_access_code.py in the repo)
```

### Running the Sniff

```bash
# On the Raspberry Pi:
cd ~
python3 sniff_2g_access_code.py
```

1. When prompted, plug in the Wobkey 2.4G dongle and switch the keyboard to 2.4G mode
2. The script scans all 84 channels, identifies which ones are active
3. It then focuses on those channels and captures packets while you type
4. After ~20 seconds of key pressing, it prints:

```
ACCESS CODE = 0xXXXXXXXX
CHANNELS    = [17, 35, 72, ...]
```

### What To Do With the Result

Once you have the access code and channel list, open [`zmk/drivers/led/crush80_rgb.c`](../zmk/drivers/led/crush80_rgb.c) — a separate TPLL driver file will be created for 2.4G, and those two values go in as constants:

```c
// In crush80_tpll.c (to be written after sniffing):
#define TPLL_ACCESS_CODE  0xXXXXXXXX  // from sniffer output
#define TPLL_CHANNELS     {17, 35, 72, 90}  // from sniffer output
```

The RF physical layer functions (`rf_set_chn`, `rf_access_code_comm`) are open-source Apache 2.0 in the Telink platform SDK — no blob needed for 2.4G.

---

## Part 3: Controlling Your LG OLED Flex 42 Without the Remote

### The Full Picture: Three Ways to Control the Flex

| Method | Controls | Hardware needed | Difficulty |
|---|---|---|---|
| **IR (NEC protocol)** | Power, volume, navigation, inputs, curvature | IR LED (you have it) + Arduino | Easy |
| **WebOS API (WiFi)** | Everything IR can do + picture settings, app launch, input by name, current input query | RPi or ESP32 on same WiFi | Medium |
| **Capture + replay** | Any button your original remote has, including curvature at exact increments | Arduino + IR LED + IR receiver module (already have?) | Easy once set up |

**The best strategy**: use all three together.

- **IR** for instant physical buttons (power, volume) — zero latency, works even when TV app crashes
- **WebOS WiFi API** for smart macros ("gaming mode": set input + picture preset + curvature 50% all in one command)
- **IR capture** for the curvature button specifically — since there's no named WebOS button for it, capture the raw IR code from your remote and replay it

### Part 3A: IR Control with Arduino + IR LED

You already have the IR LED from your Arduino kit. Check if you also have an **IR receiver module** (a small black 3-pin component, usually TSOP4838 or similar). If you do, you can capture your remote's codes directly. If not, they're $2 for a pack of 5.

#### Capturing the Curvature IR Code

The LG Flex curvature button sends an NEC IR code. The standard LG codes use `0x20DFxxxx` format. The curvature button's specific code is **not publicly documented** because it's model-specific to the Flex — you need to capture it from your own remote.

```cpp
// Arduino sketch: capture_remote.ino
// Upload this to Arduino, aim your LG Flex remote at the IR receiver, press buttons
// Watch Serial Monitor for the hex codes

#include <IRremote.h>

const int IR_RECEIVE_PIN = 11;

void setup() {
    Serial.begin(9600);
    IrReceiver.begin(IR_RECEIVE_PIN, ENABLE_LED_FEEDBACK);
    Serial.println("Point remote at sensor and press buttons...");
}

void loop() {
    if (IrReceiver.decode()) {
        Serial.print("Protocol: ");
        Serial.print(IrReceiver.decodedIRData.protocol == NEC ? "NEC" : "OTHER");
        Serial.print("  Code: 0x");
        Serial.println(IrReceiver.decodedIRData.decodedRawData, HEX);
        IrReceiver.resume();
    }
}
```

Wire: IR receiver OUT → Arduino pin 11, VCC → 5V, GND → GND.  
Install library: Arduino IDE → Library Manager → "IRremote" by shirriff/z3t0.

Press each button on your LG Flex remote and record the hex codes. The curvature + and curvature - buttons each have their own code. Write them down.

#### Sending IR Commands from Arduino

```cpp
// Arduino sketch: lg_remote.ino
// Sends LG NEC IR codes via IR LED

#include <IRremote.h>

const int IR_SEND_PIN = 3;  // IR LED → 100Ω resistor → Arduino pin 3

// Standard LG NEC codes (confirmed working on LG OLED series)
#define LG_POWER      0x20DF10EF
#define LG_VOL_UP     0x20DF40BF
#define LG_VOL_DOWN   0x20DFC03F
#define LG_MUTE       0x20DF906F
#define LG_HOME       0x20DF3D24  // confirmed for recent models
#define LG_SETTINGS   0x20DFC23D
#define LG_OK         0x20DF22DD
#define LG_UP         0x20DF02FD
#define LG_DOWN       0x20DF827D
#define LG_LEFT       0x20DFE01F
#define LG_RIGHT      0x20DF609F
#define LG_BACK       0x20DF14EB

// FILL IN from your capture session:
#define LG_CURVE_PLUS   0x00000000   // TODO: capture from your remote
#define LG_CURVE_MINUS  0x00000000   // TODO: capture from your remote

IRsend irsend;

void sendLG(uint32_t code) {
    irsend.sendNEC(code, 32);
    delay(100);
}

void setup() {
    Serial.begin(9600);
    Serial.println("LG Flex IR controller ready.");
    Serial.println("Commands: p=power, +=vol up, -=vol down, c=curve+, v=curve-");
}

void loop() {
    if (Serial.available()) {
        char cmd = Serial.read();
        switch(cmd) {
            case 'p': sendLG(LG_POWER);       Serial.println("Power"); break;
            case '+': sendLG(LG_VOL_UP);       Serial.println("Vol+");  break;
            case '-': sendLG(LG_VOL_DOWN);     Serial.println("Vol-");  break;
            case 'c': sendLG(LG_CURVE_PLUS);   Serial.println("Curve+"); break;
            case 'v': sendLG(LG_CURVE_MINUS);  Serial.println("Curve-"); break;
            case 'h': sendLG(LG_HOME);         Serial.println("Home");  break;
        }
    }
}
```

Wire: IR LED anode → 100Ω resistor → Arduino pin 3. IR LED cathode → GND.  
The IR LED from your kit is the clear/dark plastic one that looks like a normal LED.

### Part 3B: LG WebOS API from Raspberry Pi (WiFi)

The LG Flex 42 runs WebOS 22 and exposes a WebSocket API on your local network. This is the most powerful method — you can query TV state, launch apps, and send any button press, all from a script.

```bash
# On Raspberry Pi:
pip3 install aiowebostv

# Save this as lg_control.py on your RPi:
```

```python
#!/usr/bin/env python3
"""
LG OLED Flex 42 — WebOS controller
Sends commands over local WiFi — no internet, no cloud required.

First run: the TV will ask "Allow external access?" on screen → press Allow.
The client key is saved to lg_key.json for future connections.
"""

import asyncio
import json
import os
from aiowebostv import WebOsClient

TV_IP = "192.168.X.X"   # ← replace with your TV's local IP address
                         #   Find it: LG TV → Settings → General → About → Network

KEY_FILE = "lg_key.json"

async def get_client():
    client_key = None
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            client_key = json.load(f).get("client_key")

    client = WebOsClient(TV_IP, client_key=client_key)
    await client.connect()

    # Save key for future connections
    with open(KEY_FILE, "w") as f:
        json.dump({"client_key": client.client_key}, f)

    return client

async def gaming_mode():
    """One-command gaming setup: HDMI 2 + Game Optimizer + 50% curve"""
    client = await get_client()

    # Switch to HDMI 2 (your gaming PC/console)
    inputs = await client.get_inputs()
    hdmi2 = next((i for i in inputs if "HDMI 2" in i.get("label", "")), None)
    if hdmi2:
        await client.set_input(hdmi2["id"])
        print("Switched to HDMI 2")

    # Set picture mode to Game Optimizer
    await client.set_picture_settings({"pictureMode": "game"})
    print("Game Optimizer enabled")

    # Navigate to curvature via menu (since there's no direct API for it)
    # This is the workaround: send the curvature button code via IR or send
    # the curve preset button if your remote has it mapped
    # Alternatively: send button presses to navigate the menu
    await client.button("HOME")
    await asyncio.sleep(0.5)
    print("Use sendButton calls below to navigate to curvature if needed")

    await client.disconnect()

async def movie_mode():
    """Movie setup: OLED Cinema + flat screen + low brightness"""
    client = await get_client()
    await client.set_picture_settings({
        "pictureMode": "cinema",
        "brightness": 50,
        "oledLight": 60,
    })
    print("Cinema mode set, brightness reduced")
    await client.disconnect()

async def get_tv_info():
    """Print current TV state"""
    client = await get_client()
    info = await client.get_system_info()
    power = await client.get_power_state()
    picture = await client.get_picture_settings()
    volume = await client.get_volume()

    print(f"Model: {info.get('modelName', 'unknown')}")
    print(f"Power: {power.get('state', 'unknown')}")
    print(f"Volume: {volume}")
    print(f"Picture mode: {picture.get('pictureMode', 'unknown')}")
    print(f"Brightness: {picture.get('brightness', 'unknown')}")
    print(f"OLED Light: {picture.get('oledLight', 'unknown')}")

    await client.disconnect()

async def send_button(btn):
    """Send any remote button by name"""
    client = await get_client()
    await client.button(btn)
    await client.disconnect()

async def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"

    commands = {
        "info":    get_tv_info,
        "gaming":  gaming_mode,
        "movie":   movie_mode,
        "home":    lambda: send_button("HOME"),
        "back":    lambda: send_button("BACK"),
        "up":      lambda: send_button("UP"),
        "down":    lambda: send_button("DOWN"),
        "ok":      lambda: send_button("ENTER"),
        "volup":   lambda: send_button("VOLUMEUP"),
        "voldown": lambda: send_button("VOLUMEDOWN"),
    }

    fn = commands.get(cmd)
    if fn:
        await fn()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands.keys())}")

asyncio.run(main())
```

**Finding your TV's IP address:**  
LG TV → Settings → General → About This TV → Network → IP Address  
Or check your router's connected devices page.

**Usage:**
```bash
python3 lg_control.py info       # show TV state
python3 lg_control.py gaming     # one-command gaming setup
python3 lg_control.py movie      # cinema mode
python3 lg_control.py volup      # volume up
```

**On the curvature specifically:** WebOS has no named button for curvature in the standard API. The most reliable automation is the IR approach above (capture the curvature button's code, replay it with Arduino). You can chain both: the WebOS API sets the picture mode over WiFi, then the Arduino fires the IR code for curvature adjustment. Together they give you full one-button macros.

---

## Part 4: DIY Projects With This Hardware

You now have: nRF24L01+ modules, Arduino, Raspberry Pi 3B, IR LED.  
These are some of the most capable tools for physical computing projects.

---

### Project 1: One-Button Gaming Command Center

**Hardware:** Arduino (already have) + IR LED (already have) + a few tactile buttons  
**What it does:** A small box with 4 physical buttons. Press "Gaming": TV switches input, sets Game Optimizer, fires curvature IR code. Press "Movie": cinema mode, dims OLED panel. Press "Sleep": dims TV to minimum, starts sleep timer.  
**Principle:** Arduino has a USB serial connection to the RPi. RPi runs the WebOS script. Arduino reads buttons and fires both IR commands (direct) and serial commands to trigger WebOS API calls.  
**Build time:** 2 hours once you have the IR code captured.

---

### Project 2: Wireless Sensor Mesh (nRF24L01+)

**Hardware:** nRF24L01+ modules (you now have 4), Arduino, RPi 3B  
**What it does:** Place battery-powered Arduino nodes around your home. Each has an nRF24L01+ and a sensor (temperature, humidity, motion, door contact). They transmit readings to a central RPi hub. The RPi logs data and can trigger automations.  
**Range:** ~50m indoors with the PA+LNA module.  
**Power:** A single AA battery powers an Arduino Nano + nRF24 sensor node for 6–12 months in sleep mode.  
**Libraries:** RF24Network (Arduino), MySensors framework (turns RPi into a gateway automatically).

---

### Project 3: Universal IR Remote Cloner

**Hardware:** IR LED + IR receiver (the $2 module) + Arduino  
**What it does:** Point any remote at the receiver. It captures every button's IR code and saves it to a JSON file. Then you can replay any button from a web interface (served from the RPi) or trigger macros. Works for: any TV, AV receiver, AC unit, streaming devices, smart lights with IR.  
**LG Flex application:** Once you've captured the curvature codes, you could also capture your AC remote, Nvidia Shield remote, etc., and build a single-remote-to-rule-them-all.  
**Build time:** Afternoon project. IRDB and IRSCDB have code databases for most remotes if you don't want to capture.

---

### Project 4: Physical Keyboard Macro Box

**Hardware:** Arduino Pro Micro or Leonardo (acts as USB HID) + 8–16 mechanical key switches  
**What it does:** A small keypad that acts as a USB keyboard. Each key sends a programmable macro or shortcut. When you've flashed ZMK on the Crush 80, you already understand this concept deeply — this is a compact version for your desk.  
**Extra:** Add an nRF24L01+ to make it wireless, controlling both your PC and the LG Flex from the same device.

---

### Project 5: Replicating the LG Magic Remote — Full Curvature Control

**Hardware:** ESP32 (if you buy it) + IR LED  
**What it does:** The LG Magic Remote uses **IR for basic commands** and **Bluetooth for pointer/voice features**. The ESP32 has built-in Bluetooth LE. You can:
1. Replicate all IR buttons in software (same code table as Part 3A)
2. Implement BLE HID to simulate the Magic Remote's pointer (move cursor on screen)
3. Combined with WebOS API: build full voice-to-TV control — ESP32 runs a wake word, sends commands over WebOS WebSocket

**Curvature macros specifically:** Create physical buttons labeled "Flat", "50% Curve", "Full Curve". Each button fires a sequence:
- `curve_flat`: send curvature button IR code N times until flat preset
- `curve_50`: send curvature IR code to preset 1 position  
- `curve_full`: send curvature IR code to max bend

This is doable with the Arduino + IR LED you already have.

---

### Project 6: LG Flex Screen-Based Dashboard (Local WebOS App)

**Hardware:** RPi 3B only (no additional hardware)  
**What it does:** Write a small HTML/JS app that runs as a webOS TV app. Displays on your LG Flex: current time, weather, keyboard layer indicator (from ZMK), gaming session stats. Launch it from the TV's home screen.  
**Tools:** LG webOS SDK (free), Deploy via `ares-install` CLI.

---

### Project 7: 2.4 GHz Spectrum Analyzer

**Hardware:** nRF24L01+ modules you already bought + RPi + any display  
**What it does:** The nRF24L01+ can scan its receive energy across all 84 channels. This visualizes 2.4 GHz activity in your home — useful for diagnosing WiFi congestion, finding interference, optimizing device placement.  
**Display:** Pipe the channel energy levels to a terminal bargraph or a small LCD/OLED display.  
**Bonus:** Since you've already set up the sniffing infrastructure for the Crush 80, this is a 30-minute addition.

---

### Parts Summary

| What you buy | Cost | Used for |
|---|---|---|
| nRF24L01+ PA+LNA ×4 (with antennas) | $12 | Crush 80 2.4G sniffing, wireless sensor mesh, spectrum analyzer |
| ESP32 dev board *(optional)* | $10 | LG Flex WiFi control + IR blaster, Magic Remote BLE clone, macro box |
| IR receiver module ×5 *(optional)* | $3 | Capture curvature + any remote's IR codes |
| **Total** | **$12–25** | — |

What you already have covers everything else.
