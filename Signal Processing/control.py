import EMG_process
import Mic_processing
from signal_to_motor import signal_to_motor
from tensorflow.keras.models import load_model
import keyboard

my_emg = EMG_process.EMG(port='/dev/cu.usbmodem101', baud=1000000)
my_mic = Mic_processing.Mic(port='/dev/cu.usbmodem101', baud=1_000_000, samples=16_000)
my_mic.model = load_model('model1.keras')
uart = 0b000

while True:
    turning_mode = keyboard.is_pressed('t')

    #Mic part
    my_mic.get_mic_data()
    processed_data = my_mic.pre_processing(my_mic.data, fs=16_000, samples=16_000)
    my_mic.predict(processed_data, fs=16_000)
    my_mic.signal_mic_change()
    print(my_mic.mic_state)
    #EMG part
    data_emg, duration = my_emg.get_emg_data()
    my_emg.update_mode(data_emg)
    print(my_emg.mode)
    #cam part
    signal_cam = 0

    #to motor
    uart = signal_to_motor(my_mic.mic_state, my_emg.mode, signal_cam, turning_mode, uart)
    print(uart)



