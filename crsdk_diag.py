import os, ctypes as C
DLL = os.environ.get("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")
d = C.CDLL(DLL)

wchar_p = C.c_wchar_p
d.crsdk_init.restype = C.c_int
d.crsdk_release.restype = None
d.crsdk_diag_runtime.argtypes = [wchar_p, C.c_uint]
d.crsdk_diag_runtime.restype = C.c_uint

buf = C.create_unicode_buffer(512)
rc_init = d.crsdk_init()
mask = d.crsdk_diag_runtime(buf, 512)
print("dll =", DLL)
print("init =", rc_init)
print("runtime_missing_mask =", hex(mask), "|", buf.value or "missing=none")
d.crsdk_release()
