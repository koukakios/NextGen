import serial
import struct
mic_state = False

def signal_mic_change(mic_word):
    if mic_word == 'on':
        mic_state = True
    elif mic_word == 'off':
        mic_state = False
    return


def signal_to_motor(mic_state, emg_mode, turn_dir, turning_mode = False, uart_old = 0b000):
    """
    Protocol: send 8 bits of data
    States:
    still - 000
    M1 - 001
    M2 - 010
    M3 - 011
    R - 100
    L - 101
    """
    if mic_state:
        uart = 0b000
        if emg_mode == (0,0,0): #still
            uart = 0b000
        elif emg_mode == (0,0,1): #mode 1
            uart = 0b001
        elif emg_mode == (0,1,0): #mode 2
            uart = 0b010
        elif emg_mode == (1,0,0): #mode 3
            uart = 0b011

        if turn_dir == "LEFT" and turning_mode == True: #turn left
            uart = 0b101
        elif turn_dir == "MIDDLE": #still
            uart = 0b000
        elif turn_dir == "RIGHT" and turning_mode == True: #turn right
            uart = 0b100
        return uart

    else: return uart_old

def send_data(port, data):
    ser = serial.Serial(port, 1_000_000, timeout=0)
    data += "\r\n"
    ser.write(data.encode())







