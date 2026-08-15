import network 
import socket
import time
import json
import gc 
import hashlib
import binascii
import math 
from machine import Pin, I2C
from secrets import WIFI_NAME, WIFI_PASSWORD
from dsp import PulseProcessor 
import max30102

# hardware constants for the max30102
MAX30102_I2C_ADDR = 0x57
REG_LED1_PA = 0x0C
REG_LED2_PA = 0x0D

TARGET_DC_MIN = 20000
CURRENT_LED_HEX = 0x24

VIRTUAL_ATTENUATION_RED = 1.0
VIRTUAL_ATTENUATION_IR = 1.0

# initialise i2c connection 
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
# pass the connection to the sensor library
sensor = max30102.MAX30102(i2c=i2c)
sensor.setup_sensor()

processor = PulseProcessor(i2c_bus=i2c, buffer_size=100)


def get_sensor_val():
    try:
        sensor.check()

        if sensor.available():
            red_reading = sensor.pop_red_from_storage()
            ir_reading = sensor.pop_ir_from_storage()

            red_reading = int(red_reading * VIRTUAL_ATTENUATION_RED)
            ir_reading = int(ir_reading * VIRTUAL_ATTENUATION_IR)

            return red_reading, ir_reading 
    except Exception as e:
        print("Error reading sensor:", e)
    return 0,0



def send_ws_message(conn, msg):
    payload = msg.encode('utf-8')
    length = len(payload)
    # websocket header, text frame 
    header = bytearray([0x81, length])
    conn.sendall(header + payload)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(0.5)
    wlan.active(True)

    wlan.connect(WIFI_NAME, WIFI_PASSWORD)

    print("connecting to wifi ...")
    max_wait = 20
    while max_wait > 0:
        status = wlan.status()
        if status < 0 or status >= 3:
            break
        max_wait -= 1
        print("waiting for connection... status =", status)
        time.sleep(1)

    if wlan.status() != 3:
        raise RuntimeError("wifi connection failed")

    print(f"connected to wifi! IP address: {wlan.ifconfig()[0]}")
    wlan.config(pm=0xa11140) 
    return wlan

def start_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(5)
    s.settimeout(0.2)

    print("Web server live! Waiting for browser...")
    while True:
        conn = None
        log_file = None
        try:
            conn, addr = s.accept()
            conn.settimeout(None)
            
            request = conn.recv(2048).decode('utf-8')

            if 'Upgrade: websocket' in request:
                print(f"1. Browser connected from {addr[0]}...")
                key = request.split('Sec-WebSocket-Key: ')[1].split('\r\n')[0]
                magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                accept_key = binascii.b2a_base64(hashlib.sha1((key + magic).encode()).digest())[:-1].decode()

                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
                )

                conn.sendall(response.encode('utf-8'))
                print("2. WebSocket handshake successful! Streaming...")

                log_file = open('session_log.csv', 'w')
                log_file.write("Red_Raw, IR_Raw, SpO2, BPM, LED_HEX\n")

                
                conn.setblocking(False)
                frame_count = 0
                
                while True:
                    # 1. Peek to see if the browser secretly disconnected
                    try:
                        check = conn.recv(1)
                        if check == b'':
                            print("Client disconnected gracefully. Closing stream.")
                            break  
                    except OSError:
                        pass  

                    sensor.check()
                    has_new_data = False

                    while sensor.available():
                        red_val = sensor.pop_red_from_storage()
                        ir_val = sensor.pop_ir_from_storage()

                        if red_val > 0 and ir_val > 0:
                            processor.add_sample(red_val, ir_val)

                            ac_wave, bpm, spo2 = processor.process()

                            log_file.write(f"{red_val}, {ir_val}, {spo2}, {bpm}, {hex(processor.current_led_hex)}\n")
                            has_new_data = True


                    if has_new_data:

                        data = json.dumps({
                            "wave" : ac_wave,
                            "bpm" : bpm ,
                            "spo2" : spo2
                        })
                    
                    
                        # 3. Try to send data.
                        try:
                            send_ws_message(conn, data)
                        except OSError:
                            print("Client dropped connection abruptly. Closing stream.")
                            break  

                    time.sleep_ms(50)
                    frame_count += 1

                    if frame_count >= 100:
                        gc.collect()
                        frame_count = 0

            else:
                # Standard HTTP page load
                conn.sendall('HTTP/1.0 200 OK\r\nContent-type: text/html\r\nConnection: close\r\n\r\n'.encode('utf-8'))
                with open('index.html', 'rb') as f:
                    while True:
                        chunk = f.read(512)
                        if not chunk:
                            break
                        conn.sendall(chunk)
                conn.close()

        except Exception as e:
            err_msg = str(e)
            if "110" not in err_msg and "ETIMEDOUT" not in err_msg:
                print(f"CRASH CAUGHT: {err_msg}")
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
            if log_file:
                try:
                    log_file.close()
                    print("log file saved successfully")
                except:
                    pass
            gc.collect()

connect_wifi()
start_server()

