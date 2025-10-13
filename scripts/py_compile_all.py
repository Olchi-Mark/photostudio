# -*- coding: utf-8 -*-
"""모든 .py 파일을 컴파일해 문법/인코딩 오류를 빠르게 점검한다."""
import sys
from pathlib import Path

def main() -> int:
    root = Path.cwd()
    bad = []
    for p in root.rglob('*.py'):
        try:
            # BOM이 있는 파일도 허용
            try:
                src = p.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                src = p.read_text(encoding='utf-8-sig')
            # 파일 선두의 BOM 제거
            if src.startswith('\ufeff'):
                src = src.lstrip('\ufeff')
            compile(src, str(p), 'exec')
        except Exception as e:
            bad.append((p, e))
    if bad:
        print('[COMPILE] 오류 파일 수:', len(bad))
        for p, e in bad:
            info = ''
            try:
                if hasattr(e, 'lineno'):
                    info = f" line={getattr(e,'lineno',None)} col={getattr(e,'offset',None)} msg={getattr(e,'msg','')}"
            except Exception:
                pass
            print(' -', p, '->', type(e).__name__, info)
        return 1
    print('[COMPILE] 모든 .py 파일 컴파일 통과')
    return 0

if __name__ == '__main__':
    sys.exit(main())
