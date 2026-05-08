from keras.src.saving import load_model
import Mic_processing
import plotting
import EMG_process
# my_mic = Mic_processing.Mic(data = 0, fs = 16_000, port ='/dev/cu.usbmodem101', baud = 1_000_000, samples=32_000)
# my_mic.model = load_model('model1.keras')
#
# my_mic = Mic_processing.Mic(data=0, fs=16_000, port='/dev/cu.usbmodem101', baud=1_000_000, samples=32_000)
# my_mic.model = load_model('model1.keras')
#
# print("Listening...")
#
# while True:
#     try:
#         # Notice we only pass samples now!
#         my_mic.get_mic_data(samples=32_000)
#
#         my_mic.data = my_mic.pre_processing(my_mic.data)
#         my_mic.predict(my_mic.data)
#         print(my_mic.output)
#
#     except KeyboardInterrupt:  # Pressing Ctrl+C stops the loop cleanly
#         print("\nClosing connection...")
#         my_mic.serial_conn.close()
#         break


mic_out = True


my_emg = EMG_process.EMG(data = 0, mode=(0, 0, 0), port ='/dev/cu.usbmodem101', baud = 1000000, samples=100)
while True:
    if mic_out == False:
        break
    ye, duration = my_emg.get_emg_data(port='/dev/cu.usbmodem101', baud=1000000)
    my_emg.update_mode(ye)