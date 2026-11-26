# 一键可重复构建 Windows 独立发布包脚本（供本地发布与后续 GitHub Releases 使用）
param(
    [string]$PythonExe = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistTmp = Join-Path $Root "build_dist"
$WorkTmp = Join-Path $Root "build_tmp"
$ReleaseDir = Join-Path $Root "release\VGNMouseBattery"
$UninstallSrc = Join-Path $ReleaseDir "卸载程序.bat"
$UninstallBackup = Join-Path $WorkTmp "卸载程序.bat.bak"

if (!(Test-Path $PythonExe)) {
    $PythonExe = "python"
}

Write-Host "[1/4] 运行全部自动化单元测试..."
& $PythonExe -m unittest discover -s (Join-Path $Root "tests") -v
if ($LASTEXITCODE -ne 0) { throw "单元测试未通过，已中止打包。" }

New-Item -ItemType Directory -Force -Path $WorkTmp | Out-Null
if (Test-Path $UninstallSrc) {
    Copy-Item -Force $UninstallSrc $UninstallBackup
}

Write-Host "[2/4] 使用 PyInstaller 构建独立目录版..."
& $PythonExe -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name VGNMouseBattery `
    --icon (Join-Path $Root "assets\app_icon.ico") `
    --add-data ((Join-Path $Root "ui") + ";ui") `
    --add-data ((Join-Path $Root "assets") + ";assets") `
    --add-data ((Join-Path $Root "SUPPORTED_DEVICES.md") + ";.") `
    --add-data ((Join-Path $Root "THIRD_PARTY_LICENSES.md") + ";.") `
    --add-data ((Join-Path $Root "CHANGELOG.md") + ";.") `
    --hidden-import pystray._win32 `
    --hidden-import floating_widget `
    --hidden-import providers `
    --collect-submodules providers `
    --collect-all webview `
    --collect-all clr_loader `
    --collect-all pythonnet `
    --distpath $DistTmp `
    --workpath $WorkTmp `
    --specpath $WorkTmp `
    (Join-Path $Root "mouse_battery_app.py")

if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }

Write-Host "[3/4] 停止已有进程并部署到 release\VGNMouseBattery（保留卸载脚本）..."
Get-Process -Name "VGNMouseBattery" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600
if (Test-Path $UninstallBackup) {
    Copy-Item -Force $UninstallBackup (Join-Path $DistTmp "VGNMouseBattery\卸载程序.bat")
}
if (Test-Path $ReleaseDir) {
    Remove-Item -Recurse -Force $ReleaseDir
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReleaseDir) | Out-Null
Move-Item -Force (Join-Path $DistTmp "VGNMouseBattery") $ReleaseDir

Write-Host "[4/4] 清理构建临时目录..."
Remove-Item -Recurse -Force $DistTmp, $WorkTmp

Write-Host "构建完成：$ReleaseDir\VGNMouseBattery.exe"
