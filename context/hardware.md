# Modulate hardware inventory and first assembly

Inventory confirmed by the user on **October 28, 2026**. “Owned” means reported available, not connected or tested. Manufacturer documentation was checked on the same date; board revisions and installed software still need a bench check. No purchases are required by this plan.

## Available parts

One of each item below, including one cable kit:

| Part | Proposed role |
| --- | --- |
| [Raspberry Pi 5 Model B, 8 GB](https://www.raspberrypi.com/products/raspberry-pi-5/) | Trusted device runtime, isolated game execution, configuration validation, peripheral I/O |
| [Raspberry Pi 27 W power supply](https://www.raspberrypi.com/products/27w-power-supply/) | Pi power |
| [64 GB microSD card](https://www.raspberrypi.com/products/sd-cards/) | Operating system and local application |
| [USB-C microSD reader/writer, Adafruit #5212](https://www.adafruit.com/product/5212) | Prepare boot media from the development computer |
| [Adafruit Mini PiTFT #4393](https://www.adafruit.com/product/4393) | On-device game display, control labels/status, and connection to the I2C peripherals |
| [Adafruit QT rotary encoder #5880](https://www.adafruit.com/product/5880) | Main continuously adjustable control and encoder press |
| [Adafruit APDS9960 #3595](https://www.adafruit.com/product/3595) | Optional gesture/proximity input; light/color sensing |
| [Adafruit LSM6DS3TR-C IMU #4503](https://www.adafruit.com/product/4503) | Optional motion/tilt input |
| [SparkFun Servo pHAT](https://www.sparkfun.com/sparkfun-servo-phat-for-raspberry-pi.html) | Reserve; omit from the first assembly because no servo is available |
| [SparkFun Qwiic Button, red LED #15932](https://www.sparkfun.com/products/15932) | Primary action and status LED |
| [SparkFun Qwiic Button, green LED #16842](https://www.sparkfun.com/products/16842) | Secondary action and status LED |
| [SparkFun Qwiic Cable Kit](https://www.sparkfun.com/sparkfun-qwiic-cable-kit.html) | Peripheral connections; confirm supplied cable lengths and count |
| Bluetooth wireless speaker with microphone, model unspecified | Candidate voice input and audio output; microphone/profile compatibility untested |
| USB PnP microphone, confirmed attached October28 | Tested capture at16kHz mono through ALSA `plughw:CARD=Device,DEV=0`; successful local transcription in the number prototype |

## On hold

The user marked these **on hold**, so they are not available for the initial assembly:

| Part | Later role, if obtained and tested |
| --- | --- |
| [Raspberry Pi Active Cooler](https://www.raspberrypi.com/products/active-cooler/) | Pi cooling; confirm physical clearance with the PiTFT |
| [Logitech C270 webcam](https://www.logitech.com/en-us/shop/p/c270-hd-webcam.960-000694) | Optional camera input; exclude camera capability from the initial device manifest |

## Not available

The user marked these absent: PCF8574 GPIO expander (#5545), MPR121 capacitive-touch breakout (#4830), breadboard (#4539), copper foil tape, alligator clips, 9 g servo, micro-HDMI cable, and Qwiic SHIM (#15794).

Do not include those parts in the device's capabilities or make them a prerequisite for the first demo. The available encoder and Qwiic buttons cover the initial inputs. Touch pads and mechanical motion are out of the first scope.

## Requested capabilities still to establish

The October 28 product revision adds voice requests, generated games on the device's own screen, and control of a paired computer. It does not establish additional owned or working hardware.

- **Joystick:** requested as a possible game control, but absent from the confirmed inventory. Begin with encoder steering and buttons for game actions. Add a joystick to the manifest only after the user confirms one is available and its axes/buttons pass a bench test; no purchase is assumed.
- **Microphone:** the user subsequently attached a USB PnP microphone. Its capture and local Whisper transcription worked in the October28 number prototype. Bluetooth microphone support remains untested; the working USB path does not depend on it.
- **Voice activation:** voice is a core demo target. Start with push-to-talk while proving transcription; “Hey Meta” is the proposed wake phrase, with detection and false-trigger testing still to implement. It is not evidence of an official Meta voice-assistant integration. Typed prompts are a disclosed debugging fallback.
- **Computer connection:** the website is intended to pair the device and show its permitted actions. Actual PC system-volume control requires a tested host bridge for the selected operating system; browser media volume alone does not prove it. Advertise only the connected target and actions the bridge reports.

“Modular” means the design can use supported plug-in peripherals and update its capability manifest. Hot swapping is not established; continue to power down before changing this assembly.

## Smallest useful assembly

Start with **Pi 5 + Mini PiTFT + encoder + two Qwiic buttons**, plus microphone bring-up using the owned speaker. Add the APDS9960 and IMU only after a reliable physical input changes the on-device game or a paired host action.

The [Mini PiTFT documentation](https://www.adafruit.com/product/4393) describes a 1.14-inch, 135×240 SPI display, two onboard buttons, and a bottom STEMMA QT/Qwiic connector. That connector provides the I2C path for the external peripherals, so a separate Qwiic SHIM is unnecessary for this proposed arrangement. Target a simple original 2D kart racer on this screen, with short mode names, labels, values, and connection state when controlling the PC. Test orientation, game legibility, frame delivery, input-to-display latency, and sustained operation on the physical display before promising playability or frame rates. A host preview is useful for development but does not prove on-device play. Put full transcripts, code/check results, and configuration previews on the host UI. Do not assume the PiTFT is a touchscreen.

With the Pi powered off and unplugged, seat the PiTFT's **2×12 socket over the first 12 pairs of GPIO pins: physical pins 1–24**. Align pin 1 at the header end by the Pi's rounded corner/mounting hole, using the [Adafruit orientation and pinout guide](https://learn.adafruit.com/adafruit-mini-pitft-135x240-color-tft-add-on-for-raspberry-pi/pinouts). Check both rows and both ends before applying power; do not offset the socket by one pin or pair. The display mounts directly to the header and needs no loose jumper wires.

Use **QT-to-QT/Qwiic cables with a keyed four-pin plug at each end** for the peripheral chain. Set aside the dangling Dupont breakout cable shown in the supplied photo; it is not needed for this assembly. The other loose/unidentified boards in that photo do not establish additional inventory or capabilities.

```text
Pi 5 GPIO header → Mini PiTFT
Mini PiTFT QT port → encoder → red button → green button
                                      optional later → APDS9960 → IMU
Pi device service → bounded input API → isolated game runtime
Isolated game runtime → bounded drawing API → Pi device service → PiTFT
Pi device service ↔ authenticated local connection ↔ paired PC bridge
Host website → pairing, transcript, code/check results, and preview
Owned speaker microphone → Pi voice input, only after capture is verified
```

This is a proposed daisy-chain topology, not a tested wiring diagram. Switch off power before attaching boards or changing cables. Confirm orientation, board revision, connector access, and that the display clears the Pi's cooling hardware. Leave the Servo pHAT out rather than assuming both header boards can stack with the supplied connectors.

## I2C address plan

| Peripheral | Documented default | Proposed first configuration |
| --- | --- | --- |
| Rotary encoder | `0x36` | Keep `0x36` ([Adafruit guide](https://learn.adafruit.com/adafruit-i2c-qt-rotary-encoder?view=all)) |
| Red Qwiic button | `0x6F` | Keep `0x6F` |
| Green Qwiic button | `0x6F` | Change to unused `0x6E` before connecting both buttons |
| APDS9960 | `0x39` | Keep `0x39` ([Adafruit driver](https://adafruit.github.io/Adafruit_APDS9960/html/_adafruit___a_p_d_s9960_8h.html)) |
| LSM6DS3TR-C | `0x6A` | Keep `0x6A` ([Adafruit guide](https://learn.adafruit.com/adafruit-lsm6ds3tr-c-6-dof-accel-gyro-imu?view=all)) |

Both button colors share the factory address. Configure the **green button alone** before building the full chain:

1. Power off and unplug the Pi. Connect the PiTFT QT port directly to the green button with one QT-to-QT cable; leave the red button disconnected.
2. Boot with I2C enabled and the SparkFun `qwiic_button` Python library installed. Check the button's current address; a previously configured board may no longer be at `0x6F`.
3. If it is at `0x6F`, use [SparkFun's address-change example](https://github.com/sparkfun/qwiic_button_py/blob/main/examples/qwiic_button_ex6_changeI2CAddress.py) and enter `6E` at its prompt. The example calls `set_I2C_address(0x6E)`; do not use the setter's return value as proof that the change succeeded.
4. Shut down and power-cycle with the green button still isolated. Verify it responds at `0x6E` and its press/LED operation works.
5. Shut down and unplug again, then connect the full encoder → red → green chain. Verify the red button at `0x6F` and green at `0x6E` independently.

The proposed addresses avoid the other listed devices. An address scan alone does not prove identity or correct operation. See the [SparkFun hookup guide](https://learn.sparkfun.com/tutorials/sparkfun-qwiic-button-hookup-guide/all). These steps are documented guidance, not evidence that the user's hardware has been configured.

## Bring-up order and evidence

1. **Boot headlessly.** If the card needs an OS, use Raspberry Pi Imager to select a Pi 5-compatible OS and configure network access and SSH. Writing an image erases the selected card; check for existing work first. An HDMI cable is unnecessary for this network-based setup. Follow [Raspberry Pi's headless setup](https://www.raspberrypi.com/documentation/computers/getting-started.html#headless-remote-setup).
2. **Verify buses and display.** Follow [current Pi 5 Blinka setup](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi), enable I2C/SPI, and render a test label using the [PiTFT Python/ST7789 approach](https://learn.adafruit.com/adafruit-mini-pitft-135x240-color-tft-add-on-for-raspberry-pi/python-setup). Record OS and library versions. Pi 5 can report a busy chip-enable line; use Adafruit's [current SPI guidance](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/spi-sensors-devices) for OS configuration if encountered. Do not assume old GPIO libraries or framebuffer instructions work unchanged, or attempt to move the board's fixed chip-select wiring.
3. **Prove the encoder.** Read clockwise/counterclockwise movement and press. The [encoder guide](https://learn.adafruit.com/adafruit-i2c-qt-rotary-encoder?view=all) notes the preassembled encoder's direction differs from a conventional loose encoder; check the sign rather than guessing.
4. **Add buttons individually.** Resolve the address collision, verify presses and LEDs, then attach both. Add their stable IDs to the manifest only after successful reads.
5. **Prove voice capture.** Pair the owned speaker with the Pi and check microphone capture before marking voice input available. Test push-to-talk, transcription, noisy-room behavior, and audio playback separately. Record whether capture is on the Pi or an explicitly disclosed host-microphone fallback; test the proposed wake phrase only after capture works.
6. **Complete the on-device interaction.** Use encoder and button events to steer and brake in a small test scene on the PiTFT. Record physical input and visible effect together; measure frame delivery and input-to-display latency. A manually written scene proves I/O only. Live generated-game evidence additionally requires the isolated execution and verification path in the [architecture](architecture.md).
7. **Prove the paired PC action.** Pair one computer through the proposed website/bridge flow, grant the volume action, and show the encoder changing that computer's actual system volume. Verify the displayed target, reported volume, disconnect behavior, and revocation. A browser-only audio demo must be labeled as such.
8. **Add sensing if useful.** Test repeatable gesture and motion events, thresholds, and false activations before enabling them in generated mappings. APDS9960 readings are not camera images; IMU readings are not proof of position tracking.

Meta inference remains a separate provider integration. Owning an 8 GB Pi does not establish that the intended model runs locally. Keep keys on the trusted service and physical event handling/rendering independent of inference. Generated game code must use the bounded runtime described in the [architecture](architecture.md); direct GPIO access and firmware flashing are not part of the first demo.

## Proposed mapping that uses these parts

| Control | On-device kart game | Paired PC volume |
| --- | --- | --- |
| Encoder rotation | Steer left/right with bounded sensitivity | Adjust the paired computer's volume within allowed bounds |
| Encoder press | Confirm a menu choice | Confirm the displayed target/mapping |
| Red button | Brake | Mute only if the host advertises and grants it |
| Green button | Start/pause | Push-to-talk trigger, once voice input works |
| PiTFT | Original 2D game, score/status, short control hints | Paired target, volume, mapping, and connection state |

These are candidate mappings, not implemented controls. A strong follow-up is “make the steering less sensitive,” followed by visible game behavior, or “make each turn change the volume by a smaller amount,” followed by a measured PC-volume change. The agent must use the tested control IDs and current paired-device permissions. Joystick, gesture, and tilt support can follow confirmed availability and repeatable tests.
