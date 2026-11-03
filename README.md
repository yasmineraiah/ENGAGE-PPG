# Pulse Oximetry and Optical Bias: STEM Educational Kit


## Overview
This repository contains the software implementation for a microcontroller-based pulse oximeter, designed as a hands-on educational outreach kit. It streams live physiological data (PPG waveforms, SpO2, and Heart Rate) from a MAX30102 sensor over a local network via WebSockets to a browser-based clinical dashboard. 

## Project Motivation
The primary motivation behind this project is to guide young people's attention toward fairness, equity, and bias in health technologies. Pulse oximeters are widely used medical devices that measure blood oxygen saturation using light-based sensing, but clinical studies show these devices can produce less accurate readings for individuals with darker skin tones. 

This project translates this real-world issue into an accessible learning activity. Using a microcontroller and a sensor housed in a 3D-printed enclosure, students build and test a functioning pulse monitor. 

To teach inclusive engineering without "othering" individuals, the kit simulates variations in light absorption using interchangeable optical filters of different opacities. When the signal drops due to an opaque filter, students take on collaborative roles to modify parameters such as LED circuit components or signal filtering to produce a clearer heartbeat waveform. 

The goal is to support widening participation in STEM for under-represented and disadvantaged backgrounds, with particular emphasis on encouraging young girls and non-binary students. By demonstrating that engineering decisions can benefit everyone, the activity builds students' self-confidence and trust in their ability to fix bias.

## System Architecture
The system is divided into a MicroPython backend running on a Raspberry Pi Pico W and a frontend clinical dashboard.

* **Digital Signal Processing (dsp.py):** Implements a fixed-size circular buffer of 100 samples to manage memory efficiently. It calculates the DC baseline, extracts the AC pulsatile component, and applies a bandpass filter. It includes an auto-calibration function that boosts LED drive current if the signal drops below a specific threshold (simulating algorithmic correction for optical interference). SpO2 is calculated using the ratio-of-ratios method, and BPM is calculated using an adaptive threshold based on RMS amplitude.
* **Network & Streaming (main.py):** Initializes the I2C connection to the MAX30102 at 0x57. It hosts a local web server on port 80 and establishes a WebSocket connection with the client browser, streaming raw JSON telemetry data.
* **Frontend Telemetry (index.html):** A zero-dependency HTML/JS dashboard that receives WebSocket data and visualizes the real-time photoplethysmogram (PPG) waveform alongside historical trends for SpO2 and BPM using Chart.js.
* **Bias Simulator (index_depr.html):** An interactive UI designed to visualize the mathematical impact of the Monk Skin Tone (MST) scale and Perfusion Index (PI) on SpO2 measurement bias, demonstrating the limits of software correction when physical signals are inherently weak.

## Hardware Requirements
* Raspberry Pi Pico W
* MAX30102 Pulse Oximeter and Heart-Rate Sensor
* Jumper wires
* 3.3V Power Supply (via USB)

## Wiring Configuration
| MAX30102 Pin | Pico W Pin |
| :--- | :--- |
| VIN | 3V3 |
| GND | GND |
| SCL | GP5 |
| SDA | GP4 |

## Setup and Installation
1. Flash your Raspberry Pi Pico W with the latest MicroPython firmware.
2. Upload the `max30102.py` library (required, not included in this repository's core files) to the device.
3. Transfer all `.py` and `.html` files from this repository to the root directory of the Pico W.
4. Modify `secrets.py` to include your local Wi-Fi SSID and password.
5. Run `main.py`. The Pico W will connect to the network and output its IP address to the serial console upon successful connection.
6. Open a web browser on a device connected to the same network and navigate to the Pico W's IP address to view the telemetry dashboard.

## File Structure
* `main.py`: Entry point. Handles Wi-Fi connection, web server setup, and WebSocket data streaming.
* `dsp.py`: Core algorithms for signal processing, beat detection, and hardware auto-calibration.
* `secrets.py`: Stores Wi-Fi credentials.
* `scan.py` / `i2c_scan.py` / `mac.py`: Utility scripts for hardware and network debugging.
* `index.html`: The primary clinical dashboard interface.
* `index_depr.html`: The optical bias and hardware limitation simulation interface.
* `Final proposal.pdf`: Documentation outlining the educational framework, learning outcomes, and outreach strategy.
