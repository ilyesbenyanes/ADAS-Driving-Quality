"""
main.py - Controleur ADAS embarque (Raspberry Pi)
====================================================
Script unique de deploiement : reception CAN + inference XGBoost
(qualite de conduite, 3 classes) + detection de voie (vision par
ordinateur) + serveur de streaming web de supervision.

Fichiers necessaires a cote de ce script :
    models/driving_quality_model_3classes.json

Lancement :
    python3 main.py
"""

import os
import time
import collections
import threading
import numpy as np
import xgboost as xgb
import can
import cv2
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_PATH = "models/driving_quality_model_3classes.json"

CAN_INTERFACE = "can0"       # interface CAN physique reelle (bus_type socketcan)
CAN_BITRATE = 500000
SENSOR_FRAME_ID = 0x001      # trame capteurs (ADC + distance) emise par STM32 #1
DECISION_FRAME_ID = 0x100    # trame decision (risque + angle) emise vers STM32 #2

# Source video pour la detection de voie :
#   0 = camera connectee au Raspberry Pi (deploiement reel)
#   "mon_video.mp4" = fichier video (tests hors ligne)
VIDEO_SOURCE = 0
DISPLAY_WIDTH = 480          # redimensionnement EN PRESERVANT le ratio d'aspect
WEB_PORT = 8080

PRINT_INTERVAL_S = 0.5       # cadencement de l'affichage terminal

CLASSES_MAP = {
    0: "danger",
    1: "risky_driving",
    2: "safe_driving"
}
RISK_LEVEL_MAP = {
    "safe_driving": 0,
    "risky_driving": 1,
    "danger": 2
}

FEATURE_NAMES = [
    "adc_value", "distance_cm", "delta_adc", "delta_distance",
    "adc_speed", "distance_speed", "adc_mean", "distance_mean",
    "adc_std", "distance_std", "distance_min", "distance_max"
]

WINDOW_SIZE = 5
DELTA_TIME_MS = 153.0
GAP_RESET_THRESHOLD_S = 1.0
STD_DDOF = 1   # coherent avec pandas .rolling().std() utilise a l'entrainement


# ==========================================
# 2. CHARGEMENT DU MODELE
# ==========================================
print("Chargement du modele XGBoost...")
try:
    model = xgb.Booster()
    model.load_model(MODEL_PATH)
    print(f"Modele charge depuis {MODEL_PATH}")
except Exception as e:
    print(f"Erreur chargement modele : {e}")
    raise SystemExit(1)


# ==========================================
# 3. BUS CAN
# ==========================================
try:
    bus = can.interface.Bus(channel=CAN_INTERFACE, interface='socketcan')
    print(f"Bus CAN ({CAN_INTERFACE}) connecte.\n")
except Exception as e:
    print(f"Impossible de se connecter au bus CAN : {e}")
    raise SystemExit(1)

buffer_adc = collections.deque(maxlen=WINDOW_SIZE)
buffer_dist = collections.deque(maxlen=WINDOW_SIZE)
last_msg_time = None
last_print_time = 0.0

latest_servo_angle = 90
output_frame = None
lock = threading.Lock()
running = True


def reset_buffers(reason=""):
    buffer_adc.clear()
    buffer_dist.clear()
    if reason:
        print(f"Buffer reinitialise ({reason})")


def send_adas_decision(risk_level, servo_angle, verbose=True):
    msg = can.Message(
        arbitration_id=DECISION_FRAME_ID,
        data=[risk_level, int(servo_angle), 0, 0, 0, 0, 0, 0],
        is_extended_id=False
    )
    try:
        bus.send(msg)
        if verbose:
            print(f"[CAN 0x{DECISION_FRAME_ID:03X}] risk={risk_level} angle={int(servo_angle)}")
    except can.CanError:
        print("Echec d'envoi de la trame decision CAN.")


# ==========================================
# 4. DETECTION DE VOIE (vision par ordinateur)
# ==========================================
left_fit_history = []
right_fit_history = []
HISTORY_SIZE = 5
MIN_HISTOGRAM_PEAK = 25


def get_perspective_points(w, h):
    src = np.float32([
        [w * 0.44, h * 0.55], [w * 0.58, h * 0.55],
        [w * 0.90, h * 0.92], [w * 0.12, h * 0.92],
    ])
    dst = np.float32([
        [w * 0.25, 0], [w * 0.75, 0], [w * 0.75, h], [w * 0.25, h],
    ])
    return src, dst


def threshold_binary(warped):
    hls = cv2.cvtColor(warped, cv2.COLOR_BGR2HLS)
    l_channel = hls[:, :, 1]
    white = np.zeros_like(l_channel)
    white[l_channel >= 180] = 255
    hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (15, 60, 100), (35, 255, 255))
    return cv2.bitwise_or(white, yellow)


def sliding_window_search(binary):
    h, w = binary.shape
    hist = np.sum(binary[h // 2:, :] > 127, axis=0)
    mid = w // 2

    left_peak = np.max(hist[:mid])
    right_peak = np.max(hist[mid:])
    leftx_base = np.argmax(hist[:mid]) if left_peak >= MIN_HISTOGRAM_PEAK else None
    rightx_base = (np.argmax(hist[mid:]) + mid) if right_peak >= MIN_HISTOGRAM_PEAK else None

    if leftx_base is None and rightx_base is None:
        return np.array([]), np.array([]), np.array([]), np.array([])
    if leftx_base is None:
        leftx_base = max(0, rightx_base - w // 3)
    if rightx_base is None:
        rightx_base = min(w - 1, leftx_base + w // 3)

    nwin, margin, minpix = 9, 50, 30
    wh = h // nwin
    nz = binary.nonzero()
    nzy, nzx = nz[0], nz[1]
    lcur, rcur = leftx_base, rightx_base
    lidx, ridx = [], []

    for win in range(nwin):
        ylo, yhi = h - (win + 1) * wh, h - win * wh
        gl = ((nzy >= ylo) & (nzy < yhi) & (nzx >= lcur - margin) & (nzx < lcur + margin)).nonzero()[0]
        gr = ((nzy >= ylo) & (nzy < yhi) & (nzx >= rcur - margin) & (nzx < rcur + margin)).nonzero()[0]
        lidx.append(gl)
        ridx.append(gr)
        if len(gl) > minpix:
            lcur = int(np.mean(nzx[gl]))
        if len(gr) > minpix:
            rcur = int(np.mean(nzx[gr]))

    lidx = np.concatenate(lidx)
    ridx = np.concatenate(ridx)
    return nzx[lidx], nzy[lidx], nzx[ridx], nzy[ridx]


def robust_linear_fit(x, y):
    if len(x) <= 40:
        return None
    fit = np.polyfit(y, x, 1)
    predicted = fit[0] * y + fit[1]
    residuals = np.abs(x - predicted)
    threshold = max(15, np.percentile(residuals, 75))
    mask = residuals <= threshold
    if np.sum(mask) <= 40:
        return fit
    return np.polyfit(y[mask], x[mask], 1)


def is_plausible_lane_width(left_fit, right_fit, h, w):
    if left_fit is None or right_fit is None:
        return True
    y_eval = h - 1
    lx = left_fit[0] * y_eval + left_fit[1]
    rx = right_fit[0] * y_eval + right_fit[1]
    expected = w * 0.5
    return expected * 0.5 <= (rx - lx) <= expected * 1.8


def smooth_fit(fit, history, max_jump=None):
    if fit is not None and max_jump is not None and len(history) > 0:
        if abs(fit[1] - history[-1][1]) > max_jump:
            fit = None
    if fit is not None:
        history.append(fit)
        if len(history) > HISTORY_SIZE:
            history.pop(0)
    if len(history) == 0:
        return None
    return np.mean(history, axis=0)


def offset_to_servo_angle(offset_px, width):
    angle = 90 + (offset_px / (width * 0.3)) * 45.0
    return int(np.clip(angle, 45, 135))


def process_frame(frame):
    h, w, _ = frame.shape
    src, dst = get_perspective_points(w, h)
    M = cv2.getPerspectiveTransform(src, dst)
    Minv = cv2.getPerspectiveTransform(dst, src)
    warped = cv2.warpPerspective(frame, M, (w, h))

    binary = threshold_binary(warped)
    lx, ly, rx, ry = sliding_window_search(binary)

    left_fit = robust_linear_fit(lx, ly) if len(lx) else None
    right_fit = robust_linear_fit(rx, ry) if len(rx) else None

    if not is_plausible_lane_width(left_fit, right_fit, h, w):
        left_fit, right_fit = None, None

    max_jump = w * 0.15
    left_s = smooth_fit(left_fit, left_fit_history, max_jump)
    right_s = smooth_fit(right_fit, right_fit_history, max_jump)

    car_center = w / 2.0
    y_eval = h - 1
    lx_pos = (left_s[0] * y_eval + left_s[1]) if left_s is not None else None
    rx_pos = (right_s[0] * y_eval + right_s[1]) if right_s is not None else None

    if lx_pos is not None and rx_pos is not None:
        lane_center = (lx_pos + rx_pos) / 2.0
    elif lx_pos is not None:
        lane_center = lx_pos + w * 0.2
    elif rx_pos is not None:
        lane_center = rx_pos - w * 0.2
    else:
        lane_center = car_center

    offset_px = lane_center - car_center
    angle = offset_to_servo_angle(offset_px, w)

    # Overlay simple (ligne centre voiture / centre voie)
    cv2.line(frame, (int(car_center), int(h * 0.55)), (int(car_center), h), (255, 0, 0), 2)
    cv2.line(frame, (int(lane_center), int(h * 0.55)), (int(lane_center), h), (0, 255, 255), 2)
    color = (0, 255, 0) if 80 <= angle <= 100 else (0, 165, 255)
    cv2.putText(frame, f"Angle: {angle} deg", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return frame, angle


def lane_detection_thread():
    global latest_servo_angle, output_frame, running

    if isinstance(VIDEO_SOURCE, str) and not os.path.exists(VIDEO_SOURCE):
        print(f"Video introuvable : {VIDEO_SOURCE}")
        return

    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print("Impossible d'ouvrir la source video (camera/fichier).")
        return

    print("Thread detection de voie demarre.")

    while running:
        ret, frame = cap.read()
        if not ret:
            if isinstance(VIDEO_SOURCE, str):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            else:
                time.sleep(0.1)
                continue

        h0, w0 = frame.shape[:2]
        scale = DISPLAY_WIDTH / w0
        frame = cv2.resize(frame, (DISPLAY_WIDTH, int(h0 * scale)))

        processed, angle = process_frame(frame)
        latest_servo_angle = angle

        _, buf = cv2.imencode('.jpg', processed)
        with lock:
            output_frame = buf.tobytes()

        time.sleep(0.03)

    cap.release()


# ==========================================
# 5. SERVEUR DE STREAMING WEB (supervision)
# ==========================================
class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """<html><body style='background:#111;color:#fff;text-align:center;'>
            <h2>ADAS - Flux de supervision</h2>
            <img src='/stream.mjpg'/></body></html>"""
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while running:
                    with lock:
                        frame_bytes = output_frame
                    if frame_bytes is not None:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame_bytes)))
                        self.end_headers()
                        self.wfile.write(frame_bytes)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.04)
            except Exception:
                pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass


# ==========================================
# 6. BOUCLE PRINCIPALE : CAN + INFERENCE
# ==========================================
if __name__ == "__main__":
    video_thread = threading.Thread(target=lane_detection_thread, daemon=True)
    video_thread.start()

    try:
        server = ThreadedHTTPServer(('0.0.0.0', WEB_PORT), StreamingHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"Serveur web de supervision : http://<IP_RASPBERRY>:{WEB_PORT}")
    except Exception as e:
        print(f"Erreur serveur web : {e}")

    print(f"--- Controleur ADAS demarre (ecoute 0x{SENSOR_FRAME_ID:03X} sur {CAN_INTERFACE}) ---\n")

    try:
        while running:
            msg = bus.recv(timeout=0.1)
            now = time.time()

            if msg is None:
                continue

            if last_msg_time is not None and (now - last_msg_time) > GAP_RESET_THRESHOLD_S:
                reset_buffers(f"silence de {now - last_msg_time:.2f}s")
            last_msg_time = now

            if msg.arbitration_id == SENSOR_FRAME_ID and len(msg.data) >= 8:
                data = msg.data
                timestamp_ms = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
                adc_value = float((data[4] << 8) | data[5])
                distance_cm = float((data[6] << 8) | data[7])

                should_print = (now - last_print_time) >= PRINT_INTERVAL_S
                if should_print:
                    print(f"[CAN RX] t={timestamp_ms}ms ADC={int(adc_value)} dist={distance_cm:.1f}cm")
                    last_print_time = now

                buffer_adc.append(adc_value)
                buffer_dist.append(distance_cm)

                if len(buffer_adc) < WINDOW_SIZE:
                    continue

                adc_mean = float(np.mean(buffer_adc))
                distance_mean = float(np.mean(buffer_dist))
                adc_std = float(np.std(buffer_adc, ddof=STD_DDOF))
                distance_std = float(np.std(buffer_dist, ddof=STD_DDOF))
                distance_min = float(np.min(buffer_dist))
                distance_max = float(np.max(buffer_dist))
                delta_adc = float(buffer_adc[-1] - buffer_adc[-2])
                delta_dist = float(buffer_dist[-1] - buffer_dist[-2])
                adc_speed = delta_adc / DELTA_TIME_MS
                distance_speed = delta_dist / DELTA_TIME_MS

                features = np.array([[
                    adc_value, distance_cm, delta_adc, delta_dist,
                    adc_speed, distance_speed, adc_mean, distance_mean,
                    adc_std, distance_std, distance_min, distance_max
                ]], dtype=np.float32)

                dmatrix = xgb.DMatrix(features, feature_names=FEATURE_NAMES)
                preds = model.predict(dmatrix)
                pred_class_id = int(preds[0]) if preds.ndim == 1 else int(np.argmax(preds[0]))
                class_name = CLASSES_MAP.get(pred_class_id, "Unknown")
                risk_level = RISK_LEVEL_MAP.get(class_name, 0)

                if should_print:
                    print(f"  -> classe={class_name} (risque={risk_level})")

                send_adas_decision(risk_level, latest_servo_angle, verbose=should_print)

    except KeyboardInterrupt:
        print("\nArret demande par l'utilisateur.")
    finally:
        running = False
        bus.shutdown()
        print("Bus CAN ferme.")
