# smoke_mesh.py — 메쉬(라이트/미디엄) + HUD(eye/yaw/pitch/shoulder) + 틸트 박스(색/알파) + Yaw/Pitch 보조선(3/6/12)
# + 좌상단 가이던스(우선순위: 어깨→눈(롤)→Yaw→Pitch)
# pip install mediapipe opencv-python numpy

import os, sys, cv2, math, numpy as np, time
from typing import Tuple, List
import mediapipe as mp

# ── 수동모드(테스트)
MANUAL_MODE         = True
MANUAL_EYE_DEG      = +5.0
MANUAL_YAW_DEG      = +8.0
MANUAL_PITCH_DEG    = +6.0
MANUAL_SHOULDER_DEG = -4.0

# ── 샘플 점 개수
LIGHT_K  = 200
MEDIUM_K = 400

# ── 경로
IMG_PATH  = os.environ.get("IMG_PATH",  r"C:\dev\photostudio\app\utils\models\test.jpg")
FACE_TASK = os.environ.get("FACE_TASK", r"C:\dev\photostudio\app\utils\models\face_landmarker.task")
POSE_TASK = os.environ.get("POSE_TASK", r"C:\dev\photostudio\app\utils\models\pose_landmarker_full.task")

# ── 색상(BGR)
CLR_WIRE = (160,160,160)
CLR_DOT  = (210,210,210)
CLR_TXT  = (230,230,230)
CLR_BOX_G= (0,200,0)
CLR_YEL  = (0,255,255)
CLR_RED  = (0,0,255)

# ── 임계
OK_SHOULDER, WARN_SHOULDER = 3.0, 5.0
OK_EYE, WARN_EYE           = 1.5, 2.5
OK_YAW, WARN_YAW           = 6.0, 9.0
OK_PITCH_MIN, OK_PITCH_MAX = 3.0, 10.0
PITCH_YELLOW_MARGIN        = 2.0

# ── QHD 정책
# 박스 테두리 2/3/4 중 기본=3
BOX_BORDER_MIN, BOX_BORDER_MID, BOX_BORDER_MAX = 2, 3, 4
# 보조선(Yaw/Pitch) 3/6/12
GUIDE_MIN, GUIDE_MID, GUIDE_MAX = 3, 6, 12

# ── 알파
ALPHA_MESH  = 0.35
ALPHA_LINE  = 0.75
ALPHA_BOX   = 0.75
ALPHA_GUIDE = 0.75

def lerp(a,b,t): return a + (b-a)*t
def clamp01(x):  return max(0.0, min(1.0, x))

def box_border_thickness(level="mid"):
    return {"min":BOX_BORDER_MIN,"mid":BOX_BORDER_MID,"max":BOX_BORDER_MAX}[level]

def guide_thick_emph(t):    # 6→12
    return int(round(lerp(GUIDE_MID, GUIDE_MAX, clamp01(t))))
def guide_thick_deemph(t):  # 6→3
    return int(round(lerp(GUIDE_MID, GUIDE_MIN, clamp01(t))))

def color_tri(val, ok, warn):
    a = abs(val)
    return CLR_BOX_G if a <= ok else (CLR_YEL if a <= warn else CLR_RED)

def color_pitch(val):
    if OK_PITCH_MIN <= val <= OK_PITCH_MAX: return CLR_BOX_G
    if (OK_PITCH_MIN - PITCH_YELLOW_MARGIN) <= val <= (OK_PITCH_MAX + PITCH_YELLOW_MARGIN): return CLR_YEL
    return CLR_RED

def line_alpha(img, p1, p2, color, thickness, alpha=ALPHA_LINE):
    ov = img.copy(); cv2.line(ov, p1, p2, color, thickness, cv2.LINE_AA)
    return cv2.addWeighted(ov, alpha, img, 1-alpha, 0, dst=img)

def polyline_alpha(img, pts, color, thickness, alpha=ALPHA_BOX, closed=True):
    ov = img.copy(); cv2.polylines(ov, [pts.reshape(-1,1,2)], closed, color, thickness, cv2.LINE_AA)
    return cv2.addWeighted(ov, alpha, img, 1-alpha, 0, dst=img)

# ── 메쉬/점/HUD
def draw_tri_mesh(img, pts, tris, alpha=ALPHA_MESH, wire_only=True):
    overlay = img.copy()
    for a,b,c in tris:
        poly = np.int32([pts[a], pts[b], pts[c]])
        if not wire_only: cv2.fillConvexPoly(overlay, poly, CLR_WIRE)
        cv2.polylines(overlay, [poly], True, CLR_WIRE, 2, cv2.LINE_AA)
    return cv2.addWeighted(overlay, alpha, img, 1-alpha, 0)

def draw_points(img, pts):
    out = img.copy()
    for p in pts.astype(int): cv2.circle(out, tuple(p), 1, CLR_DOT, -1, cv2.LINE_AA)
    return out

def put_hud(img, shoulder_deg=None, eye_deg=None, pitch_deg=None, yaw_deg=None, tri_info:str=""):
    x, y, lh = 16, 28, 22
    if tri_info: cv2.putText(img, tri_info, (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, CLR_TXT, 2, cv2.LINE_AA); y+=lh
    if shoulder_deg is not None: cv2.putText(img, f"Shoulder: {shoulder_deg:+.2f}", (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, CLR_TXT, 2, cv2.LINE_AA); y+=lh
    if eye_deg is not None:      cv2.putText(img, f"Eye roll: {eye_deg:+.2f}",   (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, CLR_YEL,   2, cv2.LINE_AA); y+=lh
    if pitch_deg is not None:    cv2.putText(img, f"Pitch: {pitch_deg:+.2f}",    (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, CLR_TXT,  2, cv2.LINE_AA); y+=lh
    if yaw_deg is not None:      cv2.putText(img, f"Yaw: {yaw_deg:+.2f}",        (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, CLR_TXT,  2, cv2.LINE_AA)
    return img

# ── 샘플러
def _equidistant_hull_indices(pts, take):
    if len(pts)==0 or take<=0: return np.zeros((0,), np.int32)
    hull = cv2.convexHull(pts.astype(np.float32), returnPoints=False).reshape(-1)
    if len(hull)==0: return np.zeros((0,), np.int32)
    poly = pts[hull]
    seg = np.linalg.norm(np.diff(np.vstack([poly, poly[:1]]), axis=0), axis=1)
    peri=float(seg.sum()); 
    if peri<=1e-6: return hull[:min(take,len(hull))]
    step=peri/max(take,1); out=[]; acc=0.0; i=0; t=0.0
    while len(out)<min(take,len(hull)):
        while acc+seg[i]<t and len(out)<take: acc+=seg[i]; i=(i+1)%len(seg)
        out.append(int(hull[i])); t+=step
        if len(out)>=len(hull): break
    return np.array(sorted(set(out)), np.int32)

def _curvature_score_np(pts, k=8):
    if len(pts)==0: return np.zeros((0,), np.float32)
    n=len(pts); k=min(k,max(1,n-1))
    diff = pts[:,None,:]-pts[None,:,:]
    d2 = np.einsum('ijk,ijk->ij', diff, diff)
    idx = np.argpartition(d2, kth=k+1, axis=1)[:,1:k+1]
    neigh = pts[idx]; mean=neigh.mean(axis=1)
    lap = np.linalg.norm(pts-mean, axis=1)
    y=pts[:,1]; y_n=(y-y.min())/max(1e-6,(y.max()-y.min()))
    return lap+0.4*y_n

def _fps_fill(pts, k, seed, base_idx):
    n=len(pts); np.random.seed(seed)
    sel=list(base_idx.tolist()); d=np.full((n,),np.inf); d[sel]=0.0
    last = sel[-1] if sel else np.random.randint(n)
    for _ in range(max(0,k-len(sel))):
        d=np.minimum(d,np.linalg.norm(pts-pts[last],axis=1)); d[sel]=-np.inf
        j=int(np.argmax(d)); sel.append(j); last=j
    return np.array(sel[:k],np.int32)

def feature_aware_sampling(pts, k, seed=0):
    n=len(pts)
    if n==0 or k<=0: return np.zeros((0,),np.int32)
    k=min(k,n); k_hull=max(8,int(k*0.40))
    hull=_equidistant_hull_indices(pts,k_hull)
    rest=np.setdiff1d(np.arange(n, dtype=np.int32), hull, assume_unique=False)
    k_curv=max(8,int(k*0.40)); curv=_curvature_score_np(pts[rest])
    curv_idx=rest[np.argsort(-curv)[:min(k_curv,len(rest))]]
    base=np.unique(np.concatenate([hull,curv_idx]))
    return _fps_fill(pts,k,seed,base)

# ── Delaunay
def delaunay_indices(rect_xywh, pts):
    x0,y0,w,h=rect_xywh; x1,y1=x0+w,y0+h
    subdiv=cv2.Subdiv2D((x0,y0,x1,y1))
    for p in pts: subdiv.insert((float(p[0]),float(p[1])))
    tris=[]
    for t in subdiv.getTriangleList():
        p=np.array([(t[0],t[1]),(t[2],t[3]),(t[4],t[5])],np.float32)
        if np.any(p[:,0]<x0)|np.any(p[:,0]>x1)|np.any(p[:,1]<y0)|np.any(p[:,1]>y1): continue
        idx=[int(np.argmin(np.linalg.norm(pts-v,axis=1))) for v in p]
        a,b,c=idx
        if a!=b and b!=c and a!=c: tris.append((a,b,c))
    return tris

# ── MediaPipe
BaseOptions = mp.tasks.BaseOptions
VisionRunningMode = mp.tasks.vision.RunningMode
FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
FaceLandmarkerResult = mp.tasks.vision.FaceLandmarkerResult
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
PoseLandmarkerResult = mp.tasks.vision.PoseLandmarkerResult
MPImage = mp.Image

def run_face_landmarks(bgr):
    img=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    mp_image=MPImage(image_format=mp.ImageFormat.SRGB,data=img)
    opts=FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=FACE_TASK),
        running_mode=VisionRunningMode.IMAGE,num_faces=1,
        output_face_blendshapes=False, output_facial_transformation_matrixes=False)
    with FaceLandmarker.create_from_options(opts) as fl:
        res:FaceLandmarkerResult=fl.detect(mp_image)
    if not res.face_landmarks: return np.empty((0,2),np.float32)
    lm=res.face_landmarks[0]; h,w=bgr.shape[:2]
    return np.array([[p.x*w,p.y*h] for p in lm],np.float32)

# ── 지표
EYE_L_OUT,EYE_L_IN,EYE_R_IN,EYE_R_OUT = 33,133,362,263
CHIN,FOREHEAD = 152,10

def eye_tilt_deg(face_pts: np.ndarray)->float:
    try:
        L=(face_pts[EYE_L_OUT]+face_pts[EYE_L_IN])*0.5
        R=(face_pts[EYE_R_IN] +face_pts[EYE_R_OUT])*0.5
    except: return 0.0
    ang=math.degrees(math.atan2((R-L)[1],(R-L)[0]))
    if ang>90: ang-=180
    if ang<-90: ang+=180
    return ang

def pitch_deg(face_pts: np.ndarray)->float:
    try:
        eyes=((face_pts[EYE_L_OUT]+face_pts[EYE_L_IN])*0.5 + (face_pts[EYE_R_IN]+face_pts[EYE_R_OUT])*0.5)*0.5
        chin=face_pts[CHIN]; forehead=face_pts[FOREHEAD]
    except: return 0.0
    H=max(1.0, chin[1]-forehead[1])
    return math.degrees(math.atan2(chin[1]-eyes[1], H))

# ── 틸트 박스
def rotated_box_corners(box, angle_deg):
    x0,y0,x1,y1=box; cx,cy=(x0+x1)/2.0,(y0+y1)/2.0
    rect=np.array([[x0,y0],[x1,y0],[x1,y1],[x0,y1]],np.float32)
    th=math.radians(angle_deg)
    R=np.array([[math.cos(th),-math.sin(th)],[math.sin(th),math.cos(th)]],np.float32)
    return (((rect-[cx,cy])@R.T)+[cx,cy]).astype(np.float32)

def _unit(v):
    n=np.linalg.norm(v); return v/n if n>1e-6 else v

# ── 보조선
def draw_yaw_guides(img, corners, yaw_deg,
                    base_gap_ratio=1/10, near_gap_ratio=1/20, far_gap_ratio=1/5,
                    base_len_ratio=0.5, near_len_ratio=0.75, far_len_ratio=0.25,
                    color_base=CLR_YEL):
    TL,TR,BR,BL=[np.asarray(p,np.float32) for p in corners]
    cxcy=(TL+BR)*0.5
    L_mid=(TL+BL)*0.5; R_mid=(TR+BR)*0.5
    L_dir=_unit(BL-TL); R_dir=_unit(BR-TR)
    L_n=_unit(L_mid-cxcy); R_n=_unit(R_mid-cxcy)
    W=np.linalg.norm(TR-TL); H=np.linalg.norm(BL-TL)

    y=clamp01(abs(yaw_deg)/15.0); s=1 if yaw_deg>=0 else -1
    gap_base,gap_near,gap_far=W*base_gap_ratio,W*near_gap_ratio,W*far_gap_ratio
    len_base,len_near,len_far=H*base_len_ratio,H*near_len_ratio,H*far_len_ratio

    if s>0:
        gap_R=lerp(gap_base,gap_far,y); gap_L=lerp(gap_base,gap_near,y)
        seg_R=lerp(len_base,len_far,y); seg_L=lerp(len_base,len_near,y)
        th_R =guide_thick_emph(y);      th_L =guide_thick_deemph(y)
    else:
        gap_L=lerp(gap_base,gap_far,y); gap_R=lerp(gap_base,gap_near,y)
        seg_L=lerp(len_base,len_far,y); seg_R=lerp(len_base,len_near,y)
        th_L =guide_thick_emph(y);      th_R =guide_thick_deemph(y)

    def _draw(mid,u,n,seg_len,gap,th):
        if seg_len<=1: return
        half=0.5*seg_len; A=mid-u*half+n*gap; B=mid+u*half+n*gap
        line_alpha(img, tuple(A.astype(int)), tuple(B.astype(int)), color_base, int(th), alpha=ALPHA_GUIDE)
    _draw(L_mid,L_dir,L_n,seg_L,gap_L,th_L); _draw(R_mid,R_dir,R_n,seg_R,gap_R,th_R)
    return img

def draw_pitch_guides(img, corners, pitch_deg,
                      base_gap_ratio=1/10, near_gap_ratio=1/20, far_gap_ratio=1/5,
                      base_len_ratio=0.5, near_len_ratio=0.75, far_len_ratio=0.25,
                      color_base=CLR_YEL):
    TL,TR,BR,BL=[np.asarray(p,np.float32) for p in corners]
    cxcy=(TL+BR)*0.5
    T_mid=(TL+TR)*0.5; B_mid=(BL+BR)*0.5
    T_dir=_unit(TR-TL); B_dir=_unit(BR-BL)
    T_n=_unit(T_mid-cxcy); B_n=_unit(B_mid-cxcy)
    W=np.linalg.norm(TR-TL); H=np.linalg.norm(BL-TL)

    p=clamp01(abs(pitch_deg)/15.0); s=1 if pitch_deg>=0 else -1
    gap_base,gap_near,gap_far=H*base_gap_ratio,H*near_gap_ratio,H*far_gap_ratio
    len_base,len_near,len_far=W*base_len_ratio,W*near_len_ratio,W*far_len_ratio

    if s>0:
        gap_B=lerp(gap_base,gap_far,p); gap_T=lerp(gap_base,gap_near,p)
        seg_B=lerp(len_base,len_far,p); seg_T=lerp(len_base,len_near,p)
        th_B =guide_thick_emph(p);      th_T =guide_thick_deemph(p)
    else:
        gap_T=lerp(gap_base,gap_far,p); gap_B=lerp(gap_base,gap_near,p)
        seg_T=lerp(len_base,len_far,p); seg_B=lerp(len_base,len_near,p)
        th_T =guide_thick_emph(p);      th_B =guide_thick_deemph(p)

    def _draw(mid,u,n,seg_len,gap,th):
        if seg_len<=1: return
        half=0.5*seg_len; A=mid-u*half+n*gap; B=mid+u*half+n*gap
        line_alpha(img, tuple(A.astype(int)), tuple(B.astype(int)), color_base, int(th), alpha=ALPHA_GUIDE)
    _draw(T_mid,T_dir,T_n,seg_T,gap_T,th_T); _draw(B_mid,B_dir,B_n,seg_B,gap_B,th_B)
    return img

# ── 어깨
def run_pose_shoulders(bgr)->Tuple[float,bool,Tuple[int,int],Tuple[int,int]]:
    img=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    mp_image=MPImage(image_format=mp.ImageFormat.SRGB,data=img)
    opts=PoseLandmarkerOptions(base_options=BaseOptions(model_asset_path=POSE_TASK),
        running_mode=VisionRunningMode.IMAGE, output_segmentation_masks=False, num_poses=1)
    with PoseLandmarker.create_from_options(opts) as pl:
        res:PoseLandmarkerResult=pl.detect(mp_image)
    if not res.pose_landmarks: return 0.0,False,(0,0),(0,0)
    lm=res.pose_landmarks[0]; h,w=bgr.shape[:2]
    L,R=lm[11],lm[12]
    if (getattr(L,"visibility",1.0)<0.5) or (getattr(R,"visibility",1.0)<0.5): return 0.0,False,(0,0),(0,0)
    Lxy=np.array([L.x*w,L.y*h],np.float32); Rxy=np.array([R.x*w,R.y*h],np.float32)
    ang=math.degrees(math.atan2(*(Rxy-Lxy)[1::-1]))
    if ang>90: ang-=180
    if ang<-90: ang+=180
    return ang,True,tuple(Lxy.astype(int)),tuple(Rxy.astype(int))

def synthesize_shoulder_line(w,h,deg):
    cx,cy=int(w*0.5),int(h*0.62); half=int(w*0.25)
    dx=half; dy=int(math.tan(math.radians(deg))*dx)
    return (cx-dx,cy-dy),(cx+dx,cy+dy)

def shoulder_thickness(deg):
    a=abs(deg)
    if a<=OK_SHOULDER: return 3
    if a<=WARN_SHOULDER: return 6
    return 12

# ── 가이던스(좌상단 1줄)
def guidance_text(shoulder, eye, yaw, pitch):
    # 우선순위: 어깨→눈(롤)→Yaw→Pitch
    a=shoulder
    if abs(a)>2:
        return ("오른쪽 어깨를 살짝 올리세요" if a>2 else "왼쪽 어깨를 살짝 올리세요",
                color_tri(a, OK_SHOULDER, WARN_SHOULDER))
    er=abs(eye)
    if er>OK_EYE:
        return ("고개를 아주 살짝 기울여 균형", color_tri(eye, OK_EYE, WARN_EYE))
    if abs(yaw)>OK_YAW:
        return (f"정면을 바라봐 주세요 ({yaw:+.1f}°)", color_tri(yaw, OK_YAW, WARN_YAW))
    if pitch<OK_PITCH_MIN or pitch>OK_PITCH_MAX:
        return ("턱을 조금 당겨 주세요" if pitch<OK_PITCH_MIN else "턱을 조금 풀어 주세요", color_pitch(pitch))
    return ("좋습니다. 그대로 유지하세요", CLR_BOX_G)

def draw_guidance_banner(img, text, color):
    pad=10; (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    x,y=16,18
    bg=np.array([40,40,40],np.uint8)
    ov=img.copy()
    cv2.rectangle(ov, (x-8,y-14), (x+w+16,y+h+8), bg.tolist(), -1, cv2.LINE_AA)
    cv2.addWeighted(ov, 0.4, img, 0.6, 0, dst=img)
    cv2.putText(img, text, (x,y+h-6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    return img

# ── 메인
def main():
    img_path = sys.argv[1] if len(sys.argv)>1 else IMG_PATH
    for pth,name in [(FACE_TASK,"FACE_TASK"),(POSE_TASK,"POSE_TASK")]:
        if not os.path.isfile(pth): raise FileNotFoundError(f"{name} not found: {pth}")
    img=cv2.imread(img_path); assert img is not None, f"not found: {img_path}"
    h,w=img.shape[:2]; rect_xywh=(0,0,w,h)

    t0=time.perf_counter()
    face_pts=run_face_landmarks(img)
    shoulder_det,ok,Lpt,Rpt=run_pose_shoulders(img)
    t_det=(time.perf_counter()-t0)*1000.0

    if len(face_pts)==0 and not MANUAL_MODE:
        print("Face: not detected"); return

    eye_det=eye_tilt_deg(face_pts) if len(face_pts) else 0.0
    pitch_det=pitch_deg(face_pts) if len(face_pts) else 0.0

    eye_val      = MANUAL_EYE_DEG      if MANUAL_MODE else eye_det
    yaw_val      = MANUAL_YAW_DEG      if MANUAL_MODE else 0.0
    pitch_val    = MANUAL_PITCH_DEG    if MANUAL_MODE else pitch_det
    shoulder_val = MANUAL_SHOULDER_DEG if MANUAL_MODE else shoulder_det

    if not ok or MANUAL_MODE:
        Lpt,Rpt=synthesize_shoulder_line(w,h,shoulder_val)

    if len(face_pts)==0:
        bw,bh=w*0.35,h*0.45; cx,cy=w*0.5,h*0.42
        box=(cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2)
    else:
        mn=face_pts.min(0); mx=face_pts.max(0)
        box=(mn[0],mn[1],mx[0],mx[1])
    corners=rotated_box_corners(box, eye_val)

    # 라이트
    t1=time.perf_counter()
    if len(face_pts):
        sel_light=feature_aware_sampling(face_pts, LIGHT_K, seed=0)
        pts_light=face_pts[sel_light]; tris_light=delaunay_indices(rect_xywh, pts_light)
        out_l=draw_points(draw_tri_mesh(img.copy(), pts_light, tris_light, alpha=ALPHA_MESH, wire_only=True), pts_light)
    else:
        tris_light=[]; out_l=img.copy()
    # 박스(색=눈 롤 기준)
    col_box=color_tri(eye_val, OK_EYE, WARN_EYE)
    pts_box=corners.astype(np.int32)
    out_l=polyline_alpha(out_l, pts_box, col_box, box_border_thickness("mid"), alpha=ALPHA_BOX)
    # 보조선
    out_l=draw_yaw_guides(out_l, corners, yaw_val,   color_base=color_tri(yaw_val, OK_YAW, WARN_YAW))
    out_l=draw_pitch_guides(out_l, corners, pitch_val, color_base=color_pitch(pitch_val))
    # 어깨선
    t_sh=shoulder_thickness(shoulder_val)
    out_l=line_alpha(out_l, Lpt, Rpt, color_tri(shoulder_val, OK_SHOULDER, WARN_SHOULDER), t_sh, alpha=ALPHA_LINE)
    ms_light=(time.perf_counter()-t1)*1000.0

    # 미디엄
    t2=time.perf_counter()
    if len(face_pts):
        sel_medium=feature_aware_sampling(face_pts, MEDIUM_K, seed=0)
        pts_medium=face_pts[sel_medium]; tris_medium=delaunay_indices(rect_xywh, pts_medium)
        out_m=draw_points(draw_tri_mesh(img.copy(), pts_medium, tris_medium, alpha=ALPHA_MESH, wire_only=True), pts_medium)
    else:
        tris_medium=[]; out_m=img.copy()
    out_m=polyline_alpha(out_m, pts_box, col_box, box_border_thickness("mid"), alpha=ALPHA_BOX)
    out_m=draw_yaw_guides(out_m, corners, yaw_val,   color_base=color_tri(yaw_val, OK_YAW, WARN_YAW))
    out_m=draw_pitch_guides(out_m, corners, pitch_val, color_base=color_pitch(pitch_val))
    out_m=line_alpha(out_m, Lpt, Rpt, color_tri(shoulder_val, OK_SHOULDER, WARN_SHOULDER), t_sh, alpha=ALPHA_LINE)
    ms_medium=(time.perf_counter()-t2)*1000.0

    # HUD + 좌상단 가이던스
    tri_info_l=f"Light: pts={LIGHT_K}, tri≈{len(tris_light)}, {ms_light:.1f} ms"
    tri_info_m=f"Medium: pts={MEDIUM_K}, tri≈{len(tris_medium)}, {ms_medium:.1f} ms"
    out_l=put_hud(out_l, shoulder_val, eye_val, pitch_val, yaw_val, tri_info=tri_info_l+(" [MANUAL]" if MANUAL_MODE else ""))
    out_m=put_hud(out_m, shoulder_val, eye_val, pitch_val, yaw_val, tri_info=tri_info_m+(" [MANUAL]" if MANUAL_MODE else ""))

    gtxt, gcol = guidance_text(shoulder_val, eye_val, yaw_val, pitch_val)
    out_l = draw_guidance_banner(out_l, gtxt, gcol)
    out_m = draw_guidance_banner(out_m, gtxt, gcol)

    # 저장
    cv2.imwrite("out_mesh_light.jpg", out_l)
    cv2.imwrite("out_mesh_medium.jpg", out_m)
    print(f"{tri_info_l} -> out_mesh_light.jpg")
    print(f"{tri_info_m} -> out_mesh_medium.jpg")
    print(f"Detect (face+pose): {t_det:.1f} ms  | MANUAL_MODE={MANUAL_MODE}")

if __name__ == "__main__":
    main()
