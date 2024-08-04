print("main.py")

from machine import Pin, TouchPad
import time

TOUCH_THRESHOLD = 120

class Engine:

    def __init__(self):
        pass

    def up(self):
        pass

    def down(self):
        pass

class RotationSensor:

    def __init__(self) -> None:
        # Position of the winder in "num of rotations".
        # - Must be stored at power loss
        # - Must be settable to the real value that is later computed from measurements
        # TODO: Same benchmark that is later used to compute expected time needed for reaching some position
        self._position = 0.0

    def wait_for_sync_position(self):
        """
        Wait for the next magnet in order to have a perfectly synchronized position.
        Should throw an expection if this takes too long.
        """
        pass

    def wait_for_full_rotation(self):
        """
        Wait until a full rotation has been made. This should be only started if currently at a sync point.
        If not, this might be inaccurate.
        """
        pass


class SpiralModel:

    def __init__(self) -> None:
        pass

# Convert position in % to num rotations

# 25, 33, 32

# motor direction 1
mdir1 = Pin(25, Pin.OUT)

# motor direction 2
mdir2 = Pin(33, Pin.OUT)


# Magnet causes 0 -> 1 transition
hall_sensor = Pin(32, Pin.IN, Pin.PULL_UP)
hall_sensor.irq(lambda e: print(e.value()), trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING)


touch1 = TouchPad(Pin(15, Pin.IN))
touch2 = TouchPad(Pin(4, Pin.IN))


while True:
    if touch1.read() < TOUCH_THRESHOLD:
        mdir1.on()
        mdir2.off()
    elif touch2.read() < TOUCH_THRESHOLD:
        mdir1.off()
        mdir2.on()
    else:
        mdir1.off()
        mdir2.off()
    time.sleep(0.1)