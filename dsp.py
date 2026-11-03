import math
import time


class PulseProcessor:
    def __init__(self, i2c_bus, buffer_size=100, sample_rate=50):
        self.i2c = i2c_bus
        self.buffer_size = buffer_size
        # Samples per second actually delivered by the sensor
        # (sample_rate / sample_avg in setup_sensor, 400 / 8 = 50 by default).
        # Beat timing is worked out from the sample count, not the wall
        # clock: samples arrive in bursts every loop, so ticks_ms() made
        # every beat interval wrong and pushed BPM to around 40.
        self.sample_rate = sample_rate
        self.red_buf = []
        self.ir_buf = []
        self.bpm = 0
        self.spo2 = 0.0
        self.finger = False

        self.I2C_ADDR = 0x57
        self.REG_RED = 0x0C
        self.REG_IR = 0x0D
        self.TARGET_DC_MIN = 20000
        self.BASE_LED_HEX = 0x24
        self.NO_FINGER_DC = 2000
        self.current_led_hex = self.BASE_LED_HEX

        self.cooldown = 0

        self.ir_ac_filtered = []
        self.sample_index = 0
        self.last_beat_index = 0
        self.is_beating = False

    def set_led_current(self, hex_val):
        self.current_led_hex = max(0x00, min(0xFF, hex_val))
        try:
            self.i2c.writeto_mem(self.I2C_ADDR, self.REG_RED, bytes([self.current_led_hex]))
            self.i2c.writeto_mem(self.I2C_ADDR, self.REG_IR, bytes([self.current_led_hex]))
            print("LED drive current set to", hex(self.current_led_hex))
        except Exception as e:
            print("Error setting LED current:", e)

    def calibrate_signal(self, dc_ir):
        # If the signal is too dark, boost until the hardware limit
        if dc_ir < self.TARGET_DC_MIN and self.current_led_hex < 0xFF:
            self.set_led_current(min(0xFF, self.current_led_hex + 0x10))
            self.cooldown = self.buffer_size

    def add_sample(self, red, ir):
        self.sample_index += 1
        self.red_buf.append(red)
        self.ir_buf.append(ir)
        if len(self.red_buf) > self.buffer_size:
            self.red_buf.pop(0)
            self.ir_buf.pop(0)

    def _reset(self):
        self.red_buf = []
        self.ir_buf = []
        self.ir_ac_filtered = []
        self.bpm = 0
        self.spo2 = 0.0
        self.is_beating = False
        self.cooldown = 0
        # Actually write the reset to the sensor. Before, only the variable
        # was changed, so the software and the LEDs disagreed.
        if self.current_led_hex != self.BASE_LED_HEX:
            self.set_led_current(self.BASE_LED_HEX)

    def process(self):
        # Finger detection runs on the newest sample so it reacts at once
        if self.ir_buf and self.ir_buf[-1] < self.NO_FINGER_DC:
            if self.finger or self.red_buf:
                self._reset()
            self.finger = False
            return 0, 0, 0
        self.finger = True

        if len(self.red_buf) < self.buffer_size:
            return 0, 0, 0

        # DC baseline
        dc_red = sum(self.red_buf) / self.buffer_size
        dc_ir = sum(self.ir_buf) / self.buffer_size
        if dc_red == 0 or dc_ir == 0:
            return 0, 0, 0

        if self.cooldown > 0:
            self.cooldown -= 1
        else:
            self.calibrate_signal(dc_ir)

        # AC RMS
        ac_red_sq = 0
        ac_ir_sq = 0
        for i in range(self.buffer_size):
            d = self.red_buf[i] - dc_red
            ac_red_sq += d * d
            d = self.ir_buf[i] - dc_ir
            ac_ir_sq += d * d
        rms_red = math.sqrt(ac_red_sq / self.buffer_size)
        rms_ir = math.sqrt(ac_ir_sq / self.buffer_size)

        try:
            r_log = (math.log(dc_red + rms_red) - math.log(dc_red)) / (math.log(dc_ir + rms_ir) - math.log(dc_ir))
            spo2_calc = -45.060 * (r_log ** 2) + 30.354 * r_log + 94.845
            self.spo2 = max(70.0, min(100.0, round(spo2_calc, 1)))
        except (ValueError, ZeroDivisionError):
            pass

        # High pass (inverted so each heartbeat points upwards)
        latest_ac_ir = dc_ir - self.ir_buf[-1]
        self.ir_ac_filtered.append(latest_ac_ir)
        if len(self.ir_ac_filtered) > 4:
            self.ir_ac_filtered.pop(0)
        smoothed_ac = sum(self.ir_ac_filtered) / len(self.ir_ac_filtered)

        beat_threshold = rms_ir * 0.3
        if smoothed_ac > beat_threshold and not self.is_beating:
            self.is_beating = True
            dt = (self.sample_index - self.last_beat_index) * 1000 / self.sample_rate
            if 300 < dt < 1500:
                instant_bpm = 60000 / dt
                if self.bpm == 0:
                    self.bpm = int(instant_bpm)
                else:
                    self.bpm = int((self.bpm * 0.8) + (instant_bpm * 0.2))
            self.last_beat_index = self.sample_index
        elif smoothed_ac < 0 and self.is_beating:
            self.is_beating = False

        return int(smoothed_ac), self.bpm, self.spo2
