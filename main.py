print("main.py")

from machine import Pin, TouchPad
import time

from esp32 import NVS

# An ADC value read from a touch sensor indicates that the button was pressed.
TOUCH_ADC_THRESHOLD = 300

# Duration of how long a button needs to be pressed for
# causing a press event to be fired.
BUTTON_PRESS_EVENT_THRESHOLD_MS = 200

# The logic level that indicated that the hall sensor is above a magnet.
ABOVE_MAGNET_LOGIC_LEVEL = 0

# The logic level that indicates that the hall sensor is between two magnets.
NOT_ABOVE_MAGNET_LOGIC_LEVEL = int(ABOVE_MAGNET_LOGIC_LEVEL == 0)

# Total number of magnets evenly distributed on a circle.
NUM_MAGNETS = 4


class Settings:
    NUMBER_OF_TOTAL_STEPS_KEY = "R"

    def __init__(self) -> None:
        self._nvs = NVS("settings")
        try:
            self._number_of_total_steps_cached = self._nvs.get_i32(
                Settings.NUMBER_OF_TOTAL_STEPS_KEY
            )
        except OSError:
            self._number_of_total_steps_cached = None

    def reset(self):
        self._nvs.erase_key(Settings.NUMBER_OF_TOTAL_STEPS_KEY)
        self._number_of_total_steps_cached = None
        self._nvs.commit()

    def number_of_total_steps(self) -> int | None:
        return self._number_of_total_steps_cached

    def set_number_of_total_steps(self, val: int):
        self._nvs.set_i32(Settings.NUMBER_OF_TOTAL_STEPS_KEY, val)
        self._number_of_total_steps_cached = val
        self._nvs.commit()


class Blind:
    """
    The engine that is driving the belt for moving the blind up and down.
    TODO: Add support for the enable pin to reduce power consumption.
    """

    def __init__(self, pin_a: Pin, pin_b: Pin, inverted: bool):
        if inverted:
            self._pin_a = pin_a
            self._pin_b = pin_b
        else:
            self._pin_a = pin_b
            self._pin_b = pin_a

    def up(self):
        """
        Start moving the blind up.
        """
        self._pin_a.on()
        self._pin_b.off()

    def down(self):
        """
        Start moving the blind down.
        """
        self._pin_a.off()
        self._pin_b.on()

    def stop(self):
        """
        Stop the movement.
        This is safe to be called multiple times.
        """
        self._pin_a.off()
        self._pin_b.off()


class RotationSensor:
    """
    The sensor that measures the rotation of the engine that is winding the belt.
    We are using a hall sensor that is able to sense magnets that have been mounted
    to the moving part that is winding the belt.
    """

    def __init__(self, hall_pin: Pin) -> None:
        self._last_irq_ts = time.ticks_ms()
        self._relativ_position = 0
        self._hall_pin = hall_pin
        self._current_level = self._hall_pin.value()
        self._hall_pin.irq(
            lambda e: self._pin_irq(e.value()), trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING
        )

    def _pin_irq(self, new_value):
        irq_ts = time.ticks_ms()
        since_last_irq = time.ticks_diff(irq_ts, self._last_irq_ts)
        self._last_irq_ts = irq_ts

        self._last_irq_ts = irq_ts
        print(f"{new_value=}, {irq_ts=}")
        self._current_level = new_value

    def is_in_sync_position(self) -> bool:
        """
        Whether we are currently located above a magnet.
        """
        return self._hall_pin.value() == ABOVE_MAGNET_LOGIC_LEVEL

    def reset_relativ_position(self):
        self._relativ_position = 0

    def get_relative_position(self) -> int:
        return self._relativ_position

    def wait_for_sync_position(self, timeout_ms: int) -> bool:
        """
        Wait for the next magnet in order to have a perfectly synchronized position.
        A magnet can be detected by a rising edge. If we get a rising edge, our sensor is
        above a magnet.
        - However, we do not know on which edge of the magnet:
        Independent of the rotation direction we know that we moved 1/N * 360deg
        when we observer a falling edge and than a rising edge (next sync point).
        - We do not know if we are already on a sync point:
        I guess we should be allowed to assume that the system is not changing the state
        without us being the reason for the change. Probably we need to consider drift causing
        small belt movements etc.
        """
        start_ts = time.ticks_ms()
        start_level = self._current_level

        # If we started on a magnet, we first need to wait until we are not above a magnet anymore.
        if start_level == ABOVE_MAGNET_LOGIC_LEVEL:
            while True:
                ts = time.ticks_diff(time.ticks_ms(), start_ts)
                if ts > timeout_ms:
                    return False
                if self._current_level == NOT_ABOVE_MAGNET_LOGIC_LEVEL:
                    break

        # Now we are not on a magnet anymore, so we wait until we see a magnet again.
        while True:
            ts = time.ticks_diff(time.ticks_ms(), start_ts)
            if ts > timeout_ms:
                return False
            if self._current_level == ABOVE_MAGNET_LOGIC_LEVEL:
                return True


class ButtonEvent:
    """
    The different events that can be fired by pressing buttons and combinations of these.
    """

    NONE = 0
    UP = 1
    DOWN = 2
    BOTH = 3


class Buttons:
    """
    The buttons that can be used to control the belt winder.
    """

    def __init__(self, up_touch: TouchPad, down_touch: TouchPad) -> None:
        self._up = up_touch
        self._down = down_touch
        self._start_up_ts = None
        self._start_down_ts = None

    def poll_button_event(self) -> int:
        """
        Check if there is any new button event. This function must be called periodically.
        """

        # Read the button states and if pressed note down the ts when we first registered
        # the event.
        ts = time.ticks_ms()
        if self._up.read() < TOUCH_ADC_THRESHOLD:
            if self._start_up_ts is None:
                self._start_up_ts = ts
        else:
            self._start_up_ts = None

        if self._down.read() < TOUCH_ADC_THRESHOLD:
            if self._start_down_ts is None:
                self._start_down_ts = ts
        else:
            self._start_down_ts = None

        # print(f"{self._start_up_ts=} {self._start_down_ts=}")

        # Check if the currently registered presses exceeded the debounce thresholds, and,
        # if yes, fire an event.
        if self._start_up_ts is not None and self._start_down_ts is None:
            if time.ticks_diff(ts, self._start_up_ts) > BUTTON_PRESS_EVENT_THRESHOLD_MS:
                return ButtonEvent.UP
        elif self._start_up_ts is None and self._start_down_ts is not None:
            if (
                time.ticks_diff(ts, self._start_down_ts)
                > BUTTON_PRESS_EVENT_THRESHOLD_MS
            ):
                return ButtonEvent.DOWN
        elif self._start_up_ts is not None and self._start_down_ts is not None:
            if (
                time.ticks_diff(ts, self._start_up_ts) > BUTTON_PRESS_EVENT_THRESHOLD_MS
                and time.ticks_diff(ts, self._start_down_ts)
                > BUTTON_PRESS_EVENT_THRESHOLD_MS
            ):
                return ButtonEvent.BOTH

        return ButtonEvent.NONE

settings = Settings()

# motor direction pin 1
mdir1 = Pin(25, Pin.OUT)
# motor direction pin 2
mdir2 = Pin(33, Pin.OUT)
# The blind (engine)
blind = Blind(mdir1, mdir2, False)

hall_sensor = Pin(32, Pin.IN, Pin.PULL_UP)
rotation_sensor = RotationSensor(hall_sensor)

touch1 = TouchPad(Pin(15, Pin.IN))
touch2 = TouchPad(Pin(4, Pin.IN))
buttons = Buttons(touch1, touch2)

def basic_mode_loop():
    while True:
        button_event = buttons.poll_button_event()

        if button_event == ButtonEvent.UP:
            print("up")
            ts = time.ticks_ms()
            print(f"start {ts=}")
            blind.up()
            ret = rotation_sensor.wait_for_sync_position(8000)
            # todo: move down if this fails, as well as in the case below
            ts = time.ticks_ms()
            print(f"stop {ts=} {ret=}")

        elif button_event == ButtonEvent.DOWN:
            print("down")
            ts = time.ticks_ms()
            print(f"start {ts=}")
            blind.down()
            ret = rotation_sensor.wait_for_sync_position(3000)
            ts = time.ticks_ms()
            print(f"stop {ts=} {ret=}")
        elif button_event == ButtonEvent.BOTH:
            blind.stop()
            break
        else:
            blind.stop()

def move_up_until_blocked_and_count_steps():
    # calibrate
    steps = 0
    up_time_offset = 0
    endpos_on_magnet = False

    blind.up()
    while True:
        ret = rotation_sensor.wait_for_sync_position(8000)
        if ret:
            steps += 1
            print(f"{steps=}")
        else:
            endpos_on_magnet = rotation_sensor.is_in_sync_position()
            blind.down()
            rotation_sensor.wait_for_sync_position(3000)
            if endpos_on_magnet:
                blind.up()
                rotation_sensor.wait_for_sync_position(8000)
            blind.stop()
            break

    print(f"{steps=}")
    return steps

def advanced_mode_loop():
    stop_position = settings.number_of_total_steps()
    assert stop_position is not None

    # Make sure we are at a know position by moving the blind up until it is blocked.
    #
    # Alternatively, this could be solved by storing the last known position
    # in the settings. However, this value would be written each time the blind
    # is operated, but only read rarely. Not sure whether this is worth writing
    # that much to the flash memory.
    move_up_until_blocked_and_count_steps()

    # We are now at the top postion.
    current_position = stop_position

    while True:
        # TODO: Add support for events coming via MQTT.
        button_event = buttons.poll_button_event()

        # TODO: Support for incremental movements.
        if button_event == ButtonEvent.UP:
            if current_position == 0:
                blind.up()
                while True:
                    ret = rotation_sensor.wait_for_sync_position(8000)
                    if ret:
                        current_position += 1
                        print(f"{current_position=}")
                    else:
                        print("Failed up")
                        blind.stop()
                        while True:
                            pass
                    if current_position == stop_position:
                        blind.stop()
                        break
        elif button_event == ButtonEvent.DOWN:
            if current_position == stop_position:
                blind.down()
                while True:
                    ret = rotation_sensor.wait_for_sync_position(3000)
                    if ret:
                        current_position -= 1
                        print(f"{current_position=}")
                    else:
                        print("Failed down")
                        blind.stop()
                        while True:
                            pass
                    if current_position == 0:
                        blind.stop()
                        break
        else:
            blind.stop()

number_of_total_steps = settings.number_of_total_steps()
print(f"{number_of_total_steps=}")

if number_of_total_steps is None:
    basic_mode_loop()
    # if the basic mode is exited, the user request calibration.
    # Thus, we now count the number of steps required until the blind
    # is fully open/closed.
    number_of_total_steps = move_up_until_blocked_and_count_steps()
    settings.set_number_of_total_steps(number_of_total_steps)

# If we know the number of steps required to close/open the blind we can
# enter the advanced mode.
advanced_mode_loop()
