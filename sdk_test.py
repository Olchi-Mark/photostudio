# sdk_test.py  —  CRSDK bridge quick test
import argparse, ctypes as C, os, time

def load_dll(path):
    dll = C.CDLL(path)
    # sigs
    dll.crsdk_init.restype = C.c_int
    dll.crsdk_release.restype = None

    dll.crsdk_diag_runtime.argtypes = [C.c_wchar_p, C.c_uint]
    dll.crsdk_diag_runtime.restype = C.c_uint

    dll.crsdk_connect_first_dbg.argtypes = [
        C.POINTER(C.c_void_p),                 # out handle
        C.POINTER(C.c_int), C.POINTER(C.c_uint),  # enum rc, cnt
        C.POINTER(C.c_int), C.POINTER(C.c_uint),  # connect rc, waited
        C.POINTER(C.c_uint), C.POINTER(C.c_int)   # status bits, last_cb_err
    ]
    dll.crsdk_connect_first_dbg.restype = C.c_int

    dll.crsdk_connect_usb_serial.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    dll.crsdk_connect_usb_serial.restype  = C.c_int

    dll.crsdk_lv_smoke.argtypes = [C.c_void_p, C.c_wchar_p, C.POINTER(C.c_uint)]
    dll.crsdk_lv_smoke.restype  = C.c_int

    dll.crsdk_lv_smoke_dbg.argtypes = [C.c_void_p, C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)]
    dll.crsdk_lv_smoke_dbg.restype  = C.c_int

    dll.crsdk_disconnect.argtypes = [C.c_void_p]
    dll.crsdk_disconnect.restype = None

    dll.crsdk_last_cb_error.argtypes = [C.c_void_p]
    dll.crsdk_last_cb_error.restype = C.c_int

    return dll

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', required=True, help='path to crsdk_pybridge.dll')
    ap.add_argument('--serial', help='12-char USB serial (ex: D00XXXXXXXXX)')
    ap.add_argument('-o','--out', default='', help='save path for LiveView (optional)')
    ap.add_argument('-v','--verbose', action='store_true')
    args = ap.parse_args()

    dll = load_dll(args.dll)

    # runtime check
    buf = C.create_unicode_buffer(256)
    mask = dll.crsdk_diag_runtime(buf, 256)
    if args.verbose:
        print(f"[dll] path={args.dll}")
        print(f"[runtime] mask=0x{mask:02X} missing={buf.value[8:] or 'none'}")

    # init
    rc_init = dll.crsdk_init()
    print('init', rc_init)

    h = C.c_void_p()
    if args.serial:
        rc_conn = dll.crsdk_connect_usb_serial(args.serial.encode('ascii'), C.byref(h))
        print('conn_serial', rc_conn, hex(h.value or 0))
    else:
        enum_rc = C.c_int(0); enum_cnt = C.c_uint(0)
        conn_rc = C.c_int(0); waited = C.c_uint(0)
        st_bits = C.c_uint(0); lastcb = C.c_int(0)
        rc_conn = dll.crsdk_connect_first_dbg(C.byref(h), C.byref(enum_rc), C.byref(enum_cnt),
                                              C.byref(conn_rc), C.byref(waited),
                                              C.byref(st_bits), C.byref(lastcb))
        print('conn_dbg', rc_conn, 'enum_rc', enum_rc.value, 'enum_cnt', enum_cnt.value,
              'connect_rc', conn_rc.value, 'waited', waited.value,
              'status', f"0b{st_bits.value:03b}", 'last_cb_error', lastcb.value,
              hex(h.value or 0))

    # LiveView probe
    if h.value:
        n = C.c_uint(0)
        wpath = args.out if args.out else None
        rc_smoke = dll.crsdk_lv_smoke(h, wpath, C.byref(n))
        print('smoke', rc_smoke, 'bytes', n.value)
        if rc_smoke != 0 and args.verbose:
            ri = C.c_uint(0); rj = C.c_uint(0); nb = C.c_uint(0)
            rc_dbg = dll.crsdk_lv_smoke_dbg(h, C.byref(ri), C.byref(rj), C.byref(nb))
            print('dbg', rc_dbg, 'info_rc', ri.value, 'img_rc', rj.value, 'bytes', nb.value,
                  'last_cb_error', dll.crsdk_last_cb_error(h))
        dll.crsdk_disconnect(h)

    dll.crsdk_release()

if __name__ == '__main__':
    main()
