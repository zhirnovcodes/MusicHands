$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $AppDir "..\..")
$ReaderDir = Join-Path $RepoRoot "reader"
$BridgeDir = Join-Path $RepoRoot "bridge"

Push-Location $AppDir
try {
    Get-Process MusicHands -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process MusicHandsSetup -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    Write-Host "Ensuring MediaPipe gesture model is present..."
    $env:PYTHONPATH = "$ReaderDir;$BridgeDir;$AppDir"
    python -c "from musichands_reader.app import ensure_model; ensure_model()"

    $ModelPath = Join-Path $ReaderDir "models\gesture_recognizer.task"
    $ReaderHtml = Join-Path $ReaderDir "web\index.html"
    $ReaderEnabled = Join-Path $ReaderDir "enabled.json"
    $ReaderCamera = Join-Path $ReaderDir "camera.json"
    $BridgeConfig = Join-Path $BridgeDir "config.json"
    $LoopMidiZip = Join-Path $BridgeDir "musichands_bridge\loopMidi_install\loopMIDISetup_1_0_16_27.zip"
    $AppHtml = Join-Path $AppDir "web\index.html"

    $DistRoot = Join-Path $AppDir "dist"
    if (Test-Path $DistRoot) {
        Remove-Item -Recurse -Force $DistRoot
    }

    Write-Host "Building unpacked application directory (--onedir --noconsole)..."
    python -m PyInstaller --noconfirm --clean --onedir --noconsole `
        --contents-directory "_internal" `
        --name MusicHands `
        --paths "$AppDir" `
        --paths "$ReaderDir" `
        --paths "$BridgeDir" `
        --collect-all mediapipe `
        --collect-all webview `
        --exclude-module tkinter `
        --hidden-import musichands_reader.app `
        --hidden-import musichands_bridge.app `
        --hidden-import mido.backends.rtmidi `
        --hidden-import rtmidi `
        "musichands_app\__main__.py"

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }

    $AppBundleDir = Join-Path $DistRoot "MusicHands"

    # Lay down application assets & default configuration directly in the application folder
    New-Item -ItemType Directory -Force -Path (Join-Path $AppBundleDir "app_web") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $AppBundleDir "web") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $AppBundleDir "models") | Out-Null

    Copy-Item -Force $AppHtml (Join-Path $AppBundleDir "app_web\index.html")
    Copy-Item -Force $ReaderHtml (Join-Path $AppBundleDir "web\index.html")
    Copy-Item -Force $ModelPath (Join-Path $AppBundleDir "models\gesture_recognizer.task")
    Copy-Item -Force $ReaderEnabled (Join-Path $AppBundleDir "enabled.json")
    Copy-Item -Force $ReaderCamera (Join-Path $AppBundleDir "camera.json")
    Copy-Item -Force $BridgeConfig (Join-Path $AppBundleDir "config.json")

    if (Test-Path (Join-Path $AppBundleDir "_internal\cv2\opencv_videoio_ffmpeg500_64.dll")) {
        Remove-Item -Force (Join-Path $AppBundleDir "_internal\cv2\opencv_videoio_ffmpeg500_64.dll")
    }
    $FallbackDriverDir = Join-Path $AppBundleDir "_internal\musichands_bridge\loopMidi_install"
    New-Item -ItemType Directory -Force -Path $FallbackDriverDir | Out-Null
    Copy-Item -Force $LoopMidiZip (Join-Path $FallbackDriverDir (Split-Path -Leaf $LoopMidiZip))

    $CscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if (-not (Test-Path $CscPath)) {
        throw ".NET Framework C# compiler not found at $CscPath"
    }

    $UninstallStubCs = Join-Path $AppDir "installer\UninstallStub.cs"
    $UninstallExe = Join-Path $AppBundleDir "Uninstall.exe"
    Write-Host "Compiling lightweight uninstaller: Uninstall.exe..."
    & $CscPath /nologo /target:winexe /optimize+ `
        /out:"$UninstallExe" `
        /r:System.dll `
        /r:System.Drawing.dll `
        /r:System.Windows.Forms.dll `
        "$UninstallStubCs"
    if ($LASTEXITCODE -ne 0) {
        throw "Uninstaller compilation failed with exit code $LASTEXITCODE"
    }

    $PayloadZip = Join-Path $AppDir "build\payload.zip"
    if (Test-Path $PayloadZip) {
        Remove-Item -Force $PayloadZip
    }

    Write-Host "Compressing application payload for installer..."
    python -c "
import pathlib, zipfile
src = pathlib.Path(r'$AppBundleDir')
dst = pathlib.Path(r'$PayloadZip')
dst.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(dst, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for p in src.rglob('*'):
        if p.is_file():
            zf.write(p, p.relative_to(src).as_posix())
"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create payload.zip"
    }

    $SetupStubCs = Join-Path $AppDir "installer\SetupStub.cs"
    $InstallerExe = Join-Path $DistRoot "MusicHandsSetup.exe"

    Write-Host "Compiling standalone Windows installer: MusicHandsSetup.exe..."
    & $CscPath /nologo /target:winexe /optimize+ `
        /out:"$InstallerExe" `
        /r:System.dll `
        /r:System.Core.dll `
        /r:System.Drawing.dll `
        /r:System.Windows.Forms.dll `
        /r:System.IO.Compression.dll `
        /r:System.IO.Compression.FileSystem.dll `
        /resource:"$PayloadZip,payload.zip" `
        /resource:"$LoopMidiZip,loopMIDISetup.zip" `
        "$SetupStubCs"

    if ($LASTEXITCODE -ne 0) {
        throw "Installer compilation failed with exit code $LASTEXITCODE"
    }

    Write-Host "Cleaning intermediate build files..."
    Remove-Item -Force $PayloadZip -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $AppDir "build") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $AppBundleDir -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $AppDir "MusicHands.spec") -ErrorAction SilentlyContinue

    $InstallerSizeMb = [math]::Round((Get-Item $InstallerExe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Build complete!"
    Write-Host "  Installer EXE : $InstallerExe ($InstallerSizeMb MB)"
} finally {
    Pop-Location
}
