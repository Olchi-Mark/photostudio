# app/fonts.py
from PySide6.QtGui import QFontDatabase

FONT_FILES = [
    "app/assets/fonts/S-CoreDream-4Regular.otf",
    "app/assets/fonts/S-CoreDream-5Medium.otf",
    "app/assets/fonts/S-CoreDream-7ExtraBold.otf",
    "app/assets/fonts/Spectral-Regular.ttf",
    "app/assets/fonts/Spectral-Bold.ttf",
]

def register_fonts() -> dict:
    loaded = set()
    for path in FONT_FILES:
        fid = QFontDatabase.addApplicationFont(path)
        if fid != -1:
            for fam in QFontDatabase.applicationFontFamilies(fid):
                loaded.add(fam)

    def resolve_family(candidates):
        fams = [f.lower() for f in QFontDatabase.families()]
        for c in candidates:
            if c.lower() in fams:
                idx = fams.index(c.lower())
                return QFontDatabase.families()[idx]
        for c in candidates:
            for i, f in enumerate(fams):
                if c.lower() in f:
                    return QFontDatabase.families()[i]
        return candidates[0]

    score = resolve_family(["S-Core Dream", "S-CoreDream", "S Core Dream"])

    return {
        "body_family": score,
        "heading_family": score,   # 특별히 지정하지 않는 이상 헤딩도 전부 S-Core Dream 사용
        "loaded_families": sorted(loaded),
    }
