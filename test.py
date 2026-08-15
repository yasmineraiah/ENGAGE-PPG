import machine 
import time 

led = machine.Pin("LED", machine.Pin.OUT)

print("Blinking started, press stop to end")

while True:
    led.toggle()
    time.sleep(0.5)
    
