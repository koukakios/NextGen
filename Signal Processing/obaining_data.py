import Mic_processing
import plotting

my_mic = Mic_processing.Mic(data = 0, fs = 16000, port ='/dev/cu.usbmodem101', baud = 1000000, samples=32000)
my_mic.get_mic_data(port = '/dev/cu.usbmodem101', baud = 1000000, samples=32000)

plotting.plotting_freq(my_mic.duration, my_mic.data, title = "Frequency")
plotting.plotting_spectrogram(my_mic.duration, my_mic.data, title = "Spectrogram")