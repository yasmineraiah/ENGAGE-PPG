import network
import time
import rp2

# Set to UK to ensure all channels are open
rp2.country('GB') 

print("Waking up Wi-Fi chip...")
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
time.sleep(1)

print("Scanning for available networks...")
networks = wlan.scan()

print(f"\n--- FOUND {len(networks)} NETWORKS ---")
for net in networks:
    ssid = net[0].decode('utf-8')
    rssi = net[3]  # Signal strength (closer to 0 is better)
    print(f"Name: '{ssid}' | Signal Strength: {rssi}")
print("------------------------------\n")