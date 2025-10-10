# lv_capture.py
# Capture multiple LiveView frames via crsdk_pybridge.dll
# Usage:
#   pyhost.exe lv_capture.py --dll "C:\dev\photostudio\crsdk_pybridge.dll" ^
#       --out "C:\dev\photostudio\lv_%03d.jpg" --count 10 --delay 120 --serial D005D075D6AA -v

import os, sys, time, argparse
import ctypes as C

def bind(d):
    # core
    d.crsdk_init.restype = C.c_int
    d.crsdk_release.restype = None

    # connect by serial
    d.crsdk_connect_usb_serial.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    d.crsdk_connect_usb_serial.restype  = C.c_int

    # connect first (dbg)
    d.crsdk_connect_first_dbg.argtypes = [
        C.POINTER(C.c_void_p),
        C.POINTER(C.c_int),   # enum_rc
        C.POINTER(C.c_uint),  # enum_cnt
        C.POINTER(C.c_int),   # connect_rc
        C.POINTER(C.c_uint),  # waited_ms
        C.POINTER(C.c_uint),  # status_bits
        C.POINTER(C.c_int),   # last_cb_err
    ]
    d.crsdk_connect_first_dbg.restype = C.c_int

    d.crsdk_disconnect.argtypes = [C.c_void_p]
    d.crsdk_disconnect.restype = None

    # liveview
    d.crsdk_lv_smoke.argtypes = [C.c_void_p, C.c_wchar_p, C.POINTER(C.c_uint)]
    d.crsdk_lv_smoke.restype  = C.c_int
    d.crsdk_lv_smoke_dbg.argtypes = [C.c_void_p, C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)]
    d.crsdk_lv_smoke_dbg.restype  = C.c_int

    d.crsdk_error_name.argtypes = [C.c_int, C.c_wchar_p, C.c_uint]
    d.crsdk_error_name.restype  = C.c_int

def rc_name(d, rc:int) -> str:
    buf = C.create_unicode_buffer(64)
    try:
        d.crsdk_error_name(int(rc), buf, 64)
        s = buf.value
    except Exception:
        s = f"CrError={rc}"
    return s

def resolve_out_path(template:str, idx:int) -> str:
    # printf 스타일(%03d)도, format 스타일({i:03d})도 지원
    try:
        return template % idx
    except Exception:
        try:
            return template.format(i=idx)
        except Exception:
            base, ext = os.path.splitext(template)
            return f"{base}_{idx:03d}{ext}"

def connect(d, args):
    h = C.c_void_p()
    if args.serial:
        rc = d.crsdk_connect_usb_serial(args.serial.encode('ascii'), C.byref(h))
        if args.v:
            print(f"connect_serial rc={rc} handle={hex(h.value or 0)} ({rc_name(d, rc)})")
        if rc == 0 and h.value:
            return rc, h
        # fallback
        if args.v:
            print("serial connect failed → fallback to Enum connect...")
    # Enum connect (debug)
    enum_rc = C.c_int(0); enum_cnt = C.c_uint(0)
    conn_rc = C.c_int(0); waited = C.c_uint(0)
    status = C.c_uint(0); last_cb = C.c_int(0)
    rc = d.crsdk_connect_first_dbg(C.byref(h), C.byref(enum_rc), C.byref(enum_cnt),
                                   C.byref(conn_rc), C.byref(waited),
                                   C.byref(status), C.byref(last_cb))
    if args.v:
        print(f"conn_dbg {rc} enum_rc {enum_rc.value} enum_cnt {enum_cnt.value} "
              f"connect_rc {conn_rc.value} waited {waited.value} status 0b{status.value:04b} "
              f"last_cb_error {last_cb.value} {hex(h.value or 0)}")
    return rc, h

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", required=True, help="path to crsdk_pybridge.dll")
    ap.add_argument("--serial", help="12-char USB serial (optional)")
    ap.add_argument("--out", required=True, help="output path template, e.g. C:\\path\\lv_%03d.jpg")
    ap.add_argument("--count", type=int, default=1, help="number of frames")
    ap.add_argument("--delay", type=int, default=120, help="delay between frames in ms")
    ap.add_argument("-v", action="store_true", help="verbose")
    args = ap.parse_args()

    dll_path = os.path.abspath(args.dll)
    d = C.CDLL(dll_path)
    bind(d)

    if args.v:
        print(f"[dll] path={dll_path}")
        print(f"[runtime] mask=0x00 missing=none")  # runtime diag는 생략(필요시 crsdk_diag_runtime 추가)

    rc = d.crsdk_init()
    print("init", rc)
    if rc != 0:
        sys.exit(1)

    try:
        rc, h = connect(d, args)
        if rc != 0 or not h.value:
            print(f"[stop] connect failed: rc={rc}")
            return 2

        # capture loop
        for i in range(args.count):
            path = resolve_out_path(args.out, i)
            n = C.c_uint(0)
            rc_cap = d.crsdk_lv_smoke(h, C.c_wchar_p(path), C.byref(n))
            if args.v:
                print(f"cap {i:03d} rc={rc_cap} ({rc_name(d, rc_cap)}) bytes={n.value} -> {path}")
            else:
                print(f"cap {i:03d} rc={rc_cap} bytes={n.value}")
            if rc_cap != 0:
                # 진단: dbg API 한 번 더 호출
                ri = C.c_uint(0); rj = C.c_uint(0); nb = C.c_uint(0)
                try:
                    rd = d.crsdk_lv_smoke_dbg(h, C.byref(ri), C.byref(rj), C.byref(nb))
                    print(f"dbg rc={rd} info_rc={ri.value} img_rc={rj.value} bytes={nb.value}")
                except Exception:
                    pass
                return 3
            # delay
            if i + 1 < args.count and args.delay > 0:
                time.sleep(args.delay / 1000.0)

    finally:
        try:
            if 'h' in locals() and h.value:
                d.crsdk_disconnect(h)
        except Exception:
            pass
        try:
            d.crsdk_release()
        except Exception:
            pass

if __name__ == "__main__":
    main()
