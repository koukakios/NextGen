import numpy as np
import matplotlib.pyplot as plt
import scipy as scp

def plotting_signal(duration, y, title):
    plt.figure(figsize=(10,5))
    x = np.linspace(0, duration, len(y))
    plt.plot(x,y)
    plt.title(title)
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.show()

def plotting_freq(duration, y, title):
    fs = 16000
    y = y - np.mean(y) #remove the DC component
    Y = np.fft.rfft(y)
    Y = Y / np.max(abs(Y))
    plt.figure(figsize=(10,5))
    x = np.fft.rfftfreq(len(y), d=1 / fs)
    plt.plot(x ,abs(Y))
    plt.title(title)
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Amplitude")
    plt.show()

def plotting_spectrogram(duration, y, title):
    eps = 1e-20
    f, t, Sxx = scp.signal.spectrogram(y, fs=16000, window='hann', nperseg=512, noverlap = 256)
    plt.figure(figsize=(10,5))
    plt.pcolormesh(t, f, 10*np.log10(Sxx + eps))
    plt.colorbar(label = 'Power/Frequency (dB/Hz)')
    plt.xlabel('Time (s)')
    plt.ylabel('Frequency (Hz)')
    plt.title('Spectrogram')
    plt.show()