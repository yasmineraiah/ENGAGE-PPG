import network, time, rp2
rp2.country('GB')

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

print("Networks found:")
for net in wlan.scan():
    print(net[0].decode(), "channel", net[2], "signal", net[3])

wlan.connect("YOUR_WIFI_NAME", "YOUR_PASSWORD")

for i in range(20):
    status = wlan.status()
    if status == 3:
        print("Connected!", wlan.ifconfig())
        break
    if status < 0:
        break
    time.sleep(1)

print("Status:", wlan.status())