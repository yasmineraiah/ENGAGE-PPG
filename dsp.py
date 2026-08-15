import math 
import time 

class PulseProcessor:
    def __init__(self, i2c_bus, buffer_size=100):
        self.i2c = i2c_bus
        self.buffer_size = buffer_size
        self.red_buf = []
        self.ir_buf = []
        self.bpm = 0
        self.spo2 = 0.0

        # Fixed variable names
        self.I2C_ADDR = 0x57
        self.REG_RED = 0x0C
        self.REG_IR = 0x0D
        self.TARGET_DC_MIN = 20000
        self.current_led_hex = 0x24

        self.cooldown = 0

        self.ir_ac_filtered = []
        self.last_beat_time = time.ticks_ms()
        self.is_beating = False

    def set_led_current(self, hex_val):
        self.current_led_hex = max(0x00, min(0xFF, hex_val))
        try:
            self.i2c.writeto_mem(self.I2C_ADDR, self.REG_RED, bytes([self.current_led_hex]))
            self.i2c.writeto_mem(self.I2C_ADDR, self.REG_IR, bytes([self.current_led_hex]))

            print(f"Hardware has been adjusted, LED drive current boosted to {hex(self.current_led_hex)}")
        except Exception as e:
            print("Error setting LED current:", e)

    def calibrate_signal(self, dc_ir):
        # If the signal is too dark boost until hardware limit 
        if dc_ir < self.TARGET_DC_MIN and self.current_led_hex < 0xFF:
            new_hex = min(0xFF, self.current_led_hex + 0x10)
            self.set_led_current(new_hex)
            
            # FIXED: 'cooldown' now has an 'n' and will lock properly
            self.cooldown = self.buffer_size 

    def add_sample(self, red, ir):
        self.red_buf.append(red)
        self.ir_buf.append(ir)
        if len(self.red_buf) > self.buffer_size:
            self.red_buf.pop(0)
            self.ir_buf.pop(0)

    def process(self):
        if len(self.red_buf) < self.buffer_size:
            return 0, 0, 0
            
        # Calculate the DC baseline
        dc_red = sum(self.red_buf) / self.buffer_size
        dc_ir = sum(self.ir_buf) / self.buffer_size

        if dc_red == 0 or dc_ir == 0:
            return 0, 0, 0

        # PROXIMITY THRESHOLD: Stops the hat/empty air from tricking the math
        if dc_ir < 2000:
            self.current_led_hex = 0x24  # Reset LED brightness
            self.red_buf = []            # Clear stale data
            self.ir_buf = []
            self.bpm = 0
            self.ir_ac_filtered = []
            return 0, 0, 0

        # Check cooldown before allowing another hardware boost
        if self.cooldown > 0:
            self.cooldown -= 1
        else:
            self.calibrate_signal(dc_ir)

        # AC RMS calculation
        ac_red_sq = sum((x - dc_red) ** 2 for x in self.red_buf) / self.buffer_size
        ac_ir_sq = sum((x - dc_ir) ** 2 for x in self.ir_buf) / self.buffer_size
        rms_red = math.sqrt(ac_red_sq)
        rms_ir = math.sqrt(ac_ir_sq)

        try:
            r_log = (math.log(dc_red + rms_red) - math.log(dc_red)) / (math.log(dc_ir + rms_ir) - math.log(dc_ir))
            spo2_calc = -45.060 * (r_log ** 2) + 30.354 * r_log + 94.845
            self.spo2 = max(70.0, min(100.0, round(spo2_calc, 1)))
        except (ValueError, ZeroDivisionError):
            pass

        #bandpass filter 
        latest_ac_ir = dc_ir - self.ir_buf[-1] # highpass 

        self.ir_ac_filtered.append(latest_ac_ir)
        if len(self.ir_ac_filtered) > 4:
            self.ir_ac_filtered.pop(0)

        smoothed_ac = sum(self.ir_ac_filtered) / len(self.ir_ac_filtered)

        current_time = time.ticks_ms()
        beat_threshold = rms_ir * 0.3

        if smoothed_ac > beat_threshold and not self.is_beating:
            self.is_beating = True
            dt = time.ticks_diff(current_time, self.last_beat_time)

            if 300 < dt < 1500:
                instant_bpm = 60000 / dt
                if self.bpm == 0:
                    self.bpm = int(instant_bpm)
                else:
                    self.bpm = int((self.bpm * 0.8) + (instant_bpm * 0.2))
            self.last_beat_time = current_time

        elif smoothed_ac < 0 and self.is_beating:
            self.is_beating = False

        return int(smoothed_ac), self.bpm, self.spo2