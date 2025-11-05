# FrameGuard 통합 가이드 (SCRSDK 라이브뷰 프레임 보장)

본 문서는 `native/frame_guard.*`를 SCRSDK 브릿지에 통합해, Python 측으로 **항상 완전한 JPEG 프레임**만 전달하기 위한 최소 작업을 설명합니다.

## 전제 (제공해주신 스펙)

- 라이브뷰 콜백 원형: `virtual void OnNotifyMonitorUpdated(CrInt32u type, CrInt32u frameNo)` (SCRSDK::IDeviceCallback)
- 라이브뷰 데이터: `CrError GetLiveViewImage(CrDeviceHandle, CrImageDataBlock*)` 로 취득
- JPEG 데이터: `CrImageDataBlock::GetImageData()` (바이트 포인터), `CrImageDataBlock::GetImageSize()` (크기)
- CrImageDataBlock 은 프레임 번호/버퍼 크기/JPEG 본문 포인터/본문 크기를 보유

## 목표

- OnNotifyMonitorUpdated → GetLiveViewImage 로 얻은 **JPEG 바이트**를 바로 Python으로 보내되,
  일부 장치에서 조각/손상 가능성이 있을 때를 대비해 **FrameGuard**를 거쳐 **SOI(FFD8)~EOI(FFD9)** 단위만 전달
- 필요 시 DHT(허프만 테이블) 누락 프레임에 기본 DHT를 삽입 (ENV로 ON/OFF)

## 통합 절차 (예시 코드)

1) C++ 브릿지 소스에 `frame_guard.*` 포함

```cpp
#include "frame_guard.h"
static FrameGuard g_guard; // 전역 또는 멤버로 보관
```

2) OnNotifyMonitorUpdated 내에서 프레임 취득 후 가드 통과

```cpp
void MyDeviceCallback::OnNotifyMonitorUpdated(CrInt32u type, CrInt32u frameNo) {
    // 1) CrImageDataBlock 확보
    CrImageDataBlock block{};
    auto err = GetLiveViewImage(device_, &block);
    if (err != CR_ERROR_OK) return;

    // 2) JPEG 포인터/크기
    const uint8_t* p = reinterpret_cast<const uint8_t*>(block.GetImageData());
    size_t len = static_cast<size_t>(block.GetImageSize());
    if (!p || len < 2) return;

    // 3) 프레임 가드로 완전 프레임만 추출
    if (auto jpeg = g_guard.append(p, len)) {
        // 4) Python 콜백 호출 (pybind11 예시)
        try {
            pybind11::gil_scoped_acquire gil;
            pybind11::bytes pybytes(reinterpret_cast<const char*>(jpeg->data()), jpeg->size());
            if (g_py_cb) g_py_cb(pybytes); // 등록된 Python 콜백 호출
        } catch (...) {
            // 콜백 실패는 무시하고 계속 진행
        }
    }
}
```

3) Python 콜백 등록 (pybind11 예시)

```cpp
// 전역/정적: py::object g_py_cb;

void set_liveview_callback(pybind11::object cb) {
    pybind11::gil_scoped_acquire gil;
    g_py_cb = std::move(cb);
}

PYBIND11_MODULE(crsdk_pybridge, m) {
    m.def("set_liveview_callback", &set_liveview_callback, "라이브뷰 바이트 콜백 등록");
    // 필요 시 connect/start/stop 등도 노출
}
```

> 주: 현재 레포에는 pybind11 심볼이 없으므로, 위와 같이 모듈 초기화를 추가해야 Python에서 `import crsdk_pybridge` 후 콜백 등록이 가능합니다.

## 환경변수(토글)

- `CAP_FRAME_GUARD=1` (기본): 가드 활성화. `0`이면 누적만 수행(디버깅용).
- `CAP_FRAME_TIMEOUT_MS=300`: 지정 ms 이상 새 조각이 없으면 버퍼 리셋.
- `CAP_MAX_FRAME_BYTES=20971520` (20MB): 버퍼 상한. 초과 시 SOI까지 정리 후 그래도 크면 clear.
- `CAP_INJECT_DHT=1` (기본): DHT 누락 시 기본 DHT 삽입. `0`이면 삽입 안 함.

## 운영 권장

- 우선 SDK 설정으로 **항상 JPEG 정프레임**을 받는 것이 최선입니다.
- 그럼에도 간헐 손상 시 FrameGuard를 유지해 OpenCV 디코드 실패를 최대한 방지합니다.
- Python 측에서는 현재 파이프라인(OpenCV 우선 + QImage 폴백)을 그대로 사용하면 됩니다.

## 빌드

- CMake/VS 프로젝트에 `native/frame_guard.cpp` 포함
- SDK/pybind11 포함 경로/링크 설정
- 결과 DLL/모듈을 Python이 로드하는 경로에 배치

