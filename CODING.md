# 코딩 규칙 v1.0

## 주석
- 함수·메서드·클래스 첫 줄에 1줄 요약.
  - Py: """설명 한 줄."""
  - C++: /// 설명 한 줄

## 로깅
- Python: logging 사용. print 금지.
  format: "%(asctime)s %(levelname)s %(name)s:%(lineno)d - %(message)s"
  진입, 주요 분기, 외부 I/O, 예외에서 INFO/ERROR 기록.
  
- C++: LOG_I/LOG_E 매크로로 기록. std::cout 직접 사용 금지.

## 에러 처리
- Python: except에서 log.error(...) 후 raise.
- C++: catch(const std::exception& e) { LOG_E(e.what()); } 후 적절 처리.

## 스타일
- Python: PEP8 요지 준수. 공개 함수는 타입힌트.
- C++17: RAII. new/delete 지양. std::unique_ptr 사용.
  헤더는 #pragma once. 경고 최대치 활성(/W4 또는 -Wall -Wextra).

## 설계
- 함수는 한 책임. 60줄 이내 권장.
- 매직 넘버 상수화. 설정은 settings.sample.json에 두고 실제 settings.json은 .gitignore.
- 경로는 하드코딩 금지. Python은 pathlib 사용.

## 커밋 메시지
- 형식: type(scope): summary
  - type: feat, fix, refactor, perf, build, docs, test, chore, revert
  - 예: fix(liveview): 프리즈 방지 sleep 33ms
