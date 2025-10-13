# 프로젝트 파이썬 코드의 문법/형식 점검을 수행한다. (로컬 전용)
# - 문법: compileall로 main.py / app 디렉터리만 컴파일하여 SyntaxError를 조기 발견한다.
# - 선택: ruff와 mypy가 설치되어 있으면 함께 점검한다. 미설치 시 건너뛴다.

param(
  [switch]$Fix  # 포맷 자동수정과 ruff --fix를 수행한다.
)

$ErrorActionPreference = 'Stop'

function Invoke-Step {
  # 주어진 블록을 실행하고 실패 시 상태를 누적한다.
  param(
    [string]$Name,
    [scriptblock]$Body
  )
  Write-Host "==> $Name" -ForegroundColor Cyan
  try {
    & $Body
    if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) { throw "exit=$LASTEXITCODE" }
  } catch {
    Write-Host "[FAIL] $Name : $_" -ForegroundColor Red
    $script:__failed = $true
  }
}

Push-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
try {
  # 리포지토리 루트로 이동한다.
  $repo = Resolve-Path ..
  Set-Location $repo

  $paths = @()
  if (Test-Path 'main.py') { $paths += 'main.py' }
  if (Test-Path 'app') { $paths += 'app' }
  if ($paths.Count -eq 0) {
    Write-Host "점검할 파이썬 경로를 찾지 못했습니다." -ForegroundColor Yellow
    exit 0
  }

  # 1) 문법 검사 (compileall: 대상만 한정)
  Invoke-Step -Name "Python 문법 검사 (compileall)" -Body {
    & python -m compileall -q @paths
  }

  # 2) 포맷/린트 (ruff 존재 시)
  $ruff = Get-Command ruff -ErrorAction SilentlyContinue
  if ($ruff) {
    if ($Fix) {
      Invoke-Step -Name "Ruff 포맷 자동수정" -Body { & ruff format . }
      Invoke-Step -Name "Ruff 린트 (--fix)" -Body { & ruff check --fix . }
    } else {
      Invoke-Step -Name "Ruff 포맷 확인" -Body { & ruff format --check . }
      Invoke-Step -Name "Ruff 린트" -Body { & ruff check . }
    }
  } else {
    Write-Host "ruff 미설치: 린트/포맷 확인 생략" -ForegroundColor Yellow
  }

  # 3) 타입 검사 (mypy 존재 시)
  $mypy = Get-Command mypy -ErrorAction SilentlyContinue
  if ($mypy -and (Test-Path 'app')) {
    Invoke-Step -Name "mypy 타입 검사(app)" -Body { & mypy app }
  } elseif (-not $mypy) {
    Write-Host "mypy 미설치: 타입 검사 생략" -ForegroundColor Yellow
  }

} finally {
  Pop-Location
}

if ($script:__failed) { exit 1 } else { Write-Host "모든 점검을 통과했습니다." -ForegroundColor Green; exit 0 }

