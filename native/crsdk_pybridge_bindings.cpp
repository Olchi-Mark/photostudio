// -*- coding: utf-8 -*-

// 한국어 주석: pybind11 바인딩 스켈레톤
// - 목적: FrameGuard를 통해 완전한 JPEG 프레임만 Python 콜백으로 전달
// - 통합 지점: SCRSDK 콜백(예: OnNotifyMonitorUpdated)에서 GetLiveViewImage로 얻은 바이트를 on_chunk()에 전달

#include <pybind11/pybind11.h>
#include <pybind11/pytypes.h>
#include <pybind11/functional.h>
#include <pybind11/bytes.h>

#include <memory>
#include <string>
#include <vector>

#include "frame_guard.h"

namespace py = pybind11;

// 한국어 주석: 라이브뷰 브릿지 클래스
// - FrameGuard로 프레임을 보정/추출하고 Python 콜백에 bytes로 전달한다.
class LiveViewBridge {
public:
    LiveViewBridge() : guard_(std::make_unique<FrameGuard>()) {}

    // 한국어 주석: Python 콜백을 설정한다. 콜백 시그니처: def cb(data: bytes) -> None
    void set_callback(py::object cb) {
        py::gil_scoped_acquire gil;
        callback_ = std::move(cb);
    }

    // 한국어 주석: 환경 변수를 다시 읽어 FrameGuard 동작을 갱신한다.
    void reload_env() {
        guard_->reload();
    }

    // 한국어 주석: 라이브뷰 바이트 조각을 전달한다.
    // 완전한 JPEG 프레임이 추출되면 Python 콜백으로 전달하고 true를 반환한다.
    bool on_chunk(py::bytes chunk) {
        // GIL 확보는 py::bytes 접근에 필요하지만, 내부 콜백 호출 시에도 다시 확보한다.
        py::gil_scoped_acquire gil;
        // py::bytes 를 C++ 바이트 시퀀스로 변환
        std::string s = chunk;
        const auto* p = reinterpret_cast<const std::uint8_t*>(s.data());
        const auto  n = static_cast<std::size_t>(s.size());
        if (n == 0) return false;

        if (auto jpeg = guard_->append(p, n)) {
            // 콜백이 설정되어 있으면 bytes로 전달
            if (!callback_.is_none()) {
                try {
                    py::bytes out(reinterpret_cast<const char*>(jpeg->data()), jpeg->size());
                    callback_(out);
                } catch (...) {
                    // 콜백 예외는 무시
                }
            }
            return true;
        }
        return false;
    }

    // 한국어 주석: 직접 완전 프레임을 전달하여 콜백을 호출(테스트용).
    void emit_frame(py::bytes jpeg) {
        py::gil_scoped_acquire gil;
        if (callback_.is_none()) return;
        try { callback_(jpeg); } catch (...) { /* 무시 */ }
    }

private:
    std::unique_ptr<FrameGuard> guard_;
    py::object callback_ = py::none();
};

// 한국어 주석: 전역(간편) 경로도 제공
static std::unique_ptr<LiveViewBridge> g_bridge;

static void set_liveview_callback(py::object cb) {
    py::gil_scoped_acquire gil;
    if (!g_bridge) g_bridge = std::make_unique<LiveViewBridge>();
    g_bridge->set_callback(std::move(cb));
}

static bool push_liveview_chunk(py::bytes chunk) {
    py::gil_scoped_acquire gil;
    if (!g_bridge) g_bridge = std::make_unique<LiveViewBridge>();
    return g_bridge->on_chunk(std::move(chunk));
}

static void reload_frame_guard_env() {
    if (!g_bridge) g_bridge = std::make_unique<LiveViewBridge>();
    g_bridge->reload_env();
}

PYBIND11_MODULE(crsdk_pybridge, m) {
    // 한국어 주석: 모듈 설명
    m.doc() = "SCRSDK LiveView bridge skeleton with FrameGuard (JPEG framing/DHT injection)";

    // 전역 간편 API
    m.def("set_liveview_callback", &set_liveview_callback,
          "라이브뷰 바이트 콜백을 등록한다. 시그니처: def cb(data: bytes) -> None");
    m.def("push_liveview_chunk", &push_liveview_chunk,
          "라이브뷰 바이트 조각을 전달한다. 완전 프레임이 완성되면 콜백을 호출하고 true를 반환한다.");
    m.def("reload_frame_guard_env", &reload_frame_guard_env,
          "환경변수(CAP_FRAME_*)를 다시 읽어 FrameGuard 동작을 갱신한다.");

    // 객체 지향 API
    py::class_<LiveViewBridge>(m, "LiveViewBridge")
        .def(py::init<>())
        .def("set_callback", &LiveViewBridge::set_callback,
             "콜백 등록(시그니처: def cb(data: bytes) -> None)")
        .def("on_chunk", &LiveViewBridge::on_chunk,
             "라이브뷰 바이트 조각을 전달. 완전 프레임이 추출되면 콜백 호출 및 True 반환")
        .def("emit_frame", &LiveViewBridge::emit_frame,
             "완전한 JPEG 프레임을 직접 콜백으로 전달(테스트용)")
        .def("reload_env", &LiveViewBridge::reload_env,
             "환경변수(CAP_FRAME_*) 다시 로드");
}

