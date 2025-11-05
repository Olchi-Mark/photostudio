import os, ctypes as C
from ctypes import byref
from pathlib import Path

DLL = os.environ.get("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")
d = C.CDLL(DLL)

d.crsdk_init.restype = C.c_int
d.crsdk_release.restype = None
d.crsdk_connect_first.argtypes = [C.POINTER(C.c_void_p)]
d.crsdk_connect_first.restype  = C.c_int
d.crsdk_disconnect.argtypes = [C.c_void_p]; d.crsdk_disconnect.restype = None
d.crsdk_enable_liveview.argtypes = [C.c_void_p, C.c_int]; d.crsdk_enable_liveview.restype = C.c_int
d.crsdk_get_lv_info.argtypes = [C.c_void_p, C.POINTER(C.c_uint)]; d.crsdk_get_lv_info.restype = C.c_int
d.crsdk_get_lv_image.argtypes= [C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]
d.crsdk_get_lv_image.restype = C.c_int

print("init", d.crsdk_init())
h = C.c_void_p()
rc = d.crsdk_connect_first(byref(h))
print("connect", rc, hex(h.value or 0))
if rc!=0 or not h.value:
    d.crsdk_release(); raise SystemExit("connect failed")

print("lv_on", d.crsdk_enable_liveview(h,1))
need = C.c_uint(0)
print("lv_info", d.crsdk_get_lv_info(h, byref(need)), "bytes", need.value)
if need.value:
    # 라이브뷰 초기 프레임은 불안정할 수 있으므로 재시도 루프를 둔다.
    # - DLL 내부도 재시도를 하지만, 호출 측에서도 약간의 여유를 더 준다.
    buf = (C.c_ubyte * need.value)()
    used = C.c_uint(0)
    rc = -1
    for i in range(40):  # 최대 약 2초 (50ms * 40)
        used.value = 0
        rc = d.crsdk_get_lv_image(h, C.cast(buf, C.c_void_p), need.value, byref(used))
        if rc == 0 and used.value:
            break
        # 너무 빠른 루프를 피하고 카메라/SDK가 프레임을 준비할 시간을 준다.
        import time; time.sleep(0.05)
    print("lv_img", rc, "used", used.value)
    if rc==0 and used.value:
        out = Path(r"C:\PhotoBox\probe_lv.jpg"); out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f: f.write(bytes(buf[:used.value]))
        print("saved:", out)
d.crsdk_enable_liveview(h,0)
d.crsdk_disconnect(h); d.crsdk_release()
