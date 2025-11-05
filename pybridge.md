# crsdk_pybridge.dll 인터페이스 요약

본 문서는 `crsdk_pybridge.cpp`(DLL 브릿지)의 공개 함수와 동작을 간단히 정리합니다. 반환 규약은 기본적으로 0=성공, 0이 아닌 값=실패 코드입니다.

## 초기화/종료
- `crsdk_set_debug(int on)`: 내부 디버그 로그 온/오프.
- `crsdk_init()`: SDK/의존 DLL 사전 로드 및 초기화.
- `crsdk_release()`: SDK 해제.
- `crsdk_get_build_info(wchar_t* buf, unsigned cch)`: 빌드 스탬프 문자열.

## 연결/해제/상태
- `crsdk_connect_first(void** out_handle)`: 첫 기기 연결(콜백 등록/이벤트 대기 포함).
- `crsdk_connect_usb_serial(const char* ascii12, void** out_handle)`: USB 시리얼(12자)로 연결 시도. 실패 시 일반 연결로 폴백.
- `crsdk_disconnect(void* handle)`: 연결 해제 및 자원 정리.
- `crsdk_status(void* handle)`: 상태 비트 반환.
- `crsdk_last_cb_error(void* handle)`: 마지막 콜백 오류 코드.

## 라이브뷰
- `crsdk_enable_liveview(void* handle, int enable)`: 라이브뷰 On/Off.
- `crsdk_get_lv_info(void* handle, unsigned* out_nbytes)`: 필요 버퍼 크기 산출(최소 크기/가드 포함).
- `crsdk_get_lv_image(void* handle, void* out_buf, unsigned buf_size, unsigned* out_used)`: JPEG 바이트 추출. SOI~EOI 구간 보호/필요 시 DHT 삽입.
- 스모크: `crsdk_lv_smoke(...)`, `crsdk_lv_smoke_dbg(...)`.

## 촬영/AF/AWB
- `crsdk_shoot_one(void* handle, int)`: Release Down/Up 시퀀스로 1회 촬영.
- `crsdk_one_shot_af(void* handle)`: AF 트리거(TrackingOnAndAFOn Down/Up). 0=성공.
- `crsdk_one_shot_awb(void*)`: 현재 빌드 미지원(고정 -24).

## 저장/다운로드
- `crsdk_set_save_dir(void* handle, const char* path)`: Host 저장 모드로 설정 + 전역 다운로드 디렉터리 갱신.
- `crsdk_set_save_info(void* handle, int save_mode, const char* host_dir, const char* file_name)`: SaveInfo 직접 설정.
- `crsdk_set_download_dir(const char* dir)`: 전역 다운로드 디렉터리만 변경.
- `crsdk_get_last_saved_jpeg(void*, wchar_t* out_path, unsigned cch)`: 전역 디렉터리에서 최신 JPG 경로 탐색(0=성공, 1=없음).
- `crsdk_preset_host_save_dir(void* handle, const char* host_dir_utf8)`: Host 저장 프리셋 + 다운로드 디렉터리 동기화.

## 진단/열거/유틸
- `crsdk_diag_runtime(wchar_t* buf, unsigned cch)`: 의존 DLL 존재 여부 비트마스크 + 설명 문자열.
- `crsdk_enum_count()`, `crsdk_enum_dump(wchar_t* buf, unsigned cch)`: 카메라 열거 요약/덤프.
- `crsdk_error_name(int rc, wchar_t* buf, unsigned cch)`, `crsdk_strerror(int rc)`: 오류 코드 → 문자열 변환.

## 환경 변수(발췌)
- `CRSDK_LV_MIN_BUF`, `CRSDK_LV_SCRATCH`, `CRSDK_LV_TRIES`, `CRSDK_LV_SLEEP_MS`: 라이브뷰 버퍼/재시도/슬립 조정.
- `CRSDK_LV_GUARD`, `CAP_INJECT_DHT`: JPEG 가드/기본 DHT 삽입 사용 여부.

## 주의사항
- 경로 인코딩: 입력은 UTF-8/ACP 허용, 내부는 UTF-16로 변환해 사용.
- 저장 디렉터리: 전역 `g_download_dir` 보호(뮤텍스). `crsdk_set_save_dir`는 SaveInfo+다운로드 디렉터리를 함께 갱신.
- 반환 규약: 상위 래퍼에서 0=성공 규약을 그대로 따르는 것을 권장합니다.

