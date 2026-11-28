# BattDock 一键可重复构建与 Release 打包脚本（使用全新构建与产物目录，不含递归删除，保留已有正式资产）
param(
    [string]$PythonExe = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

if ([string]::IsNullOrWhiteSpace($PythonExe) -or !(Test-Path $PythonExe)) {
    $DefaultPy = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $DefaultPy) {
        $PythonExe = $DefaultPy
    } else {
        $PythonExe = "python"
    }
}

$AppVersion = (& $PythonExe -c "import sys; sys.path.insert(0, r'$Root'); import brand; print(brand.APP_VERSION)").Trim()
$BaseOut = if ([string]::IsNullOrWhiteSpace($OutputRoot)) { Join-Path $Root "release" } else { $OutputRoot }
$BuildRunDir = Join-Path $BaseOut "build_run_v${AppVersion}_$Stamp"
$DistTmp = Join-Path $BuildRunDir "dist"
$WorkTmp = Join-Path $BuildRunDir "work"
$ReleaseDir = Join-Path $BaseOut "BattDock_v${AppVersion}_$Stamp"
$ReleaseAssetsDir = Join-Path $BaseOut "assets_v$AppVersion"
if (Test-Path $ReleaseAssetsDir) {
    $ReleaseAssetsDir = Join-Path $BaseOut "assets_v${AppVersion}_$Stamp"
}

Write-Host "=== 构建 BattDock v$AppVersion（全新隔离目录，保留已有正式资产） ==="

Write-Host "[1/6] 运行全部自动化单元测试..."
& $PythonExe -m unittest discover -s (Join-Path $Root "tests") -v
if ($LASTEXITCODE -ne 0) { throw "单元测试未通过，已中止打包。" }

New-Item -ItemType Directory -Force -Path $WorkTmp, $DistTmp, $ReleaseAssetsDir | Out-Null

Write-Host "[2/6] 使用 PyInstaller 构建 BattDock.exe（含品牌图标与 Windows 版本属性）..."
& $PythonExe -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name BattDock `
    --icon (Join-Path $Root "assets\app_icon.ico") `
    --version-file (Join-Path $Root "version_info.txt") `
    --add-data ((Join-Path $Root "ui") + ";ui") `
    --add-data ((Join-Path $Root "assets") + ";assets") `
    --add-data ((Join-Path $Root "SUPPORTED_DEVICES.md") + ";.") `
    --add-data ((Join-Path $Root "THIRD_PARTY_LICENSES.md") + ";.") `
    --add-data ((Join-Path $Root "CHANGELOG.md") + ";.") `
    --hidden-import brand `
    --hidden-import device_icons `
    --hidden-import tray_icon `
    --hidden-import tray_hover_popup `
    --hidden-import updater `
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

if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建 BattDock 失败。" }

Write-Host "[3/6] 构建旧版 v2.2.0 升级迁移桥接器（VGNMouseBattery.exe）..."
$BridgeDist = Join-Path $WorkTmp "bridge_dist"
$BridgeWork = Join-Path $WorkTmp "bridge_work"
& $PythonExe -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name VGNMouseBattery `
    --icon (Join-Path $Root "assets\app_icon.ico") `
    --version-file (Join-Path $Root "version_info.txt") `
    --distpath $BridgeDist `
    --workpath $BridgeWork `
    --specpath $BridgeWork `
    (Join-Path $Root "legacy_shim.py")

if ($LASTEXITCODE -ne 0) { throw "构建旧版迁移桥接器失败。" }

Write-Host "[4/6] 生成卸载脚本与快捷方式脚本..."
$BuiltAppDir = Join-Path $DistTmp "BattDock"

$UninstallBat = @"
@echo off
chcp 65001 >nul
title 卸载 BattDock
echo 正在停止 BattDock 运行进程...
taskkill /F /IM BattDock.exe >nul 2>&1
taskkill /F /IM VGNMouseBattery.exe >nul 2>&1
echo 正在清理开机自启项...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "BattDock" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "VGNMouseBattery" /f >nul 2>&1
echo 正在清理桌面与开始菜单快捷方式...
del /F /Q "%USERPROFILE%\Desktop\BattDock.lnk" >nul 2>&1
del /F /Q "%USERPROFILE%\Desktop\VGNMouseBattery.lnk" >nul 2>&1
del /F /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\BattDock.lnk" >nul 2>&1
del /F /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\VGNMouseBattery.lnk" >nul 2>&1
echo.
set /p DELCFG=是否同时删除个人配置文件（%LOCALAPPDATA%\BattDock）？[y/N]: 
if /I "%DELCFG%"=="y" (
    rmdir /S /Q "%LOCALAPPDATA%\BattDock" >nul 2>&1
    echo 已删除个人配置文件。
)
echo.
echo BattDock 自启项与快捷方式已清理完毕，您现在可以直接删除本程序文件夹。
pause
"@
Set-Content -Path (Join-Path $BuiltAppDir "卸载BattDock.bat") -Value $UninstallBat -Encoding UTF8

$ShortcutBat = @"
@echo off
chcp 65001 >nul
title 创建 BattDock 快捷方式
powershell -NoProfile -ExecutionPolicy Bypass -Command "`$ws = New-Object -ComObject WScript.Shell; `$exe = Join-Path '%~dp0' 'BattDock.exe'; `$ico = Join-Path '%~dp0' '_internal\assets\app_icon.ico'; foreach (`$dst in @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'BattDock.lnk'), (Join-Path ([Environment]::GetFolderPath('Programs')) 'BattDock.lnk'))) { `$s = `$ws.CreateShortcut(`$dst); `$s.TargetPath = `$exe; `$s.WorkingDirectory = '%~dp0'; if (Test-Path `$ico) { `$s.IconLocation = `$ico }; `$s.Description = 'BattDock - 轻量化 Windows 无线外设电量管理工具'; `$s.Save() }"
echo 已在桌面与开始菜单创建 BattDock 快捷方式！
pause
"@
Set-Content -Path (Join-Path $BuiltAppDir "创建桌面与开始菜单快捷方式.bat") -Value $ShortcutBat -Encoding UTF8

Write-Host "[5/6] 部署到全新运行目录 $ReleaseDir 并打包正式发布产物..."
Move-Item -Force $BuiltAppDir $ReleaseDir

$PortableZip = Join-Path $ReleaseAssetsDir "BattDock-v$AppVersion-Windows-x64-Portable.zip"
$BridgeZip = Join-Path $ReleaseAssetsDir "VGNMouseBattery-v$AppVersion-win64-UpgradeBridge.zip"
$SetupExe = Join-Path $ReleaseAssetsDir "BattDock-v$AppVersion-Setup.exe"
$BridgeExe = Join-Path $BridgeDist "VGNMouseBattery.exe"

# 若本机安装了 Inno Setup 6，则同步编译标准 Windows 安装程序（Setup.exe）
$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$IsccExe = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$IssPath = Join-Path $Root "installer\BattDock.iss"
if ($IsccExe -and (Test-Path $IssPath)) {
    Write-Host "[5.5/6] 使用 Inno Setup 编译标准安装程序（BattDock-v$AppVersion-Setup.exe）..."
    & $IsccExe "/DMyAppVersion=$AppVersion" "/DMySourceDir=$ReleaseDir" "/DMyOutputDir=$ReleaseAssetsDir" $IssPath
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译安装程序失败。" }
} else {
    Write-Host "[5.5/6] 未检测到 Inno Setup 6，跳过 Setup.exe 编译（仅生成便携 ZIP）。"
}

& $PythonExe -c "
import hashlib, zipfile
from pathlib import Path
rel = Path(r'$ReleaseDir')
pzip = Path(r'$PortableZip')
bzip = Path(r'$BridgeZip')
bexe = Path(r'$BridgeExe')
setup_exe = Path(r'$SetupExe')

with zipfile.ZipFile(pzip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for f in sorted(rel.rglob('*')):
        if f.is_file():
            zf.write(f, 'BattDock/' + f.relative_to(rel).as_posix())

with zipfile.ZipFile(bzip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for f in sorted(rel.rglob('*')):
        if f.is_file():
            zf.write(f, 'BattDock/' + f.relative_to(rel).as_posix())
    zf.write(bexe, 'BattDock/VGNMouseBattery.exe')

targets = [pzip, bzip]
if setup_exe.is_file():
    targets.insert(0, setup_exe)

sums = []
for fp in targets:
    h = hashlib.sha256(fp.read_bytes()).hexdigest()
    sums.append(f'{h}  {fp.name}')
(pzip.parent / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
print('ASSETS_OK:', ' | '.join(f'{fp.name} ({round(fp.stat().st_size/1048576, 2)} MB)' for fp in targets))
"
if ($LASTEXITCODE -ne 0) { throw "打包发布产物 ZIP 失败。" }

Write-Host "[6/6] 构建完成（零递归删除，保留中间构建目录与历史正式资产）..."
Write-Host "运行目录：$ReleaseDir\BattDock.exe"
Write-Host "发布产物目录：$ReleaseAssetsDir"
Write-Host "构建中间目录：$BuildRunDir"
