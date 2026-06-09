import cv2
import numpy as np

from collections import deque
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

        # Φόρτωση LBF model για Landmarks
        print("Loading Facemark LBF model...")
        self.facemark = cv2.face.createFacemarkLBF()
        self.facemark.loadModel(landmark_path)

        # Αρχικοποίηση κάμερας
        self.cap = cv2.VideoCapture(camera_index)

        # State
        self.state = "MIDDLE"
        self.color = (0, 255, 0)
        self.state_buffer = deque(maxlen=1)

    def get_direction(self, startX, endX, nose_x):
        """
        Υπολογίζει αν το πρόσωπο κοιτάει αριστερά, δεξιά ή κέντρο.
        Επιστρέφει το κείμενο και το χρώμα.
        """
        face_width = endX - startX
        face_center_x = startX + (face_width / 2)
        margin = face_width * self.deadzone_ratio

        if nose_x < (face_center_x - 0.5 * margin):
            direction = -1
        elif nose_x > (face_center_x + margin):
            direction = 1
        else:
            direction = 0

        self.state_buffer.append(direction)
        average_direction = round(sum(self.state_buffer) / len(self.state_buffer))

        states = {
            -1: ("RIGHT", (255, 0, 0)),
            0: ("MIDDLE", (0, 255, 0)),
            1: ("LEFT", (0, 0, 255)),
        }
        self.state, self.color = states[average_direction]

        return self.state, self.color

    def update_state(self):
        """
        Διαβάζει ένα frame από την κάμερα και ενημερώνει το state.
        """
        if not self.cap.isOpened():
            print("Error: Could not open the camera.")
            return False

        ret, frame = self.cap.read()
        if not ret:
            return False

        h, w = frame.shape[:2]

        # Προετοιμασία εικόνας
        blob = cv2.dnn.blobFromImage(
            frame,
            1.0,
            (300, 300),
            (104.0, 177.0, 123.0)
        )

        self.net.setInput(blob)
        detections = self.net.forward()

        for i in range(1):
            confidence = detections[0, 0, i, 2]

            if confidence > 0.5:
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")

                # Περιορισμός συντεταγμένων
                startX, startY = max(0, startX), max(0, startY)
                endX, endY = min(w, endX), min(h, endY)

                if startX >= endX or startY >= endY:
                    continue

                # cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0), 2)

                faces = np.array(
                    [[startX, startY, endX - startX, endY - startY]],
                    dtype=np.int32
                )

                ok, landmarks = self.facemark.fit(frame, faces)

                if ok:
                    for marks in landmarks:
                        nose_x = marks[0][30][0]
                        nose_y = marks[0][30][1]

                        # cv2.circle(frame, (int(nose_x), int(nose_y)), 3, (0, 0, 255), -1)

                        # Υπολογισμός κατεύθυνσης
                        position, color = self.get_direction(startX, endX, nose_x)

                        # cv2.putText(
                        #     frame,
                        #     f"Head: {position}",
                        #     (startX, startY - 10),
                        #     cv2.FONT_HERSHEY_SIMPLEX,
                        #     0.7,
                        #     color,
                        #     2
                        # )

        # Big live label on screen
        # cv2.putText(
        #     frame,
        #     f"Direction: {self.state}",
        #     (30, 50),
        #     cv2.FONT_HERSHEY_SIMPLEX,
        #     1.2,
        #     self.color,
        #     3
        # )

        # Show live camera
        # cv2.imshow("Head Direction Camera", frame)

        # Press q to quit
        # if cv2.waitKey(1) & 0xFF == ord("q"):
        #     return False

        return True

    def cleanup(self):
        """
        Απελευθερώνει την κάμερα και κλείνει τα παράθυρα.
        """
        print("Cleaning up resources...")
        self.cap.release()
        # cv2.destroyAllWindows()


# --- ΕΚΤΕΛΕΣΗ ΚΩΔΙΚΑ ---
if __name__ == "__main__":
    detector = Camera(
        proto_path=DNN_PROTO,
        model_path=DNN_MODEL,
        landmark_path=LBF_MODEL,
        camera_index=cam_index,
        deadzone_ratio=deadzone_ratio
    )

    try:
        print("System ready. Press 'q' to quit.")

        while True:
            keep_running = detector.update_state()

            if not keep_running:
                break

    finally:
        detector.cleanup()
