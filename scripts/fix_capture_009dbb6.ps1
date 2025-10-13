Param()

# capture.py의 손상된 한국어 문자열과 따옴표 오류를 교정한다.
$p = "app/pages/capture.py"
try {
    $enc = [System.Text.Encoding]::UTF8
    $lines = [System.IO.File]::ReadAllLines($p, $enc)

    # 라이브뷰 시작 로그 라인 정리 (주석 라인은 선택적, try+log 라인은 강제 치환)
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match '^\s*# .*라이브뷰.*진입.*로그') {
            $lines[$i] = '        # 라이브뷰 시작 진입을 로깅한다.'
            break
        }
    }
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match '^\s*try:\s*_log\.info\(') {
            $lines[$i] = '        try: _log.info("[CONN] start 진입")'
            break
        }
    }

    # BusyOverlay 기본 문구 정리
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match 'self\.busy = BusyOverlay\(') {
            $lines[$i] = '        self.busy = BusyOverlay(self, "카메라 연결 중")'
            break
        }
    }
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match 'self\.busy\.setText\(') {
            $lines[$i] = '            self.busy.setText("카메라 연결 중")'
            break
        }
    }
    # 라인 기반 교정 후에도 여전히 손상이 남아있을 수 있어, 원문 텍스트 치환을 한 번 더 수행한다.
    $text = [System.IO.File]::ReadAllText($p, $enc)
    $arr = $text -split "`r?`n"
    for ($i = 0; $i -lt $arr.Length; $i++) {
        if ($arr[$i] -like '*BusyOverlay(*') {
            $arr[$i] = '        self.busy = BusyOverlay(self, "카메라 연결 중")'
        }
        if ($arr[$i] -like '*busy.setText(*') {
            $arr[$i] = '            self.busy.setText("카메라 연결 중")'
        }
        if ($arr[$i] -like 'try: _log.info(*') {
            $arr[$i] = '        try: _log.info("[CONN] start 진입")'
        }
    }
    $text2 = [string]::Join([Environment]::NewLine, $arr)
    [System.IO.File]::WriteAllText($p, $text2, $enc)
    Write-Output "FIX_APPLIED"
}
catch {
    Write-Error $_
    exit 1
}
