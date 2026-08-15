import machine 
import time 

i2c = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=100000)

print("scanning i2c bus...")
time.sleep(1)

devices = i2c.scan()

if len(devices) == 0:
    print("no i2c devices found")
else:
    print(f"i2c device found : {len(devices)} ")
    for device in devices:
        print (f"device address : {hex(device)}")
