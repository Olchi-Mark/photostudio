Param()

# capture.py의 37cb6ce 시점에서 손상된 한국어 문자열을 교정한다.
$p = "app/pages/capture.py"
try {
    $enc = [System.Text.Encoding]::UTF8
    $lines = [System.IO.File]::ReadAllLines($p, $enc)

    # 안전 범위 체크 후 라인 교체(1-based: 281, 297, 299)
    if ($lines.Length -ge 700) {
        $lines[280] = '        try: _log.info("[CONN] start 진입")'
        $lines[296] = '        self.busy = BusyOverlay(self, "Connecting camera...")'
        $lines[298] = '            self.busy.setText("Connecting camera...")'
        $lines[345] = '        self._show_connect_overlay("Connecting camera...")'
        $lines[662] = '                    self.overlay.update_badges("DEBUG: badge", {})'
        $lines[665] = '            self.btn_capture.setText("Capture"); self.btn_capture.setEnabled(True)'
        # resizeEvent 내 오버레이 토글 들여쓰기 보정
        $lines[363] = '                    self.overlay.show(); self.overlay.raise_()'
        $lines[364] = '                else:'
        $lines[365] = '                    self.overlay.hide(); self.overlay.lower()'
        # update_badges 들여쓰기 보정
        $lines[485] = "                if hasattr(self.overlay, 'update_badges'):"
        $lines[486] = '                    self.overlay.update_badges("DEBUG: badge", {})'
        $lines[487] = '                self.overlay.show(); self.overlay.raise_()'
        $lines[488] = ''
        $lines[490] = '            except Exception: pass'
        [System.IO.File]::WriteAllLines($p, $lines, $enc)
        Write-Output "FIX37_APPLIED"
    } else {
        Write-Output "FIX37_SKIPPED:FILE_TOO_SHORT"
    }
}
catch {
    Write-Error $_
    exit 1
}
