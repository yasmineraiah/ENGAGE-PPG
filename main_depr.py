import network
import socket
import time
import math
import json
import secrets
import gc
import hashlib
import binascii

# simulated sensor value, uses a sine wave with added noise 
def get_sensor_val():
    return math.sin(time.ticks_ms() / 200) + ((time.ticks_us() % 10) / 50.0)


def send_ws_message(conn, msg):
    payload = msg.encode('utf-8')
    length = len(payload)
    header = bytearray([0x81, length])
    conn.sendall(header + payload)
    # sends the frame header and payload to the websocket connection


def start_server():
    # tcpip socket to listen for incoming connections on port 80
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(5)

    # timeout loop for accepting connections 
    s.settimeout(0.2)

    print("web server live! waiting for browser...")

    while True:
        conn = None
        try:
            # wait for a browser to connect 
            conn, addr = s.accept()
            conn.settimeout(None)

            request = conn.recv(1024).decode('utf-8')

            # check if the browser is asking to upgrade to a websocket connection
            if 'Upgrade: websocket' in request:
                key = request.split('Sec-WebSocket-Key: ')[1].split('\r\n')[0]
                magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                accept_key = binascii.b2a_base64(
                    hashlib.sha1((key + magic).encode()).digest()
                )[:-1].decode()

                # accept the websocket connection
                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
                )
                conn.sendall(response.encode('utf-8'))
                print("WebSocket connected!")

                # process and send realtime data 
                frame_count = 0
                while True:
                    # push data as json to the browser every 50 ms
                    data = json.dumps({"value": get_sensor_val()})
                    send_ws_message(conn, data)
                    time.sleep_ms(50)

                    # garbage collect so pico's ram doesnt fill up
                    frame_count += 1
                    if frame_count >= 100:
                        gc.collect()
                        frame_count = 0

            # standard http request, send the index.html in chunks 
            else:
                conn.sendall(
                    'HTTP/1.0 200 OK\r\nContent-type: text/html\r\nConnection: close\r\n\r\n'.encode('utf-8')
                )
                with open('index.html', 'rb') as f:
                    while True:
                        chunk = f.read(512)
                        if not chunk:
                            break
                        conn.sendall(chunk)

            conn.close()
        # manage closed connections
        except OSError:
            pass
        except Exception as e:
            print("Connection closed or dropped:", e)
            if conn:
                try:
                    conn.close()
                except:
                    pass
            gc.collect()


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)

    # reset the radio in case a previous run left it in a bad state
    wlan.active(False)
    time.sleep(0.5)
    wlan.active(True)

    wlan.connect(getattr(secrets, "WIFI_NAME"), getattr(secrets, "WIFI_PASSWORD"))

    print("connecting to wifi...")
    max_wait = 20
    while max_wait > 0:
        status = wlan.status()
        if status < 0 or status >= 3:
            break
        max_wait -= 1
        print("waiting for connection... status =", status)
        time.sleep(1)

    if wlan.status() != 3:
        raise RuntimeError('network connection failed, status=%s' % wlan.status())

    ip_address = wlan.ifconfig()[0]
    print(f"connected to wifi! IP address: {ip_address}")
    return wlan


# boot sequence
connect_wifi()
start_server()