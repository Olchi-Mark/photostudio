// -*- coding: utf-8 -*-

// 한국어 주석: SCRSDK 라이브뷰용 pybind11 바인딩 (콜백 풀 방식)
// - 모듈명: scrsdk
// - 경로: bindings/liveview_py.cpp
// - 의존: pybind11/pybind11.h, pybind11/numpy.h
// - 목적: FrameGuard로 완전한 JPEG 프레임만 보장하고, 등록된 콜백 풀에 bytes로 브로드캐스트한다.

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/bytes.h>

#include <cstdint>
#include <vector>
#include <unordered_map>
#include <memory>
#include <atomic>
#include <optional>

#include "../native/frame_guard.h"

namespace py = pybind11;

// 한국어 주석: 라이브뷰 콜백 풀
// 한국어 주석: 단일 생산자/단일 소비자(SPSC) 링 버퍼 - 잠금 없이 동작
// - SDK 콜백 스레드(생산자)와 파이썬 폴링 스레드(소비자)를 분리한다.
class SpscRing {
public:
    // 한국어 주석: 고정 크기 큐를 초기화한다. 용량은 2의 거듭제곱이 아니어도 된다.
    explicit SpscRing(std::size_t cap) : capacity_(cap ? cap : 128), slots_(capacity_) {}

    // 한국어 주석: 프레임을 큐에 적재한다. 가득 찼을 경우 가장 오래된 항목을 덮어쓴다(드롭-올드 정책).
    void enqueue(std::string data) {
        const auto head = head_.load(std::memory_order_relaxed);
        auto next = head + 1;
        if (next - tail_.load(std::memory_order_acquire) > capacity_) {
            // 한국어 주석: 포화 상태 – 가장 오래된 것을 하나 제거한다.
            tail_.store(tail_.load(std::memory_order_relaxed) + 1, std::memory_order_release);
        }
        slots_[head % capacity_] = std::move(data);
        head_.store(next, std::memory_order_release);
    }

    // 한국어 주석: 프레임을 하나 꺼낸다. 없으면 std::nullopt.
    std::optional<std::string> try_dequeue() {
        const auto tail = tail_.load(std::memory_order_relaxed);
        if (tail == head_.load(std::memory_order_acquire)) return std::nullopt;
        auto idx = tail % capacity_;
        std::string out = std::move(slots_[idx]);
        slots_[idx].clear();
        tail_.store(tail + 1, std::memory_order_release);
        return out;
    }

    // 한국어 주석: 큐에 쌓인 개수를 반환한다.
    std::size_t size() const {
        auto h = head_.load(std::memory_order_acquire);
        auto t = tail_.load(std::memory_order_acquire);
        return (h >= t) ? static_cast<std::size_t>(h - t) : 0;
    }

    // 한국어 주석: 용량을 반환한다.
    std::size_t capacity() const { return capacity_; }

private:
    std::size_t capacity_;
    std::vector<std::string> slots_;
    std::atomic<std::size_t> head_{0};
    std::atomic<std::size_t> tail_{0};
};

// 한국어 주석: 라이브뷰 콜백 풀(프레임 가드 + 콜백 브로드캐스트 + SPSC 큐)
class LiveViewPool {
public:
    // 한국어 주석: 생성자 – FrameGuard 초기화
    LiveViewPool() : guard_(std::make_unique<FrameGuard>()) {}

    // 한국어 주석: 콜백을 풀에 등록하고 ID를 반환한다. 콜백 시그니처: def cb(data: bytes) -> None
    int add_callback(py::object cb) {
        py::gil_scoped_acquire gil;
        const int id = ++seq_;
        callbacks_.emplace(id, std::move(cb));
        return id;
    }

    // 한국어 주석: ID로 콜백을 제거한다. 성공 시 True.
    bool remove_callback(int id) {
        py::gil_scoped_acquire gil;
        return callbacks_.erase(id) > 0;
    }

    // 한국어 주석: 모든 콜백을 제거한다.
    void clear_callbacks() {
        py::gil_scoped_acquire gil;
        callbacks_.clear();
    }

    // 한국어 주석: 등록된 콜백 수를 반환한다.
    std::size_t size() const {
        return callbacks_.size();
    }

    // 한국어 주석: 환경변수(CAP_FRAME_*)를 다시 읽어 FrameGuard 동작을 갱신한다.
    void reload_env() { guard_->reload(); }

    // 한국어 주석: 라이브뷰 바이트 조각을 전달한다. 완전한 JPEG 프레임이 완성되면 큐에 적재한다(콜백 직접 호출 금지).
    bool on_chunk(py::bytes chunk) {
        py::gil_scoped_acquire gil;
        std::string s = chunk; // bytes -> std::string
        const auto* p = reinterpret_cast<const std::uint8_t*>(s.data());
        const auto  n = static_cast<std::size_t>(s.size());
        if (n == 0) return false;
        if (auto jpeg = guard_->append(p, n)) {
            queue_.enqueue(std::string(reinterpret_cast<const char*>(jpeg->data()), jpeg->size()));
            return true;
        }
        return false;
    }

    // 한국어 주석: 큐에서 프레임을 하나 꺼내 등록된 콜백에 브로드캐스트한다. 콜백 호출 수를 반환.
    int poll_broadcast(int max_n = 1) {
        py::gil_scoped_acquire gil;
        int called = 0;
        while (max_n-- > 0) {
            auto item = queue_.try_dequeue();
            if (!item) break;
            py::bytes out(item->data(), item->size());
            for (auto it = callbacks_.begin(); it != callbacks_.end(); ++it) {
                try { it->second(out); ++called; } catch (...) { /* 무시 */ }
            }
        }
        return called;
    }

    // 한국어 주석: 큐에서 프레임 하나를 꺼내 bytes로 반환(None 가능).
    py::object poll_once() {
        py::gil_scoped_acquire gil;
        auto item = queue_.try_dequeue();
        if (!item) return py::none();
        return py::bytes(item->data(), item->size());
    }

    // 한국어 주석: 큐 크기/용량 조회
    std::size_t queue_size() const { return queue_.size(); }
    std::size_t queue_capacity() const { return queue_.capacity(); }

private:
    std::unique_ptr<FrameGuard> guard_;
    std::unordered_map<int, py::object> callbacks_;
    std::atomic<int> seq_{0};
    SpscRing queue_{256};
    // 한국어 주석: 소스 모드 분기(팬·틸트 등) – 확장을 위해 보관
    enum class SourceMode { SDK, PTZ_HTTP };
    SourceMode mode_ = SourceMode::SDK;
};

// 한국어 주석: 전역 풀(간편 API)
static std::unique_ptr<LiveViewPool> g_pool;

// 한국어 주석: 전역 – 콜백 등록
static int add_callback(py::object cb) {
    py::gil_scoped_acquire gil;
    if (!g_pool) g_pool = std::make_unique<LiveViewPool>();
    return g_pool->add_callback(std::move(cb));
}

// 한국어 주석: 전역 – 콜백 제거
static bool remove_callback(int id) {
    py::gil_scoped_acquire gil;
    if (!g_pool) return false;
    return g_pool->remove_callback(id);
}

// 한국어 주석: 전역 – 콜백 전부 제거
static void clear_callbacks() {
    py::gil_scoped_acquire gil;
    if (g_pool) g_pool->clear_callbacks();
}

// 한국어 주석: 전역 – 조각 입력
static bool push_chunk(py::bytes chunk) {
    py::gil_scoped_acquire gil;
    if (!g_pool) g_pool = std::make_unique<LiveViewPool>();
    return g_pool->on_chunk(std::move(chunk));
}

// 한국어 주석: 전역 – ENV 재적용
static void reload_env() {
    if (!g_pool) g_pool = std::make_unique<LiveViewPool>();
    g_pool->reload_env();
}

// 한국어 주석: pybind11 모듈 정의 (모듈명: scrsdk)
PYBIND11_MODULE(scrsdk, m) {
    m.doc() = "SCRSDK LiveView callback-pool bindings with FrameGuard (JPEG framing/DHT injection)";

    // 전역 API
    m.def("add_callback", &add_callback, "라이브뷰 콜백 등록 (def cb(data: bytes) -> None) → id 반환");
    m.def("remove_callback", &remove_callback, "등록된 콜백 제거(id)");
    m.def("clear_callbacks", &clear_callbacks, "모든 콜백 제거");
    // 한국어 주석: SDK 콜백 스레드는 push_chunk만 호출(큐 적재). 파이썬 폴링 스레드에서 poll_broadcast/poll_once를 호출한다.
    m.def("push_chunk", &push_chunk, "라이브뷰 바이트 조각 입력 – 완전 프레임이면 큐에 적재(콜백 직접 호출 없음)");
    m.def("poll_broadcast", [](int max_n){
        if (!g_pool) g_pool = std::make_unique<LiveViewPool>();
        return g_pool->poll_broadcast(max_n);
    }, py::arg("max_n")=1, "큐에서 최대 max_n개 프레임을 꺼내 등록 콜백에 브로드캐스트");
    m.def("poll_once", [](){
        if (!g_pool) g_pool = std::make_unique<LiveViewPool>();
        return g_pool->poll_once();
    }, "큐에서 프레임 하나를 꺼내 bytes로 반환(None 가능)");
    m.def("queue_size", [](){ if (!g_pool) g_pool = std::make_unique<LiveViewPool>(); return g_pool->size(); }, "등록 콜백 수 반환(호환용)");
    m.def("queue_len", [](){ if (!g_pool) g_pool = std::make_unique<LiveViewPool>(); return g_pool->queue_size(); }, "큐에 쌓인 프레임 수");
    m.def("reload_env", &reload_env, "CAP_FRAME_* 환경변수 재적용");

    // 객체지향 API
    py::class_<LiveViewPool>(m, "LiveViewPool")
        .def(py::init<>())
        .def("add_callback", &LiveViewPool::add_callback, "콜백 등록(id 반환)")
        .def("remove_callback", &LiveViewPool::remove_callback, "콜백 제거")
        .def("clear_callbacks", &LiveViewPool::clear_callbacks, "모든 콜백 제거")
        .def("size", &LiveViewPool::size, "콜백 수 반환")
        .def("on_chunk", &LiveViewPool::on_chunk, "라이브뷰 바이트 조각 입력 → 완전 프레임이면 큐에 적재")
        .def("poll_broadcast", &LiveViewPool::poll_broadcast, py::arg("max_n")=1, "큐에서 최대 max_n개 프레임을 브로드캐스트")
        .def("poll_once", &LiveViewPool::poll_once, "큐에서 프레임 하나를 bytes로 반환(None 가능)")
        .def("queue_len", &LiveViewPool::queue_size, "큐에 쌓인 프레임 수")
        .def("reload_env", &LiveViewPool::reload_env, "CAP_FRAME_* 재적용");
}
