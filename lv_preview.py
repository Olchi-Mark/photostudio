# -*- coding: utf-8 -*-
# LiveView preview using crsdk_pybridge.dll + OpenCV
import os, sys, time, argparse
import ctypes as C
import numpy as np
import cv2

def load_dll(path: str):
    dll = C.CDLL(path)
    # signatures
    dll.crsdk_init.restype = C.c_int
    dll.crsdk_release.restype = None

    dll.crsdk_connect_usb_serial.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    dll.crsdk_connect_usb_serial.restype  = C.c_int

    dll.crsdk_connect_first.argtypes = [C.POINTER(C.c_void_p)]
    dll.crsdk_connect_first.restype  = C.c_int

    dll.crsdk_enable_liveview.argtypes = [C.c_void_p, C.c_int]
    dll.crsdk_enable_liveview.restype  = C.c_int

    dll.crsdk_get_lv_info.argtypes = [C.c_void_p, C.POINTER(C.c_uint)]
    dll.crsdk_get_lv_info.restype  = C.c_int

    dll.crsdk_get_lv_image.argtypes = [C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]
    dll.crsdk_get_lv_image.restype  = C.c_int

    dll.crsdk_disconnect.argtypes = [C.c_void_p]
    dll.crsdk_disconnect.restype  = None
    return dll

def connect(dll, serial: str|None):
    h = C.c_void_p()
    rc = -1
    if serial:
        rc = dll.crsdk_connect_usb_serial(serial.encode('ascii'), C.byref(h))
        print("connect_serial rc=", rc, "handle=", hex(h.value or 0))
        if rc == 0:
            return h
        print("serial connect failed -> fallback to Enum connect...")

    rc = dll.crsdk_connect_first(C.byref(h))
    print("connect_enum rc=", rc, "handle=", hex(h.value or 0))
    if rc != 0:
        raise RuntimeError(f"connect failed rc={rc}")
    return h

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", required=True, help="crsdk_pybridge.dll 절대경로")
    ap.add_argument("--serial", help="12자리 USB 시리얼(옵션)")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()

    dll = load_dll(args.dll)
    rc = dll.crsdk_init()
    print("init", rc)
    if rc != 0: sys.exit(1)

    h = None
    try:
        h = connect(dll, args.serial)

        # enable LV
        rc = dll.crsdk_enable_liveview(h, 1)
        if rc != 0:
            raise RuntimeError(f"enable_lv rc={rc}")

        # query buffer size
        need = C.c_uint(0)
        rc = dll.crsdk_get_lv_info(h, C.byref(need))
        if rc != 0 or need.value == 0:
            # 첫 프레임까지 시간이 걸릴 수 있음 -> 약간 대기 후 재시도
            for _ in range(40):
                time.sleep(0.05)
                rc = dll.crsdk_get_lv_info(h, C.byref(need))
                if rc == 0 and need.value > 0:
                    break
        if need.value == 0:
            raise RuntimeError(f"lv_info rc={rc} size=0")

        buf = (C.c_ubyte * need.value)()
        used = C.c_uint(0)

        delay = max(1.0/args.fps, 0.001)
        print("preview start: need=", need.value)

        while True:
            rc = dll.crsdk_get_lv_image(h, C.byref(buf), need.value, C.byref(used))
            if rc == 0 and used.value > 0:
                # used 바이트만 넘긴다!
                arr = np.ctypeslib.as_array(buf, shape=(need.value,))[:used.value]
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is None:
                    # 디코드 실패 디버그: 앞 16바이트 덤프
                    head = bytes(arr[:16]).hex(" ")
                    print("decode failed (used=", used.value, ") head:", head)
                else:
                    cv2.imshow("LiveView", img)
                    if cv2.waitKey(1) & 0xFF in (27, ord('q')):
                        break
            else:
                if args.v:
                    print("get_lv_image rc=", rc, "used=", used.value)
                time.sleep(0.03)

            time.sleep(delay)

        cv2.destroyAllWindows()
        dll.crsdk_enable_liveview(h, 0)

    finally:
        try:
            if h: dll.crsdk_disconnect(h)
        except: pass
        try:
            dll.crsdk_release()
        except: pass

if __name__ == "__main__":
    main()
