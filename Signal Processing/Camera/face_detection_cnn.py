import cv2
import numpy as np

# Φόρτωση του μοντέλου (DNN Face Detector)
model_bin = r"C:\Users\kkouk\Downloads\res10_300x300_ssd_iter_140000.caffemodel"
config_text = r"C:\Users\kkouk\Downloads\deploy.prototxt.txt"
net = cv2.dnn.readNetFromCaffe(config_text, model_bin)

# Φόρτωση Dlib (LBF model για Landmarks)
facemark = cv2.face.createFacemarkLBF()
facemark.loadModel(r"C:\Users\kkouk\Downloads\lbfmodel.yaml")

cap = cv2.VideoCapture(0)

# --- ΡΥΘΜΙΣΗ ΕΥΑΙΣΘΗΣΙΑΣ (TWEAK THIS) ---
# 0.05 = Πολύ ευαίσθητο (αλλάζει σε Left/Right με την παραμικρή κίνηση)
# 0.06 = Ισορροπημένο (Καλή αρχική ρύθμιση)
# 0.15 = Πολύ "χαλαρό" (κολλάει στο MIDDLE, όπως πριν)
DEADZONE_RATIO = 0.06

while True:
    ret, frame = cap.read()
    if not ret:
        break

    h, w = frame.shape[:2]

    # Προετοιμασία εικόνας για το νευρωνικό (blob)
    blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), (104.0, 177.0, 123.0))
    net.setInput(blob)
    detections = net.forward()

    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]
        if confidence > 0.5:  # Threshold για την εγκυρότητα
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            (startX, startY, endX, endY) = box.astype("int")

            # Περιορισμός συντεταγμένων στα όρια της εικόνας για αποφυγή crash
            startX, startY = max(0, startX), max(0, startY)
            endX, endY = min(w, endX), min(h, endY)

            # Ακύρωση αν το κουτί βγει εκτός λογικών ορίων
            if startX >= endX or startY >= endY:
                continue

            cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0), 2)

            # Υποχρεωτική χρήση np.int32 για να μην κρασάρει η facemark.fit
            faces = np.array([[startX, startY, endX - startX, endY - startY]], dtype=np.int32)
            ok, landmarks = facemark.fit(frame, faces)

            if ok:
                for marks in landmarks:
                    # Το σημείο 30 είναι η άκρη της μύτης
                    nose_x = marks[0][30][0]
                    nose_y = marks[0][30][1]

                    # Σχεδίαση μύτης
                    cv2.circle(frame, (int(nose_x), int(nose_y)), 3, (0, 0, 255), -1)

                    # --- ΥΠΟΛΟΓΙΣΜΟΣ ΚΑΤΕΥΘΥΝΣΗΣ ΜΕ ΡΥΘΜΙΖΟΜΕΝΟ ΠΕΡΙΘΩΡΙΟ ---
                    face_width = endX - startX
                    face_center_x = startX + (face_width / 2)

                    # Υπολογισμός του deadzone με βάση το ratio
                    margin = face_width * DEADZONE_RATIO

                    if nose_x < (face_center_x - margin):
                        position = "RIGHT"
                        color = (255, 0, 0)  # Μπλε κείμενο για αριστερά
                    elif nose_x > (face_center_x + margin):
                        position = "LEFT"
                        color = (0, 0, 255)  # Κόκκινο κείμενο για δεξιά
                    else:
                        position = "MIDDLE"
                        color = (0, 255, 0)  # Πράσινο κείμενο για κέντρο

                    cv2.putText(frame, f"Nose: {position}", (startX, startY - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    cv2.imshow("DNN Detector (Multi-angle)", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()