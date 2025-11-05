// -*- coding: utf-8 -*-
#include "frame_guard.h"

#include <cstdlib>
#include <string>

// 한국어 주석: 표준 DHT 테이블(예시). 실제 운영 시에는 표준 기본 DHT 전체를 채워 넣는 것을 권장한다.
// 참고: 일부 MJPEG 스트림은 DHT(FFC4)가 누락되어 있어 OpenCV 디코드가 실패할 수 있다.
static const std::uint8_t kDefaultDHT[] = {
    // 간단한 placeholder. 실제 표준 DHT 바이트 시퀀스를 사용하세요.
    0xFF, 0xC4, 0x00, 0x1F,
    0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01,
    0x01, 0x01, 0x01, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00
};

// 한국어 주석: 환경변수 파서
static inline long long env_i64(const char* key, long long def) {
    if (const char* v = std::getenv(key)) {
        try { return std::stoll(v); } catch (...) {}
    }
    return def;
}

static inline bool env_on(const char* key, bool def=false) {
    if (const char* v = std::getenv(key)) {
        std::string s(v);
        for (auto& c : s) c = static_cast<char>(::tolower(static_cast<unsigned char>(c)));
        return (s=="1" || s=="true" || s=="on");
    }
    return def;
}

FrameGuard::FrameGuard() {
    loadEnv();
    last_append_time_ = std::chrono::steady_clock::now();
}

void FrameGuard::reload() {
    loadEnv();
}

void FrameGuard::loadEnv() {
    // 한국어 주석: 최대 프레임 버퍼 크기(바이트), 프레임 타임아웃(ms), DHT 삽입 여부, 가드 활성화 여부
    max_bytes_   = static_cast<std::size_t>(env_i64("CAP_MAX_FRAME_BYTES", 20*1024*1024)); // 20MB
    timeout_ms_  = env_i64("CAP_FRAME_TIMEOUT_MS", 300);
    inject_dht_  = env_on("CAP_INJECT_DHT", true);
    enable_guard_= env_on("CAP_FRAME_GUARD", true);
}

void FrameGuard::pruneIfOversize() {
    if (buf_.size() > max_bytes_) {
        // 한국어 주석: SOI 전부를 제거하여 공간 확보
        pruneUntilSOI();
        if (buf_.size() > max_bytes_) buf_.clear();
    }
}

void FrameGuard::resetIfTimeout() {
    auto now = std::chrono::steady_clock::now();
    auto ms  = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_append_time_).count();
    if (ms > timeout_ms_) {
        // 한국어 주석: 오래된 조각은 프레임 경계 파손 가능성이 크므로 버린다.
        buf_.clear();
    }
}

void FrameGuard::pruneUntilSOI() {
    // 한국어 주석: SOI(FFD8)를 찾을 때까지 앞부분 제거
    for (std::size_t i=0; i+1<buf_.size(); ++i) {
        if (buf_[i]==0xFF && buf_[i+1]==0xD8) {
            if (i>0) buf_.erase(buf_.begin(), buf_.begin()+static_cast<std::ptrdiff_t>(i));
            return;
        }
    }
    // SOI 자체가 없으면 전체 폐기
    buf_.clear();
}

std::optional<std::pair<std::size_t,std::size_t>> FrameGuard::findJpegSegment() const {
    // SOI 검색
    std::size_t soi = static_cast<std::size_t>(-1);
    for (std::size_t i=0; i+1<buf_.size(); ++i) {
        if (buf_[i]==0xFF && buf_[i+1]==0xD8) { soi=i; break; }
    }
    if (soi==static_cast<std::size_t>(-1)) return std::nullopt;
    // EOI 검색 (SOI 이후)
    for (std::size_t j=soi+2; j+1<buf_.size(); ++j) {
        if (buf_[j]==0xFF && buf_[j+1]==0xD9) {
            return std::make_pair(soi, j+2); // [SOI, EOI] 구간
        }
    }
    return std::nullopt;
}

void FrameGuard::injectDefaultDHT(std::vector<std::uint8_t>& jpeg) {
    // 한국어 주석: DHT(FFC4) 세그먼트가 없으면 SOI 뒤에 기본 DHT를 삽입한다.
    bool hasDHT = false;
    for (std::size_t i=0; i+1<jpeg.size(); ++i) {
        if (jpeg[i]==0xFF && jpeg[i+1]==0xC4) { hasDHT=true; break; }
    }
    if (!hasDHT && !jpeg.empty() && jpeg[0]==0xFF && jpeg[1]==0xD8 && kDefaultDHT[0]==0xFF) {
        jpeg.insert(jpeg.begin()+2, std::begin(kDefaultDHT), std::end(kDefaultDHT));
    }
}

std::optional<std::vector<std::uint8_t>> FrameGuard::append(const std::uint8_t* data, std::size_t len) {
    if (!enable_guard_) {
        // 한국어 주석: 가드 비활성화 시에는 누적만 수행하고 추출하지 않는다.
        buf_.insert(buf_.end(), data, data+len);
        last_append_time_ = std::chrono::steady_clock::now();
        return std::nullopt;
    }

    resetIfTimeout();
    buf_.insert(buf_.end(), data, data+len);
    last_append_time_ = std::chrono::steady_clock::now();

    pruneIfOversize();

    auto seg = findJpegSegment();
    if (!seg) return std::nullopt;
    auto [s,e] = *seg;
    if (e <= s || (e - s) < 2048) {
        // 한국어 주석: 비정상적으로 작은 프레임은 폐기하고 다음 프레임을 기다린다.
        buf_.erase(buf_.begin(), buf_.begin()+static_cast<std::ptrdiff_t>(e));
        return std::nullopt;
    }
    std::vector<std::uint8_t> out(buf_.begin()+static_cast<std::ptrdiff_t>(s),
                                  buf_.begin()+static_cast<std::ptrdiff_t>(e));
    // 사용한 구간 제거
    buf_.erase(buf_.begin(), buf_.begin()+static_cast<std::ptrdiff_t>(e));

    if (inject_dht_) injectDefaultDHT(out);
    return out;
}

