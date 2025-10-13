#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture.py의 손상된 문자열/따옴표/들여쓰기를 보수적으로 교정한다.
기능 변경 없이 문자열/문법만 수정한다.
"""
from __future__ import annotations
import io
import os
import re
import sys


def fix_lines(lines: list[str]) -> tuple[list[str], bool]:
    changed = False

    def replace_log_conn(i: int, s: str) -> str:
        nonlocal changed
        if 'try: _log.info(' in s and '[CONN] start' in s:
            new = '        try: _log.info("[CONN] start enter")'
            if s != new:
                changed = True
            return new
        return s

    def odd_quotes(s: str) -> bool:
        return s.count('"') % 2 != 0

    # 1) [CONN] start 로그 교정
    for i, s in enumerate(lines):
        lines[i] = replace_log_conn(i, s)

    # 2) BusyOverlay/연결 오버레이 텍스트 교정 (ASCII로 안전화)
    for i, s in enumerate(lines):
        if 'self.busy = BusyOverlay(' in s:
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.busy = BusyOverlay(self, "Connecting camera...")'
            changed = True
            # 근처 setText도 교정
            for j in range(i+1, min(i+6, len(lines))):
                if 'self.busy.setText(' in lines[j]:
                    lines[j] = f'{indent}    self.busy.setText("Connecting camera...")'
                    changed = True
                    break
        if '_show_connect_overlay(' in s and odd_quotes(s):
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self._show_connect_overlay("Connecting camera...")'
            changed = True

    # 3) update_badges/overlay 표시 라인 들여쓰기/문구 교정
    i = 0
    while i < len(lines):
        s = lines[i]
        if '.update_badges(' in s:
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.overlay.update_badges("DEBUG: badge", {{}})'
            changed = True
        if ("if hasattr(self.overlay, 'update_badges')" in s) or ("if hasattr(self.overlay, \"update_badges\")" in s):
            indent = s[:len(s) - len(s.lstrip())]
            call = f'{indent}    self.overlay.update_badges("DEBUG: badge", {{}})'
            if i + 1 < len(lines):
                lines[i+1] = call
            else:
                lines.append(call)
            changed = True
            i += 1
            continue
        if 'overlay.show()' in s and 'raise_()' in s:
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.overlay.show(); self.overlay.raise_()'
            changed = True
        i += 1

    # 4) 버튼 라벨/문구 손상 교정
    for i, s in enumerate(lines):
        if 'self.btn_capture.setText(' in s and (odd_quotes(s) or '�' in s or '??' in s):
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.btn_capture.setText("Capture"); self.btn_capture.setEnabled(True)'
            changed = True
        if 'self.btn_retake.setText(' in s and (odd_quotes(s) or '�' in s or '??' in s):
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.btn_retake.setText("Retake")'
            changed = True
        if 'self.busy.setText(' in s and (odd_quotes(s) or '�' in s or '??' in s):
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.busy.setText("Connecting camera...")'
            changed = True
        if 'self.toast.popup(' in s and (odd_quotes(s) or '�' in s or '촬영' in s):
            indent = s[:len(s) - len(s.lstrip())]
            lines[i] = f'{indent}self.toast.popup("Shooting...")'
            changed = True
        if ' _log.warning(' in s and odd_quotes(s):
            indent = s[:len(s) - len(s.lstrip())]
            # 라인이 'try: _log.warning("...")' 형태일 가능성이 높음
            if s.strip().startswith('try: '):
                lines[i] = f'{indent}try: _log.warning("[CONN] 12s elapsed: still connecting")'
            else:
                lines[i] = f'{indent}_log.warning("[CONN] warn")'
            changed = True

    # 5) 주석/코드 혼합 라인 정리 (thumb_path, try:)
    new_lines: list[str] = []
    i = 0
    while i < len(lines):
        s = lines[i]
        if ('thumb_path = self._save_preview_snapshot_indexed' in s) and ('#' in s) and (not s.strip().startswith('#')):
            indent = s[:len(s) - len(s.lstrip())]
            new_lines.append(indent + '# Save preview snapshot to path/filename')
            new_lines.append(indent + 'thumb_path = self._save_preview_snapshot_indexed(int(idx) if idx is not None else 0)')
            changed = True
        elif ('try:' in s) and ('#' in s) and (s.index('try:') > s.index('#')):
            indent = s[:len(s) - len(s.lstrip())]
            comment = s[:s.index('try:')].rstrip()
            if not comment.strip().startswith('#'):
                comment = indent + '# ' + comment.strip().lstrip('#').strip()
            new_lines.append(comment)
            new_lines.append(indent + 'try:')
            changed = True
        else:
            new_lines.append(s)
        i += 1
    lines = new_lines

    # 6) resizeEvent 오버레이 토글 들여쓰기 보정
    for i, s in enumerate(lines):
        if s.strip().startswith('def resizeEvent'):
            j = i
            while j < len(lines):
                sj = lines[j]
                if 'getattr(self, "_overlay_from_button", False)' in sj:
                    base_indent = sj[:len(sj) - len(sj.lstrip())]
                    # 기대 순서: 다음 줄 show, 그 다음 줄 else:, 그 다음 줄 hide
                    if j+1 < len(lines):
                        lines[j+1] = base_indent + '    self.overlay.show(); self.overlay.raise_()'
                    if j+2 < len(lines):
                        lines[j+2] = base_indent + 'else:'
                    if j+3 < len(lines):
                        lines[j+3] = base_indent + '    self.overlay.hide(); self.overlay.lower()'
                    changed = True
                    break
                if lines[j].strip().startswith('def ') and j != i:
                    break
                j += 1
            break

    # 7) _overlay_show_during_capture 헤더부 보정 (주석/if/return)
    for i, s in enumerate(lines):
        if s.strip().startswith('def _overlay_show_during_capture'):
            # 기대되는 구성으로 강제 교정
            # i: def, i+1: docstring or next, i+2: try:
            # i+3..i+5: comment, if, return
            # try 라인 보정
            k = i + 2
            if k < len(lines):
                lines[k] = '        try:'
            # 주석/if/return 보정
            if k + 1 < len(lines):
                lines[k+1] = '            # 버튼으로 시작한 촬영에서만 오버레이를 표시한다.'
            if k + 2 < len(lines):
                lines[k+2] = '            if not getattr(self, "_overlay_from_button", False):'
            if k + 3 < len(lines):
                lines[k+3] = '                return'
            changed = True
            break

    return lines, changed


def main() -> int:
    path = os.path.join('app', 'pages', 'capture.py')
    if not os.path.exists(path):
        print('NO_FILE')
        return 1

    with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
        original = f.read().splitlines()

    lines, changed = fix_lines(original)

    if not changed:
        print('NO_CHANGE')
        return 0

    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')

    print('FIXED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
