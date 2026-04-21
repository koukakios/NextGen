#!/usr/bin/env python
##################################################################################
# UnicornGiga
# Read Unicorn Hybrid Black over bluetooth. Send signal over serial port to
# Arduino Giba
# Robert Oostenveld, Bori Hunyadi, Leon Abelmann. March 2025
#
# Copyright (C) 2022 Robert Oostenveld
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
###################################################################################

import serial  # python package pyserial (pip install pyserial)
import struct
import string
import random
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import time

import winsound

import winsound # Only for Windows OS

matplotlib.use("TkAgg")  # needed so that it can be visualized in pycharm

from pylsl import StreamInfo, StreamOutlet
from scipy.signal import butter, lfilter

# For threading
import queue
import threading

# Ports used.
# unicorn_device = '/dev/tty.UN-20230623' # Mac OSX type
# arduino_device = '/dev/cu.usbmodem2101' #
unicorn_device = 'COM6'  # Windows OS type
arduino_device = 'COM7'

# Unicorn acquisition settings
blocksize = 0.2
timeout = 5
nchan = 16
nchan_eeg = 8
fsample = 250
buffer_len = 10

# filter settings
order = 5
low = 1 / (fsample / 2)
high = 20 / (fsample / 2)
b, a = butter(order, [low, high], btype='bandpass')

# Communication with unicorn
start_acq = [0x61, 0x7C, 0x87]
stop_acq = [0x63, 0x5C, 0xC5]
start_response = [0x00, 0x00, 0x00]
stop_response = [0x00, 0x00, 0x00]
start_sequence = [0xC0, 0x00]
stop_sequence = [0x0D, 0x0A]

# EEG buffers
eeg_buffer = np.zeros(shape=(buffer_len * fsample, nchan_eeg), dtype=float)
eegfilt_buffer = np.zeros(shape=(buffer_len * fsample, nchan_eeg), dtype=float)


##############################################################################
# Play_beep
# Play a beep sound with the given frequency (Hz) and duration (ms). """
# Only works for Windows
def play_beep(frequency=1000, duration=500):
    winsound.Beep(frequency, duration)


##############################################################################
# detect_blink()
# Detect eye blink on unicorn. Returns True if input exceeds background
# input      : data sequence
# background : background level
# No clue what happens here, Leon
##############################################################################
def detect_blink(input, background):
    blink = False
    r = np.zeros(nchan_eeg)
    for ch in range(nchan_eeg):
        std_input = np.std(input[:, ch])
        std_bgr = np.std(background[:, ch])
        r[ch] = std_input / std_bgr
    if (r[0] > 2 and all(x <= 2 for x in r[1:])):
        blink = True
    return blink


##############################################################################
# write_read(x)
# Send byte (char) sequence to Arduino Giga
# To be done: Readback does not work when unicorn is connected. Do we need
# a thread as well for the Arduino? Leon, Feb 2025
##############################################################################
def write_read(x):
    print(x)
    try:
        arduino.write(bytes(x, 'utf-8'))
    except:
        print("arduino write failed")
    return


##############################################################################
# serial_read(s)
# Read item from serial port, byte per byte and store into queue
##############################################################################
unicorn_queue = queue.Queue(10000)


def serial_read(s):
    while True:
        item = s.read(1);
        #        print("read : ", item, "of type : ", type(item))
        unicorn_queue.put(item)


##############################################################################
# read_block_from_queue()
# return one block of data of 45 bytes from the queue
# check for sanity
# possiblity to read battery status
##############################################################################
def read_block_from_queue():
    payload = b''

    for i in range(45):
        # print("reading byte ", i, "Queue size: ", unicorn_queue.qsize())
        item = unicorn_queue.get()
        # print(item, type(item))
        payload = payload + item

    # print("Payload[0:2]   : ",payload[0:2])
    # print("Payload[43:45] : ",payload[43:45])

    # check the start and end bytes
    if payload[0:2] != b'\xC0\x00':
        raise RuntimeError("invalid packet")
    if payload[43:45] != b'\x0D\x0A':
        raise RuntimeError("invalid packet")

    battery = 100 * float(payload[2] & 0x0F) / 15
    # print("Battery : ", battery)
    return payload


##############################################################################
# unpack(payload)
# Unpack block of data from unicorn and return the filtered EEG signal
# returns a counter that acts like a clock
##############################################################################
def unpack(payload):
    global eeg_buffer
    global eegfilt_buffer

    eeg = np.zeros(8)
    for ch in range(0, 8):
        # unpack as a big-endian 32 bit signed integer
        eegv = struct.unpack('>i', b'\x00' + payload[(3 + ch * 3):(6 + ch * 3)])[0]
        # apply two’s complement to the 32-bit signed integral value if the sign bit is set
        if (eegv & 0x00800000):
            eegv = eegv | 0xFF000000
        eeg[ch] = float(eegv) * 4500000. / 50331642.

    accel = np.zeros(3)
    # unpack as a little-endian 16 bit signed integer
    accel[0] = float(struct.unpack('<h', payload[27:29])[0]) / 4096.
    accel[1] = float(struct.unpack('<h', payload[29:31])[0]) / 4096.
    accel[2] = float(struct.unpack('<h', payload[31:33])[0]) / 4096.

    gyro = np.zeros(3)
    # unpack as a little-endian 16 bit signed integer
    gyro[0] = float(struct.unpack('<h', payload[27:29])[0]) / 32.8
    gyro[1] = float(struct.unpack('<h', payload[29:31])[0]) / 32.8
    gyro[2] = float(struct.unpack('<h', payload[31:33])[0]) / 32.8

    counter = struct.unpack('<L', payload[39:43])[0]

    battery = 100 * float(payload[2] & 0x0F) / 15
    # print("Battery : ", battery)

    # collect the data that will be sent to LSLii
    dat[0:8] = eeg
    dat[8:11] = accel
    dat[11:14] = gyro
    dat[14] = battery
    dat[15] = counter

    # send the data to LSL
    outlet.push_sample(dat)

    # fill EEG buffer
    eegdat = eeg[:, np.newaxis]
    eeg_buffer = np.r_[eeg_buffer[1:buffer_len * fsample, :], eegdat.transpose()]
    del eegdat

    # filter
    clean = np.zeros(8)
    clean = clean[:, np.newaxis]
    for ch in range(nchan_eeg):
        x = eeg_buffer[-2 * order - 1:, ch]
        y = np.inner(np.flip(b), x) - np.inner(np.flip(a[1:]), eegfilt_buffer[-2 * order:, ch])
        clean[ch] = y
    eegfilt_buffer = np.r_[eegfilt_buffer[1:2500, :], clean.transpose()]
    return counter


##############################################################################
# update_plot(eegfilt_buffer,fig,axs)
#
##############################################################################
def update_plot(eegfilt_buffer, fig, axs):
    for i, ax in enumerate(axs.flat):
        # Update existing plot lines if they exist
        if len(ax.lines) > 0:
            ax.lines[0].set_data(np.arange(0, buffer_len * fsample, 1), eegfilt_buffer[:, i])
        else:
            ax.plot(np.arange(0, buffer_len * fsample, 1), eegfilt_buffer[:, i], color='C0')
        if i != len(axs.flat) - 1:
            ax.set_xticklabels([])
        ax.set_frame_on(0)
        ax.relim()
        ax.autoscale_view()

        if i == len(axs.flat) - 1:
            ax.set_xlabel('Time (s)')
            ax.set_xticks(np.arange(0, buffer_len * fsample + 1, fsample))
            ax.set_xticklabels(np.arange(0, buffer_len * fsample + 1, fsample) / fsample)

    fig.canvas.draw_idle()
    fig.canvas.flush_events()
    return


# establish connections
try:
    unicorn = serial.Serial(unicorn_device, 115200, timeout=timeout)
    print("connected to unicorn at serial port " + unicorn_device)
except:
    raise RuntimeError("cannot connect to unicron at port " + unicorn_device)

arduino_found = False
try:
    arduino = serial.Serial(port=arduino_device,
                            baudrate=115200, timeout=.1)
    print("connected to unicorn at serial port " + unicorn_device)
    arduino_found = True
except:
    print("cannot connect to arduino at port %s, continuing without Arduino" % (arduino_device))

# Why do we use an LSL stream? Leon
lsl_name = 'Unicorn'
lsl_type = 'EEG'
lsl_format = 'float32'
lsl_id = ''.join(random.choice(string.digits) for i in range(6))

# create an outlet stream
info = StreamInfo(lsl_name, lsl_type, nchan, fsample, lsl_format, lsl_id)
outlet = StreamOutlet(info)

print('started LSL stream: name=%s, type=%s, id=%s' % (lsl_name, lsl_type, lsl_id))

# start the Unicorn data stream, try 10 times
# print("Start datastream")
unicorn.write(start_acq)
try:
    response = unicorn.read(3)
except:
    raise RuntimeError('Cannot connect to unicorn')
if (response == b'\x00\x00\x00'):
    unicorn_thread = threading.Thread(target=serial_read, args=(unicorn,), ).start()
    print('started communication with Unicorn')
else:
    raise RuntimeError('could not start communication with Unicorn')

# initialize plotting
plt.ion()
fig, axs = plt.subplots(ncols=1, nrows=nchan_eeg, figsize=(12, 10), layout="constrained")

# Main loop:
try:
    print("Terminate with ^C")
    while True:

        dat = np.zeros(nchan)

        # read one block of data from the queue
        payload = read_block_from_queue()
        # print("payload : ", payload)

        # Unpack payload into EEG buffers
        counter = unpack(payload)

        # update plot and check for blink every half seconds
        if ((counter % 125) == 0):
            # print('eeg buffer 1 value  %f' % (eegfilt_buffer[1,1]))
            tstart = time.time()
            update_plot(eegfilt_buffer, fig, axs)

            # detect blink and play sound
            blink = detect_blink(eegfilt_buffer[-125:, :], eegfilt_buffer[-500:-125, :])

            if blink:
                print("Blink!")
                # play_beep()
                if (arduino_found):
                    write_read('42')

except:
    print('closing')
    unicorn.write(stop_acq)
    unicorn.close()
    del outlet

