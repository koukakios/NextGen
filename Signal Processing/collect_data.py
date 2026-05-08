class CollectData:
    def __init__(self, fs_mic = 16_000, samples_emg = 100, fs_cam = 10, baud = 1_000_000, port = '/dev/cu.usbmodem101'):
        self.fs_mic = fs_mic
        self.samples_emg = samples_emg
        self.fs_cam = fs_cam
        self.baud = baud
        self.port = port
        self.data = None

        def get_data(self):




