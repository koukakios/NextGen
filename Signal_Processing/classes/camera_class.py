import cv2
import numpy as np
from utils.Config import DNN_PROTO, DNN_MODEL, LBF_MODEL
from utils.Config import deadzone_ratio, cam_index

class Camera:
    def __init__(self, proto_path, model_path, landmark_path, camera_index=0, deadzone_ratio=0.06):
        """
        Αρχικοποίηση της κλάσης με τα μοντέλα και την κάμερα.
        """
        self.deadzone_ratio = deadzone_ratio

        # Φόρτωση του μοντέλου (DNN Face Detector)
        print("Loading DNN Face Detector...")
        self.net = cv2.dnn.readNetFromCaffe(proto_path, model_path)

        # Φόρτωση Dlib (LBF model για Landmarks)
        print("Loading Facemark LBF model...")
        self.facemark = cv2.face.LBPHFaceRecognizer_create()
        self.facemark.loadModel(landmark_path)

        # Αρχικοποίηση κάμερας
        self.cap = cv2.VideoCapture(camera_index)

        #State
        self.state = 'm'

    def get_direction(self, startX, endX, nose_x):
        """
        Υπολογίζει αν το πρόσωπο κοιτάει αριστερά, δεξιά ή κέντρο.
        Επιστρέφει το κείμενο (Position) και το χρώμα (Color).
        """
        face_width = endX - startX
        face_center_x = startX + (face_width / 2)
        margin = face_width * self.deadzone_ratio

        if nose_x < (face_center_x - margin):
            self.state = "LEFT"
            return "LEFT", (255, 0, 0)  # Μπλε
        elif nose_x > (face_center_x + margin):
            self.state = "RIGHT"
            return "RIGHT", (0, 0, 255)  # Κόκκινο
        else:
            self.state = "MIDDLE"
            return "MIDDLE", (0, 255, 0)  # Πράσινο

    def update_state(self):
        """
        Ξεκινάει το κεντρικό loop της κάμερας.
        """
        if not self.cap.isOpened():
            print("Error: Could not open the camera.")
            return

        print("System ready. Press 'q' to quit.")



        ret, frame = self.cap.read()
        if not ret:
            return

        h, w = frame.shape[:2]

        # Προετοιμασία εικόνας
        blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), (104.0, 177.0, 123.0))
        self.net.setInput(blob)
        detections = self.net.forward()

        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]

            if confidence > 0.5:
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")

                # Περιορισμός συντεταγμένων
                startX, startY = max(0, startX), max(0, startY)
                endX, endY = min(w, endX), min(h, endY)

                if startX >= endX or startY >= endY:
                    continue

                cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0), 2)

                faces = np.array([[startX, startY, endX - startX, endY - startY]], dtype=np.int32)
                ok, landmarks = self.facemark.fit(frame, faces)

                if ok:
                    for marks in landmarks:
                        nose_x = marks[0][30][0]
                        nose_y = marks[0][30][1]

                        cv2.circle(frame, (int(nose_x), int(nose_y)), 3, (0, 0, 255), -1)

                        # Κλήση της συνάρτησης για την κατεύθυνση
                        position, color = self.get_direction(startX, endX, nose_x)

                        cv2.putText(frame, f"Nose: {position}", (startX, startY - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.imshow("DNN Detector (Multi-angle)", frame)


    def cleanup(self):
        """
        Απελευθερώνει την κάμερα και κλείνει τα παράθυρα.
        """
        print("Cleaning up resources...")
        self.cap.release()
        cv2.destroyAllWindows()


# --- ΕΚΤΕΛΕΣΗ ΚΩΔΙΚΑ ---
if __name__ == "__main__":
    # Δημιουργία του αντικειμένου και εκκίνηση
    # Μπορείς να αλλάξεις το 0.06 εδώ απευθείας:
    detector = Camera(
        proto_path=DNN_PROTO,
        model_path=DNN_MODEL,
        landmark_path=LBF_MODEL,
        camera_index=cam_index,
        deadzone_ratio=deadzone_ratio
    )

    detector.update_state()