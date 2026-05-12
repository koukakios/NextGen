from __future__ import print_function
import cv2 as cv
import argparse


def detectAndDisplay(frame, face_cascade, eyes_cascade):
    frame_gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
    frame_gray = cv.equalizeHist(frame_gray)

    # -- Detect faces
    faces = face_cascade.detectMultiScale(frame_gray, scaleFactor=1.16, minNeighbors=6)
    for (x, y, w, h) in faces:
        center = (x + w // 2, y + h // 2)
        frame = cv.ellipse(frame, center, (w // 2, h // 2), 0, 0, 360, (255, 0, 255), 4)

        faceROI = frame_gray[y:y + h, x:x + w]
        # -- In each face, detect eyes
        """
        eyes = eyes_cascade.detectMultiScale(faceROI)
        for (x2, y2, w2, h2) in eyes:
            eye_center = (x + x2 + w2 // 2, y + y2 + h2 // 2)
            radius = int(round((w2 + h2) * 0.25))
            frame = cv.circle(frame, eye_center, radius, (255, 0, 0), 4)
        """

    cv.imshow('Capture - Face detection', frame)


parser = argparse.ArgumentParser(description='Code for Cascade Classifier tutorial.')
parser.add_argument('--face_cascade', help='Path to face cascade.',
                    default='data/haarcascades/haarcascade_frontalface_alt.xml')
parser.add_argument('--eyes_cascade', help='Path to eyes cascade.',
                    default='data/haarcascades/haarcascade_eye_tree_eyeglasses.xml')
parser.add_argument('--camera', help='Camera divide number.', type=int, default=0)
args = parser.parse_args()

#you need to download the classfiers xml files from here:
# https://media.geeksforgeeks.org/wp-content/uploads/20250415122920890394/harr_casscade_classifiers.zip
#then u need to extract the zip and change the paths below to the ones in your computer
face_cascade = cv.CascadeClassifier(r"C:\Users\kkouk\Desktop\haarcascade_frontalface_default.xml")
eyes_cascade = cv.CascadeClassifier(r"C:\Users\kkouk\Desktop\haarcascade_eye.xml")

camera_device = args.camera
# -- 2. Read the video stream
cap = cv.VideoCapture(camera_device)
if not cap.isOpened:
    print('--(!)Error opening video capture')
    exit(0)

while True:
    ret, frame = cap.read()
    if frame is None:
        print('--(!) No captured frame -- Break!')
        break

    detectAndDisplay(frame, face_cascade, eyes_cascade)

    if cv.waitKey(10) == 27:
        break