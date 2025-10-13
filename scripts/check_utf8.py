# -*- coding: utf-8 -*-
"""UTF-8 인코딩 검증 스크립트.

레포 내 .py 파일을 UTF-8로 열어보며 디코딩 오류를 리포트한다.
"""
import sys
from pathlib import Path

def main() -> int:
    root = Path.cwd()
    bad = []
    for p in root.rglob('*.py'):
        try:
            _ = p.read_text(encoding='utf-8')
        except Exception as e:
            bad.append((p, e))
    if bad:
        print('[UTF8] 디코딩 오류 파일 수:', len(bad))
        for p, e in bad:
            print(' -', p, '->', repr(e))
        return 1
    print('[UTF8] 모든 .py 파일 UTF-8 정상')
    return 0

if __name__ == '__main__':
    sys.exit(main())

