param(
    [string]$AdbPath = $env:ARKNIGHTS_ADB,
    [string]$Device = $env:ARKNIGHTS_DEVICE,
    [string]$GamePackage = $env:ARKNIGHTS_GAME_PACKAGE,
    [string]$MaaPath = $env:ARKNIGHTS_MAA_PATH,
    [string]$MuMuRoot = $env:ARKNIGHTS_MUMU_ROOT,
    [string]$PythonPath = $env:ARKNIGHTS_PYTHON,
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
$results = [System.Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [string]$Status, [string]$Value, [string]$Detail = "") {
    $results.Add([pscustomobject]@{
        check = $Name
        status = $Status
        value = $Value
        detail = $Detail
    })
}

function First-Existing([string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

$cv = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
$build = [int]$cv.CurrentBuildNumber
$windowsName = if ($build -ge 22000) { "Windows 11" } else { "Windows 10" }
$architecture = if ([Environment]::Is64BitOperatingSystem) { "64-bit" } else { "32-bit" }
Add-Check "windows" "PASS" "$windowsName build $build" $architecture

$MuMuRoot = First-Existing @(
    $MuMuRoot,
    "$env:ProgramFiles\Netease\MuMuPlayer-12.0",
    "$env:ProgramFiles\Netease\MuMu Player",
    "$env:ProgramFiles\Netease\MuMuPlayerGlobal-12.0"
)
if ($MuMuRoot) {
    Add-Check "mumu_root" "PASS" $MuMuRoot
} else {
    Add-Check "mumu_root" "FAIL" "not found" "Pass -MuMuRoot or ARKNIGHTS_MUMU_ROOT."
}

$AdbPath = First-Existing @(
    $AdbPath,
    $(if ($MuMuRoot) { Join-Path $MuMuRoot "shell\adb.exe" } else { "" }),
    $(if ($MuMuRoot) { Join-Path $MuMuRoot "adb.exe" } else { "" })
)
if (-not $AdbPath) {
    Add-Check "adb" "FAIL" "not found" "Pass -AdbPath or ARKNIGHTS_ADB."
} else {
    Add-Check "adb" "PASS" $AdbPath
}

$activeDevices = @()
if ($AdbPath) {
    $activeDevices = @(& $AdbPath devices | Select-String "\sdevice$" | ForEach-Object {
        ($_.Line -split "\s+")[0]
    })
    if (-not $Device -and $activeDevices.Count -eq 1) {
        $Device = $activeDevices[0]
    }
    if ($Device -and $activeDevices -contains $Device) {
        Add-Check "adb_device" "PASS" $Device
    } elseif ($activeDevices.Count -eq 0) {
        Add-Check "adb_device" "FAIL" "none" "Start exactly one target emulator or pass its connected device."
    } elseif (-not $Device) {
        Add-Check "adb_device" "FAIL" ($activeDevices -join ", ") "Multiple devices; pass -Device explicitly."
    } else {
        Add-Check "adb_device" "FAIL" $Device "Requested device is not in adb devices."
    }
}

$screenshotSize = "unknown"
if ($AdbPath -and $Device -and $activeDevices -contains $Device) {
    $wmSize = (& $AdbPath -s $Device shell wm size 2>&1) -join " "
    $wmDensity = (& $AdbPath -s $Device shell wm density 2>&1) -join " "
    Add-Check "android_wm_size" "INFO" $wmSize
    Add-Check "android_density" "INFO" $wmDensity "Recorded for diagnosis; screenshot dimensions are the hard gate."

    $tempPng = Join-Path ([IO.Path]::GetTempPath()) ("arknights-preflight-" + [guid]::NewGuid().ToString("N") + ".png")
    try {
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $AdbPath
        $startInfo.Arguments = "-s `"$Device`" exec-out screencap -p"
        $startInfo.UseShellExecute = $false
        $startInfo.RedirectStandardOutput = $true
        $process = [Diagnostics.Process]::Start($startInfo)
        $file = [IO.File]::OpenWrite($tempPng)
        try { $process.StandardOutput.BaseStream.CopyTo($file) } finally { $file.Dispose() }
        $process.WaitForExit(10000) | Out-Null
        Add-Type -AssemblyName System.Drawing
        $image = [Drawing.Image]::FromFile($tempPng)
        try { $screenshotSize = "$($image.Width)x$($image.Height)" } finally { $image.Dispose() }
        if ($screenshotSize -eq "1920x1080") {
            Add-Check "screenshot_resolution" "PASS" $screenshotSize
        } else {
            Add-Check "screenshot_resolution" "FAIL" $screenshotSize "Required: landscape 1920x1080. Do not scale coordinates."
        }
    } catch {
        Add-Check "screenshot_resolution" "FAIL" "capture failed" $_.Exception.Message
    } finally {
        Remove-Item -LiteralPath $tempPng -Force -ErrorAction SilentlyContinue
    }

    $packages = @(& $AdbPath -s $Device shell pm list packages 2>$null | ForEach-Object { $_.Trim() })
    if (-not $GamePackage) {
        $known = @("com.hypergryph.arknights", "com.hypergryph.arknights.bilibili")
        $installed = @($known | Where-Object { $packages -contains "package:$_" })
        if ($installed.Count -eq 1) { $GamePackage = $installed[0] }
    }
    if ($GamePackage -and $packages -contains "package:$GamePackage") {
        Add-Check "game_package" "PASS" $GamePackage
    } else {
        $packageValue = if ($GamePackage) { $GamePackage } else { "not detected" }
        Add-Check "game_package" "FAIL" $packageValue "Configure the correct server package explicitly."
    }
}

$MaaPath = First-Existing @(
    $MaaPath,
    "$env:LOCALAPPDATA\MAA-App\MAA.exe"
)
if ($MaaPath) {
    $version = (Get-Item -LiteralPath $MaaPath).VersionInfo.ProductVersion
    Add-Check "maa" "PASS" $MaaPath $version
} else {
    Add-Check "maa" "FAIL" "not found" "Pass -MaaPath or ARKNIGHTS_MAA_PATH."
}

$PythonPath = First-Existing @(
    $PythonPath,
    $((Get-Command python.exe -ErrorAction SilentlyContinue).Source)
)
if ($PythonPath) {
    $probe = & $PythonPath -c "import PIL, cv2, rapidocr_onnxruntime, uiautomation; print('OK')" 2>&1
    if ($LASTEXITCODE -eq 0 -and ($probe -join " ") -match "OK") {
        Add-Check "python_runtime" "PASS" $PythonPath "Required imports are available."
    } else {
        Add-Check "python_runtime" "FAIL" $PythonPath (($probe -join " ").Trim())
    }
} else {
    Add-Check "python_runtime" "FAIL" "not found" "Pass -PythonPath or ARKNIGHTS_PYTHON."
}

$dpi = Get-ItemProperty -LiteralPath "HKCU:\Control Panel\Desktop" -ErrorAction SilentlyContinue
$logPixels = if ($dpi.LogPixels) { [int]$dpi.LogPixels } else { 96 }
$scale = [math]::Round(($logPixels / 96.0) * 100)
Add-Check "windows_desktop_scale" "INFO" "$scale%" "ADB control is unaffected; calibrate any desktop-coordinate fallback when not 100%."

$results | Format-Table -AutoSize
$failures = @($results | Where-Object status -eq "FAIL")
$summary = [pscustomobject]@{
    checked_at = (Get-Date).ToString("o")
    ready_for_non_destructive_validation = ($failures.Count -eq 0)
    failures = $failures.Count
    checks = $results
}

if ($OutputJson) {
    $parent = Split-Path -Parent $OutputJson
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputJson -Encoding utf8
}

if ($failures.Count -gt 0) { exit 2 }
exit 0
