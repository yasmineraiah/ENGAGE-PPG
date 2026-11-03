import network
import socket
import select
import time
import json
import gc
import os
import hashlib
import binascii
from machine import Pin, I2C
from secrets import WIFI_NAME, WIFI_PASSWORD
from dsp import PulseProcessor
import max30102

# The page served at http://<pico-ip>/
DASHBOARD_FILE = 'index2.html'

# Files the dashboard is allowed to load, by extension
CONTENT_TYPES = {
    'html': 'text/html',
    'js': 'application/javascript',
    'css': 'text/css',
    'png': 'image/png',
    'woff2': 'font/woff2',
    'ico': 'image/x-icon',
}

MAX30102_I2C_ADDR = 0x57
SAMPLE_RATE = 400      # sensor sample rate
SAMPLE_AVG = 8         # on-chip averaging, so 400 / 8 = 50 samples a second
# Off for demos: this writes about 1.5 KB/s, which fills the Pico's flash
# during a long session and takes the sensor loop down with it. The logging
# code below is left in place, so this is the only line to flip.
LOG_TO_FILE = False

VIRTUAL_ATTENUATION_RED = 1.0
VIRTUAL_ATTENUATION_IR = 1.0

# ---------- sensor ----------
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)

found = i2c.scan()
print("I2C devices found:", [hex(d) for d in found])
if MAX30102_I2C_ADDR not in found:
    print("MAX30102 NOT FOUND at 0x57. Check the wiring:")
    print("  VIN -> 3V3 (pin 36), GND -> GND, SDA -> GP4 (pin 6), SCL -> GP5 (pin 7)")
    print("  SDA and SCL swapped is the most common cause.")
    raise RuntimeError("MAX30102 not detected on the I2C bus")

sensor = max30102.MAX30102(i2c=i2c)
sensor.setup_sensor(sample_rate=SAMPLE_RATE, sample_avg=SAMPLE_AVG)

processor = PulseProcessor(i2c_bus=i2c, buffer_size=100,
                           sample_rate=SAMPLE_RATE // SAMPLE_AVG)
# setup_sensor() leaves the LEDs at 0x7F, but the auto-calibration assumes
# it starts at 0x24. Write it so the hardware and the software agree;
# otherwise the first "boost" actually dims the LEDs.
processor.set_led_current(processor.BASE_LED_HEX)
print("MAX30102 ready")


def check_dashboard_files():
    """Print which of the dashboard's files actually made it onto the board.

    MicroPico only uploads the extensions listed in micropico.syncFileTypes, and
    the default list has no png or woff2 in it, so the fonts and the device image
    are the first things to go missing. Missing files are reported, never raised:
    the sensor loop should still run even if the page ends up unstyled.
    """
    needed = [
        DASHBOARD_FILE,
        'vendor/chart.umd.js',
        'assets/pulse-oximeter-icon-removebg.png',
    ]
    for weight in (400, 500, 600, 700, 800):
        needed.append('vendor/fonts/poppins-%d-latin.woff2' % weight)

    print("Checking dashboard files:")
    missing = 0
    for path in needed:
        if file_exists(path):
            print("  OK       %s" % path)
        else:
            print("  MISSING: %s" % path)
            missing += 1

    if missing:
        print("  %d of %d missing. The page is still served, but it will not look"
              % (missing, len(needed)))
        print("  right. Check micropico.syncFileTypes includes png and woff2.")
    else:
        print("  All %d dashboard files present." % len(needed))

    try:
        st = os.statvfs('/')
        free_kb = st[4] * st[1] / 1024   # f_bavail * f_frsize
        print("  Free flash: %.1f KB" % free_kb)
    except (AttributeError, OSError) as e:
        print("  Could not read free flash space:", e)


# ---------- wifi ----------
def connect_wifi():
    try:
        import rp2
        rp2.country('GB')
    except Exception:
        pass

    reasons = {
        -1: "general failure (weak signal or power)",
        -2: "network not found (check the name, and that it's 2.4 GHz)",
        -3: "wrong password",
        2: "joined but got no IP address",
    }

    wlan = network.WLAN(network.STA_IF)

    for attempt in range(1, 4):
        print("wifi attempt", attempt, "->", WIFI_NAME)
        wlan.active(False)
        time.sleep(0.5)
        wlan.active(True)
        wlan.config(pm=0xa11140)  # power saving off before connecting
        wlan.connect(WIFI_NAME, WIFI_PASSWORD)

        for _ in range(30):
            status = wlan.status()
            if status < 0 or status >= 3:
                break
            print("waiting... status =", status)
            time.sleep(1)

        status = wlan.status()
        if status == 3:
            ip = wlan.ifconfig()[0]
            print("connected! signal:", wlan.status('rssi'))
            print("Open http://%s/ in your browser" % ip)
            return wlan

        print("failed, status =", status, "-", reasons.get(status, "unknown"))
        wlan.disconnect()
        time.sleep(2)

    raise RuntimeError("wifi connection failed")

# ---------- http / websocket helpers ----------
def read_request(conn):
    data = b''
    while b'\r\n\r\n' not in data and len(data) < 4096:
        chunk = conn.recv(1024)
        if not chunk:
            break
        data += chunk
    return data.decode('utf-8', 'ignore')


def parse_request(raw):
    lines = raw.split('\r\n')
    parts = lines[0].split(' ') if lines else []
    path = parts[1] if len(parts) > 1 else '/'
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            k, v = line.split(':', 1)
            headers[k.strip().lower()] = v.strip()
    return path, headers


def file_exists(path):
    try:
        f = open(path, 'rb')
        f.close()
        return True
    except OSError:
        return False


def serve_file(conn, path):
    path = path.split('?')[0].split('#')[0]
    if path == '/' or path == '':
        path = '/' + DASHBOARD_FILE
    local = path.lstrip('/')
    ext = local.rsplit('.', 1)[-1].lower() if '.' in local else ''

    # Only hand out dashboard files, never the .py files or secrets
    allowed = ext in CONTENT_TYPES and '..' not in local
    if not allowed or not file_exists(local):
        conn.sendall(b'HTTP/1.0 404 Not Found\r\nConnection: close\r\n\r\nNot found')
        return

    header = 'HTTP/1.0 200 OK\r\nContent-Type: %s\r\nConnection: close\r\n' % CONTENT_TYPES[ext]
    if ext != 'html':
        header += 'Cache-Control: max-age=86400\r\n'
    conn.sendall((header + '\r\n').encode())
    # 4 KB chunks: chart.umd.js is about 208 KB, and 1 KB reads made the
    # first page load noticeably slow.
    buf = bytearray(4096)
    with open(local, 'rb') as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            conn.sendall(buf[:n] if n < len(buf) else buf)


def ws_handshake(conn, headers):
    key = headers.get('sec-websocket-key', '')
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept_key = binascii.b2a_base64(hashlib.sha1((key + magic).encode()).digest())[:-1].decode()
    conn.sendall((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: %s\r\n\r\n" % accept_key
    ).encode())


def send_ws_message(conn, msg):
    payload = msg.encode('utf-8')
    length = len(payload)
    if length < 126:
        header = bytes([0x81, length])
    else:
        # Longer messages need the extended length field
        header = bytes([0x81, 126, (length >> 8) & 0xFF, length & 0xFF])
    conn.sendall(header + payload)


def handle_new_connection(conn):
    """Serve a page/file, or return the socket if it is a WebSocket upgrade."""
    conn.settimeout(3)
    try:
        raw = read_request(conn)
        path, headers = parse_request(raw)
        if headers.get('upgrade', '').lower() == 'websocket':
            ws_handshake(conn, headers)
            conn.settimeout(2)
            return conn
        serve_file(conn, path)
    except Exception as e:
        print("request error:", e)
    try:
        conn.close()
    except Exception:
        pass
    return None


# ---------- main loop ----------
def run():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('', 80))
    server.listen(5)

    poller = select.poll()
    poller.register(server, select.POLLIN)

    ws = None
    log_file = None
    waves = []
    bpm = 0
    spo2 = 0
    loop_count = 0

    def close_ws():
        nonlocal ws, log_file
        if ws:
            try:
                poller.unregister(ws)
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass
            ws = None
        if log_file:
            try:
                log_file.close()
                print("log file saved")
            except Exception:
                pass
            log_file = None

    print("Web server live! Waiting for browser...")
    while True:
        # 1. Network: new connections and messages from the open WebSocket.
        #    Pages keep being served while data streams, so a reload or a
        #    font request no longer hangs.
        for item in poller.poll(0):
            obj, event = item[0], item[1]  # MicroPython tuples can be longer than 2
            if obj is server:
                try:
                    conn, addr = server.accept()
                except OSError:
                    continue
                new_ws = handle_new_connection(conn)
                if new_ws:
                    close_ws()  # only one live viewer at a time
                    ws = new_ws
                    poller.register(ws, select.POLLIN)
                    print("Browser connected from", addr[0], "- streaming")
                    if LOG_TO_FILE:
                        log_file = open('session_log.csv', 'w')
                        log_file.write("Red_Raw, IR_Raw, SpO2, BPM, LED_HEX\n")
            elif obj is ws:
                closed = event & (select.POLLHUP | select.POLLERR)
                if not closed:
                    try:
                        data = ws.recv(128)
                        # empty read = gone, opcode 0x8 = close frame
                        closed = (not data) or (data[0] & 0x0F) == 0x8
                    except OSError:
                        closed = True
                if closed:
                    print("Browser disconnected")
                    close_ws()

        # 2. Sensor: keep reading even with no browser attached, so the
        #    FIFO never overflows and the filter is warm when one connects.
        try:
            sensor.check()
            while sensor.available():
                red_val = int(sensor.pop_red_from_storage() * VIRTUAL_ATTENUATION_RED)
                ir_val = int(sensor.pop_ir_from_storage() * VIRTUAL_ATTENUATION_IR)
                processor.add_sample(red_val, ir_val)
                wave, bpm, spo2 = processor.process()
                if ws:
                    waves.append(wave)
                if log_file:
                    log_file.write("%d, %d, %s, %s, %s\n" % (red_val, ir_val, spo2, bpm, hex(processor.current_led_hex)))
        except Exception as e:
            print("Error reading sensor:", e)

        # 3. Stream everything collected since the last send
        if ws and waves:
            msg = json.dumps({
                "wave": waves[-1],
                "waves": waves,
                "bpm": bpm,
                "spo2": spo2,
                "finger": processor.finger,
            })
            waves = []
            try:
                send_ws_message(ws, msg)
            except OSError:
                print("Client dropped connection. Closing stream.")
                close_ws()
        elif not ws:
            waves = []

        time.sleep_ms(20)
        loop_count += 1
        if loop_count >= 100:
            loop_count = 0
            gc.collect()


check_dashboard_files()
connect_wifi()
run()
