import os, ctypes as C
dll = os.environ.get("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")
d = C.CDLL(dll)

# sigs
c_void_p=c_int_p=None
d.crsdk_init.restype=C.c_int
d.crsdk_release.restype=None
d.crsdk_connect_first_dbg = getattr(d, "crsdk_connect_first_dbg")
d.crsdk_connect_first_dbg.argtypes = [C.POINTER(C.c_void_p), C.POINTER(C.c_int),
                                      C.POINTER(C.c_uint), C.POINTER(C.c_int),
                                      C.POINTER(C.c_uint), C.POINTER(C.c_uint),
                                      C.POINTER(C.c_int)]
d.crsdk_connect_first_dbg.restype = C.c_int

d.crsdk_error_name.argtypes=[C.c_int, C.c_wchar_p, C.c_uint]; d.crsdk_error_name.restype=C.c_int

def errname(rc):
    buf=C.create_unicode_buffer(64); d.crsdk_error_name(rc, buf, 64); return buf.value

print("init", d.crsdk_init())
h=C.c_void_p(); enum_rc=C.c_int(); enum_cnt=C.c_uint()
conn_rc=C.c_int(); waited=C.c_uint(); status=C.c_uint(); last=C.c_int()
rc = d.crsdk_connect_first_dbg(C.byref(h), C.byref(enum_rc), C.byref(enum_cnt),
                               C.byref(conn_rc), C.byref(waited),
                               C.byref(status), C.byref(last))
print(f"rc={rc} enum_rc={enum_rc.value} cnt={enum_cnt.value} "
      f"connect_rc={conn_rc.value}({errname(conn_rc.value)}) "
      f"status=0b{status.value:04b} last_cb_err={last.value}")
if h.value:
    # 끊기
    d.crsdk_disconnect.argtypes=[C.c_void_p]; d.crsdk_disconnect.restype=None
    d.crsdk_disconnect(h)
d.crsdk_release()
