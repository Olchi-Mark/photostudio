# quick_face_landmarker_tasks.py  (Tasks API + model bytes 로딩)
import sys, os, math, urllib.request
import cv2, mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

URL = ("https://storage.googleapis.com/mediapipe-models/"
       "face_landmarker/face_landmarker/float16/1/face_landmarker.task")
LOCAL = "face_landmarker.task"

def ensure_bytes(p):
    if not os.path.exists(p) or os.path.getsize(p) < 1024*100:
        urllib.request.urlretrieve(URL, p)
    with open(p, "rb") as f:
        data = f.read()
    if len(data) < 1024*100:
        raise RuntimeError("모델 파일 손상/과소크기")
    return data

def estimate_roll_deg(lm, iw, ih):
    lx, ly = int(lm[33].x*iw),  int(lm[33].y*ih)   # 좌 눈꼬리
    rx, ry = int(lm[263].x*iw), int(lm[263].y*ih)  # 우 눈꼬리
    return math.degrees(math.atan2(ry-ly, rx-lx)), (lx,ly), (rx,ry)

def main(img="test.jpg"):
    model_bytes = ensure_bytes(LOCAL)
    bgr = cv2.imread(img)
    if bgr is None:
        print("이미지 로드 실패:", img); return
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    opts = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=model_bytes),
        num_faces=1,
        running_mode=vision.RunningMode.IMAGE,
    )
    det = vision.FaceLandmarker.create_from_options(opts)
    res = det.detect(mp_img)
    if not res.face_landmarks:
        print("no face"); return

    lm = res.face_landmarks[0]; ih, iw = rgb.shape[:2]
    roll, pL, pR = estimate_roll_deg(lm, iw, ih)
    for x,y in (pL, pR):
        cv2.circle(bgr, (x,y), 3, (0,255,0), -1)
    cv2.imwrite("test_out.jpg", bgr)
    print(f"ok: {len(lm)} pts, roll={roll:.2f} deg → saved: test_out.jpg")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "test.jpg")
