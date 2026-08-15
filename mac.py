import network
import binascii

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
mac = binascii.hexlify(wlan.config('mac'), ':').decode().upper()
print(f"My MAC Address is: {mac}")