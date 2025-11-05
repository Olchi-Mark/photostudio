import sys
from pathlib import Path
import tokenize
from io import StringIO

def strip_comments(src: str) -> str:
    out = []
    last_lineno = -1
    last_col = 0
    for tok in tokenize.generate_tokens(StringIO(src).readline):
        ttype = tok.type
        tstr = tok.string
        (srow, scol) = tok.start
        (erow, ecol) = tok.end
        if srow > last_lineno:
            last_col = 0
        if scol > last_col:
            out.append(" " * (scol - last_col))
        if ttype != tokenize.COMMENT:
            out.append(tstr)
        last_col = ecol
        last_lineno = erow
    return "".join(out)

p = Path(sys.argv[1])
src = p.read_text(encoding='utf-8', errors='ignore')
text = strip_comments(src)
p.write_text(text, encoding='utf-8')
print('STRIPPED_OK', p)
