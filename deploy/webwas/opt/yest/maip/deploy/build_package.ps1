# 운영 서버 배포 파일 3개를 만든다(Windows 개발 PC) — build_package.sh 와 같은 묶음이다. 절차: docs/DEPLOYMENT.md §0
#   .\deploy\build_package.ps1          → deploy\dist\ 에 maip-<커밋>.tar.gz · maip-<커밋>.tar.gz.sha256 · deploy.sh
#   .\deploy\build_package.ps1 <ref>    → origin/main 대신 그 커밋(받지 않는다 — 원격 인증 없이 로컬에 있는 커밋으로 묶는다)
# 필요: git, Windows 기본 tar.exe(bsdtar), Python pip — .venv 가 있으면 그것, 없으면 PATH 의 py·python(다른 pip 는 $env:PIP). 실행 정책에 막히면
#   powershell -ExecutionPolicy Bypass -File deploy\build_package.ps1 <커밋>
# 소스는 풀지 않고 git archive 의 tar 항목을 그대로 옮긴다 — Windows 에서 풀면 실행 권한(deploy.sh 등)이 사라진다.
# Windows PowerShell 5.1 이 한글을 읽게 UTF-8 BOM 으로 저장한다.
param([string]$Ref = '')
$ErrorActionPreference = 'Stop'

function Invoke-Native {
    # 네이티브 명령은 실패해도 예외가 나지 않는다 — 종료 코드를 본다
    $exe = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "실패(종료 코드 $LASTEXITCODE): $exe $rest" }
}

function Write-Lf([string]$Path, [string[]]$Lines) {
    # 서버 sha256sum -c 가 읽는다 — LF·BOM 없이 쓴다
    [IO.File]::WriteAllText($Path, (($Lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
}

$root = (git rev-parse --show-toplevel)
if ($LASTEXITCODE -ne 0) { throw '저장소 안에서 실행한다' }
Push-Location $root
$work = Join-Path ([IO.Path]::GetTempPath()) ('maip-build-' + [guid]::NewGuid())
$oldPipConfig = $env:PIP_CONFIG_FILE
try {
    if (-not $Ref) {
        git fetch -q origin main
        if ($LASTEXITCODE -ne 0) {
            throw 'origin main 을 받지 못했다(원격 인증 등). 커밋을 지정해 다시 실행한다: .\deploy\build_package.ps1 <커밋>'
        }
        $Ref = 'origin/main'
    }
    $ver = (git rev-parse --short $Ref)
    if ($LASTEXITCODE -ne 0) { throw "커밋을 찾지 못했다: $Ref" }
    $name = "maip-$ver"
    # wheel 은 --platform 으로 받으므로 개발 venv 가 아니어도 된다 — .venv 가 없는 PC 는 PATH 의 Python 을 쓴다
    $venvPy = Join-Path $root '.venv\Scripts\python.exe'
    $pip = @(if ($env:PIP) { $env:PIP }   # @( ) — 하나짜리도 배열로 둬야 @pip 이 글자로 쪼개지지 않는다
             elseif (Test-Path $venvPy) { $venvPy, '-m', 'pip' }
             elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py', '-3', '-m', 'pip' }
             elseif (Get-Command python -ErrorAction SilentlyContinue) { 'python', '-m', 'pip' }
             else { throw 'pip 을 찾지 못했다 — Python 을 설치하거나 $env:PIP 에 pip.exe 경로를 넣는다' })
    $tar = if ($env:TAR) { $env:TAR } else { Join-Path $env:SystemRoot 'System32\tar.exe' }   # Git 의 GNU tar 는 @archive 를 모른다
    $dist = Join-Path $root 'deploy\dist'
    $wheels = Join-Path $work "$name\wheels"
    $srcTar = Join-Path $work 'source.tar'

    New-Item -ItemType Directory -Force -Path $wheels, $dist | Out-Null
    Invoke-Native git archive --format=tar "--prefix=$name/source/" -o $srcTar $Ref
    Invoke-Native $tar -xf $srcTar -C $work "$name/source/requirements.txt" "$name/source/deploy/deploy.sh"

    # 개발 PC 의 pip 설정(사내·NVIDIA 보조 인덱스 등)을 읽지 않는다 — 서버 wheel 은 pypi.org 에서만 받는다. 닿지 않는 인덱스가 있으면 재시도로 멈춘다
    $env:PIP_CONFIG_FILE = if ($env:OS -eq 'Windows_NT') { 'nul' } else { '/dev/null' }   # pip 이 os.devnull 과 같을 때만 설정 파일을 건너뛴다
    Invoke-Native @pip download -q -r (Join-Path $work "$name\source\requirements.txt") -d $wheels --only-binary=:all: `
        --implementation cp --python-version 3.12 --abi cp312 `
        --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64

    $sums = Get-ChildItem -Path $wheels -Filter *.whl | Sort-Object Name | ForEach-Object {
        '{0}  ./{1}' -f (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower(), $_.Name
    }
    Write-Lf (Join-Path $wheels 'SHA256SUMS.txt') $sums
    $full = (git rev-parse $Ref)
    $date = (git log -1 --format=%cd --date=iso $Ref)
    Write-Lf (Join-Path $work "$name\VERSION") @("$full $date")

    $out = Join-Path $dist "$name.tar.gz"
    Invoke-Native $tar -czf $out -C $work "@$srcTar" "$name/wheels" "$name/VERSION"
    Write-Lf "$out.sha256" @('{0}  {1}.tar.gz' -f (Get-FileHash -Algorithm SHA256 $out).Hash.ToLower(), $name)
    Copy-Item -Force (Join-Path $work "$name\source\deploy\deploy.sh") (Join-Path $dist 'deploy.sh')   # 그 커밋의 배포 스크립트

    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "$Ref → deploy\dist\ ($mb MB)"
    Write-Host '  서버 /home/yhan/dist/ 에 바이너리 모드로 올린다(DEPLOYMENT §0):'
    Write-Host "    deploy\dist\$name.tar.gz  deploy\dist\$name.tar.gz.sha256  deploy\dist\deploy.sh"
}
finally {
    $env:PIP_CONFIG_FILE = $oldPipConfig
    Pop-Location
    if (Test-Path $work) { Remove-Item -Recurse -Force $work }
}
