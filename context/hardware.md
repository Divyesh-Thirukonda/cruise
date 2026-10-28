# Hardware inventory and first assembly

Inventory confirmed by the user on **October 28, 2026**. “Owned” means reported available, not connected or tested. Manufacturer documentation was checked on the same date; board revisions and installed software still need a bench check. No purchases are required by this plan.

## Available parts

One of each item below, including one cable kit:

| Part | Proposed role |
| --- | --- |
| [Raspberry Pi 5 Model B, 8 GB](https://www.raspberrypi.com/products/raspberry-pi-5/) | Device runtime, configuration validation, peripheral I/O |
| [Raspberry Pi 27 W power supply](https://www.raspberrypi.com/products/27w-power-supply/) | Pi power |
| [64 GB microSD card](https://www.raspberrypi.com/products/sd-cards/) | Operating system and local application |
| [USB-C microSD reader/writer, Adafruit #5212](https://www.adafruit.com/product/5212) | Prepare boot media from the development computer |
| [Adafruit Mini PiTFT #4393](https://www.adafruit.com/product/4393) | Small mode/label display and connection to the I2C peripherals |
| [Adafruit QT rotary encoder #5880](https://www.adafruit.com/product/5880) | Main continuously adjustable control and encoder press |
| [Adafruit APDS9960 #3595](https://www.adafruit.com/product/3595) | Optional gesture/proximity input; light/color sensing |
| [Adafruit LSM6DS3TR-C IMU #4503](https://www.adafruit.com/product/4503) | Optional motion/tilt input |
| [SparkFun Servo pHAT](https://www.sparkfun.com/sparkfun-servo-phat-for-raspberry-pi.html) | Reserve; omit from the first assembly because no servo is available |
| [SparkFun Qwiic Button, red LED #15932](https://www.sparkfun.com/products/15932) | Primary action and status LED |
| [SparkFun Qwiic Button, green LED #16842](https://www.sparkfun.com/products/16842) | Secondary action and status LED |
| [SparkFun Qwiic Cable Kit](https://www.sparkfun.com/sparkfun-qwiic-cable-kit.html) | Peripheral connections; confirm supplied cable lengths and count |
| Bluetooth wireless speaker with microphone, model unspecified | Candidate audio output; microphone/profile compatibility untested |

## Not available

The user marked these absent: PCF8574 GPIO expander (#5545), MPR121 capacitive-touch breakout (#4830), breadboard (#4539), copper foil tape, alligator clips, 9 g servo, micro-HDMI cable, and Qwiic SHIM (#15794).

Do not include those parts in the device's capabilities or make them a prerequisite for the first demo. The available encoder and Qwiic buttons cover the initial inputs. Touch pads and mechanical motion are out of the first scope.

## Smallest useful assembly

Start with **Pi 5 + Mini PiTFT + encoder + two Qwiic buttons**. Add the APDS9960 and IMU only after a reliable physical input changes a real host action.

The [Mini PiTFT documentation](https://www.adafruit.com/product/4393) describes a 1.14-inch, 135×240 SPI display, two onboard buttons, and a bottom STEMMA QT/Qwiic connector. That connector provides the I2C path for the external peripherals, so a separate Qwiic SHIM is unnecessary for this proposed arrangement. Use the screen for short mode names, labels, values, and connection state; put full prompt entry and configuration preview on the host computer. Do not assume it is a touchscreen.

```text
Pi 5 GPIO header → Mini PiTFT
Mini PiTFT QT port → encoder → red button → green button
                                      optional later → APDS9960 → IMU
Pi device service ↔ local network ↔ host prompt UI and demo application
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

Both button colors share the factory address. Connect only one button while configuring its address with the manufacturer's supported method; then power-cycle and verify persistence before adding the other. Check actual board addresses because they may already have been changed. The proposed addresses avoid the other listed devices; an address scan alone does not prove device identity or correct operation. See the [SparkFun hookup guide](https://learn.sparkfun.com/tutorials/sparkfun-qwiic-button-hookup-guide/all).

## Bring-up order and evidence

1. **Boot headlessly.** If the card needs an OS, use Raspberry Pi Imager to select a Pi 5-compatible OS and configure network access and SSH. Writing an image erases the selected card; check for existing work first. An HDMI cable is unnecessary for this network-based setup. Follow [Raspberry Pi's headless setup](https://www.raspberrypi.com/documentation/computers/getting-started.html#headless-remote-setup).
2. **Verify buses and display.** Follow [current Pi 5 Blinka setup](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi), enable I2C/SPI, and render a test label using the [PiTFT Python/ST7789 approach](https://learn.adafruit.com/adafruit-mini-pitft-135x240-color-tft-add-on-for-raspberry-pi/python-setup). Record OS and library versions. Pi 5 can report a busy chip-enable line; use Adafruit's [current SPI guidance](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/spi-sensors-devices) for OS configuration if encountered. Do not assume old GPIO libraries or framebuffer instructions work unchanged, or attempt to move the board's fixed chip-select wiring.
3. **Prove the encoder.** Read clockwise/counterclockwise movement and press. The [encoder guide](https://learn.adafruit.com/adafruit-i2c-qt-rotary-encoder?view=all) notes the preassembled encoder's direction differs from a conventional loose encoder; check the sign rather than guessing.
4. **Add buttons individually.** Resolve the address collision, verify presses and LEDs, then attach both. Add their stable IDs to the manifest only after successful reads.
5. **Complete one physical interaction.** Send the encoder event to a host audio control or timeline action, then record input, screen label, and visible/audible effect together.
6. **Add sensing if useful.** Test repeatable gesture and motion events, thresholds, and false activations before enabling them in generated mappings. APDS9960 readings are not camera images; IMU readings are not proof of position tracking.
7. **Check audio separately.** Pair the owned speaker with the machine producing audio and test timing. Treat its microphone as unavailable until capture works on the selected host; typed prompts remain the baseline.

Meta inference remains a separate provider integration. Owning an 8 GB Pi does not establish that the intended model runs locally. Keep keys on the trusted service and physical event handling independent of inference.

## Proposed mapping that uses these parts

| Control | Music mode | Video mode |
| --- | --- | --- |
| Encoder rotation | Adjust one mix parameter | Scrub a timeline |
| Encoder press | Toggle fine/coarse adjustment | Toggle frame/large-step scrub |
| Red button | Start/stop a loop | Play/pause |
| Green button | Trigger a second allowed action | Add a marker |
| PiTFT | Active mode, mappings, current value | Updated mappings and current position |

Actions require a real implementation in the chosen host application. A strong follow-up is “make the knob move one frame per step and swap the two buttons,” followed by using the changed controls. Gesture or tilt remapping is a stretch demonstration, not a reason to delay this loop.
