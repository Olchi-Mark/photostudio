// -*- coding: utf-8 -*-
#pragma once

#include <vector>
#include <cstdint>
#include <optional>
#include <chrono>

/*
 * 프레임 가드(FrameGuard)
 * - 목적: 라이브뷰 수신 바이트 스트림에서 "완전한 JPEG 프레임(FFD8~FFD9)"만 잘라 반환한다.
 * - 배경: 일부 장치/환경에서는 조각난 JPEG(MJPEG 조각, DHT 누락 등)로 인해 OpenCV 디코드가 실패할 수 있다.
 * - 방식: 내부 버퍼에 조각을 누적하고 SOI(0xFFD8)~EOI(0xFFD9) 범위를 찾으면 그 구간만 반환한다.
 * - 보정: 옵션에 따라 표준 DHT 세그먼트를 삽입해 디코드 성공률을 높인다.
 * - 가드: 타임아웃/최대 크기 상한으로 비정상 누적을 방지한다.
 */
class FrameGuard {
public:
    // 생성자: 환경변수를 읽어 동작 파라미터를 초기화한다.
    FrameGuard();

    // 바이트 조각을 누적한다. 완전한 JPEG 프레임을 추출하면 즉시 반환한다.
    // 반환값: 추출된 JPEG 프레임(필요 시 DHT 삽입 적용) 또는 std::nullopt
    std::optional<std::vector<std::uint8_t>> append(const std::uint8_t* data, std::size_t len);

    // 환경 파라미터를 갱신한다. (예: 런타임에 ENV를 바꾸고 다시 적용하고 싶을 때)
    void reload();

private:
    // 내부 상태
    std::vector<std::uint8_t> buf_;
    std::size_t max_bytes_;
    std::int64_t timeout_ms_;
    bool inject_dht_;
    bool enable_guard_;
    std::chrono::steady_clock::time_point last_append_time_;

    // 내부 유틸리티
    void loadEnv();
    void pruneIfOversize();
    void pruneUntilSOI();
    void resetIfTimeout();
    std::optional<std::pair<std::size_t,std::size_t>> findJpegSegment() const; // [start,end)
    static void injectDefaultDHT(std::vector<std::uint8_t>& jpeg);
};

