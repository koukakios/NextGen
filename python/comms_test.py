import serial
import struct
import time
import threading

class WheelchairController:
    """
    Handles background serial communication to the Wheelchair MCU.
    Maintains a constant heartbeat to satisfy the hardware watchdog.
    """
    def __init__(self, port: str, baudrate: int = 115200, hz: int = 20):
        self.port = port
        self.baudrate = baudrate
        self.period = 1.0 / hz  # Default 20Hz = 50ms period
        
        self.serial_conn = None
        self.running = False
        self.comm_thread = None
        
        # Shared state variables
        self._v = 0.0
        self._w = 0.0
        self._lock = threading.Lock() # Mutex for thread safety

    def connect(self):
        """Opens the serial port and waits for the MCU to boot."""
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=0.1, write_timeout=0.1)
            print(f"Connected to {self.port} at {self.baudrate} baud.")
            
            # Mandatory: Wait for Arduino Giga bootloader/reset sequence
            time.sleep(2.0) 
            return True
        except serial.SerialException as e:
            print(f"CRITICAL: Serial Connection Failed. {e}")
            return False

    def start(self):
        """Spawns the background thread to continuously send data."""
        if not self.serial_conn or not self.serial_conn.is_open:
            raise RuntimeError("Must call connect() before start().")
            
        self.running = True
        self.comm_thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self.comm_thread.start()
        print("Communication thread started.")

    def set_velocity(self, v: float, w: float):
        """
        Updates the target velocities. 
        Thread-safe: Safely overwrites variables while the transmit loop reads them.
        """
        with self._lock:
            self._v = float(v)
            self._w = float(w)

    def _transmit_loop(self):
        """The core producer loop running in the background."""
        while self.running:
            loop_start = time.time()
            
            # 1. Safely copy the current targets
            with self._lock:
                current_v = self._v
                current_w = self._w
                
            # 2. Serialize Data (The ICD Contract)
            # <BffB = Little-Endian, UInt8, Float32, Float32, UInt8
            try:
                packet = struct.pack('<BffB', 0x02, current_v, current_w, 0x03)
                self.serial_conn.write(packet)
            except serial.SerialTimeoutException:
                print("WARNING: Serial write timeout. Is the buffer full?")
            except Exception as e:
                print(f"ERROR: Transmission failed: {e}")
                self.running = False
                break
                
            # 3. Deterministic sleep to maintain target frequency
            elapsed = time.time() - loop_start
            time_to_sleep = self.period - elapsed
            if time_to_sleep > 0:
                time.sleep(time_to_sleep)

    def stop(self):
        """Gracefully halts the wheelchair and closes the port."""
        print("Initiating shutdown sequence...")
        self.running = False
        
        if self.comm_thread:
            self.comm_thread.join(timeout=1.0)
            
        # Send one final zero-velocity packet to ensure immediate stop
        if self.serial_conn and self.serial_conn.is_open:
            try:
                stop_packet = struct.pack('<BffB', 0x02, 0.0, 0.0, 0.03)
                self.serial_conn.write(stop_packet)
                self.serial_conn.flush()
            except Exception as e:
                pass
            finally:
                self.serial_conn.close()
                print("Serial port closed safely.")

import time
from pynput import keyboard
# Assuming you saved the previous class in a file named 'wheelchair_comm.py'
# from wheelchair_comm import WheelchairController 

# --- Configuration ---
PORT = 'COM3'
V_MAX = 0.5  # Maximum linear velocity (m/s)
W_MAX = 0.5  # Maximum angular velocity (rad/s)

# State dictionary to track which keys are currently held down
active_keys = {
    'w': False,
    'a': False,
    's': False,
    'd': False
}

def on_press(key):
    try:
        char = key.char.lower()
        if char in active_keys:
            active_keys[char] = True
    except AttributeError:
        pass # Handle special keys (Shift, Ctrl, etc.) without crashing

def on_release(key):
    try:
        char = key.char.lower()
        if char in active_keys:
            active_keys[char] = False
    except AttributeError:
        pass
        
    if key == keyboard.Key.esc:
        # Stop listener and exit program
        return False

def main():
    # Initialize your hardware controller
    chair = WheelchairController(port=PORT, hz=20)
    
    if not chair.connect():
        return
        
    chair.start()
    
    # Start the keyboard listener in the background
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    
    print("\n" + "="*40)
    print("⌨️  TELEOP CONTROL ACTIVE")
    print("   W : Drive Forward")
    print("   S : Drive Reverse")
    print("   A : Turn Left")
    print("   D : Turn Right")
    print("   [ESC] : Emergency Stop & Exit")
    print("="*40 + "\n")

    try:
        # Main Control Loop runs at 20Hz (50ms)
        while listener.running:
            # 1. Calculate target velocities based on active keys
            # If W is True (1) and S is False (0), v = 1 * V_MAX = 0.5
            # If both are True (1 - 1), v = 0 (Cancels out safely)
            target_v = (active_keys['w'] - active_keys['s']) * V_MAX
            target_w = (active_keys['a'] - active_keys['d']) * W_MAX
            
            # 2. Send to the background transmission thread
            chair.set_velocity(target_v, target_w)
            
            # 3. Optional telemetry print (carriage return \r overwrites the line)
            print(f"Command -> v: {target_v:5.2f} m/s | w: {target_w:5.2f} rad/s", end='\r')
            
            time.sleep(0.05) 
            
    except KeyboardInterrupt:
        pass
    finally:
        print("\n\nShutting down teleop...")
        chair.stop()
        listener.stop()

if __name__ == "__main__":
    main()