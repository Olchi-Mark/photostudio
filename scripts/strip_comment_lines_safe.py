import sys
from pathlib import Path

def strip_comments_linewise(text: str) -> str:
    out_lines = []
    for line in text.splitlines():
        s = line
        i = 0
        in_sq = False
        in_dq = False
        escaped = False
        cut = None
        while i < len(s):
            ch = s[i]
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == "'" and not in_dq:
                in_sq = not in_sq
            elif ch == '"' and not in_sq:
                in_dq = not in_dq
            elif ch == '#' and not in_sq and not in_dq:
                cut = i
                break
            i += 1
        if cut is not None:
            s = s[:cut].rstrip()
        if s.strip().startswith('#'):
            s = ''
        out_lines.append(s)
    return '\n'.join(out_lines) + ('\n' if text.endswith('\n') else '')

p = Path(sys.argv[1])
src = p.read_text(encoding='utf-8', errors='ignore')
res = strip_comments_linewise(src)
p.write_text(res, encoding='utf-8')
print('LINEWISE_STRIPPED', p)
