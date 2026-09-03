# init_mobile.ps1 — Assemble the Rifo React Native + Kotlin overlay app.
#
# Rifo's mobile source is staged under <repo>/mobile/ (JS/TS shell + the Kotlin
# native overlay under mobile/android-native/). This script turns that into a
# real, buildable RN project by:
#   1. scaffolding a stock RN project into <repo>/app  (PRD: app lives at /app)
#   2. copying the staged JS/TS shell over the template root
#   3. copying the Kotlin overlay into app/android/app/src/main/java/com/rifo/overlay/
#   4. patching AndroidManifest.xml, MainApplication.kt and gradle.properties
#   5. installing the extra JS dependencies
#
# Requires: Node + npm (RN CLI is fetched on demand). Building further requires
# the Android SDK/JDK — run `npm run android` afterwards.
#
# Usage (PowerShell, from the repo root):
#   .\scripts\init_mobile.ps1
# Re-run is idempotent-ish: pass -SkipInit -SkipNpmInstall to re-apply just the
# staged code + patches onto an existing app/ tree.

param(
    [string]$ProjectName = "Rifo",
    [string]$PackageName = "com.rifo",
    [switch]$SkipInit,
    [switch]$SkipNpmInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Staging   = Join-Path $RepoRoot "mobile"
$AppDir    = Join-Path $RepoRoot "app"

function Test-Cmd([string]$name) {
    try { Get-Command $name -ErrorAction Stop | Out-Null; return $true } catch { return $false }
}

if (-not (Test-Cmd node)) { Write-Error "Node.js is required (https://nodejs.org). Aborting." }
if (-not (Test-Cmd npm))  { Write-Error "npm was not found next to node. Aborting." }

# ---- 1. scaffold ---------------------------------------------------------------
if (-not $SkipInit) {
    if (Test-Path $AppDir) {
        Write-Host "app/ already exists at $AppDir — pass -SkipInit to reuse it." -ForegroundColor Yellow
    } else {
        Write-Host "Scaffolding React Native project '$ProjectName' into app/ (package $PackageName)..."
        # --install-pods false keeps this Windows/Android-first flow from probing CocoaPods.
        npx "@react-native-community/cli@latest" init $ProjectName `
            --directory $AppDir `
            --package $PackageName `
            --pm npm `
            --install-pods false
        if ($LASTEXITCODE -ne 0) { Write-Error "React Native init failed (exit $LASTEXITCODE)." }
    }
}

if (-not (Test-Path (Join-Path $AppDir "package.json"))) {
    Write-Error "No app/ project found. Re-run without -SkipInit (or run the RN init manually)."
}

# ---- 2. staged JS/TS shell over the template root --------------------------------
Write-Host "Copying staged JS/TS shell into app/ ..."
Copy-Item -Force (Join-Path $Staging "App.tsx") (Join-Path $AppDir "App.tsx")
if (Test-Path (Join-Path $Staging "src")) {
    Copy-Item -Recurse -Force (Join-Path $Staging "src") (Join-Path $AppDir "src")
}

# ---- 3. Kotlin overlay into the RN android tree -----------------------------------
$ktSrc = Join-Path $Staging "android-native"
$ktDst = Join-Path $AppDir "android\app\src\main\java\com\rifo\overlay"
Write-Host "Copying Kotlin overlay to $ktDst ..."
New-Item -ItemType Directory -Force -Path $ktDst | Out-Null
Get-ChildItem $ktSrc -Filter "*.kt" | ForEach-Object {
    Copy-Item -Force $_.FullName (Join-Path $ktDst $_.Name)
}
# PATCHES.md is documentation only — keep it with the source, not the build.

# ---- 4. patch manifest / MainApplication / gradle.properties -----------------------
function Insert-After([string]$content, [string]$anchor, [string]$insert) {
    $idx = $content.IndexOf($anchor)
    if ($idx -lt 0) { return $null }
    return $content.Substring(0, $idx + $anchor.Length) + $insert + $content.Substring($idx + $anchor.Length)
}

function Insert-BeforeLast([string]$content, [string]$anchor, [string]$insert) {
    $idx = $content.LastIndexOf($anchor)
    if ($idx -lt 0) { return $null }
    return $content.Substring(0, $idx) + $insert + $content.Substring($idx)
}

$manifestPath = Join-Path $AppDir "android\app\src\main\AndroidManifest.xml"
if (Test-Path $manifestPath) {
    $m = Get-Content $manifestPath -Raw -Encoding utf8

    $permissions = @"
    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
"@
    $anchor = '<uses-permission android:name="android.permission.INTERNET" />'
    $newManifest = $null
    if ($m.Contains($anchor)) {
        $newManifest = Insert-After $m $anchor ("`r`n" + $permissions)
    } else {
        $newManifest = Insert-BeforeLast $m "<application" ($permissions + "`r`n    ")
    }
    $svc = @"
    <service
        android:name="com.rifo.overlay.OverlayService"
        android:exported="false"
        android:foregroundServiceType="mediaProjection" />
"@
    $newManifest = Insert-BeforeLast $newManifest "</application>" ($svc + "`r`n    ")
    if ($null -eq $newManifest) { Write-Error "Could not patch AndroidManifest.xml (unexpected shape)." }
    Set-Content -Path $manifestPath -Value $newManifest -Encoding utf8
    Write-Host "Patched AndroidManifest.xml"
} else {
    Write-Host "AndroidManifest.xml not found; skipping manifest patch." -ForegroundColor Yellow
}

$mainApp = Get-ChildItem (Join-Path $AppDir "android\app\src\main\java") -Recurse -Filter "MainApplication.kt" | Select-Object -First 1
if ($mainApp) {
    $k = Get-Content $mainApp.FullName -Raw -Encoding utf8
    $k = Insert-After $k "package $PackageName" "`r`n`r`nimport com.rifo.overlay.OverlayPackage"
    $k = Insert-After $k "packages.apply {" "`r`n            add(OverlayPackage())"
    if ($null -eq $k) { Write-Error "Could not patch MainApplication.kt (unexpected shape)." }
    Set-Content -Path $mainApp.FullName -Value $k -Encoding utf8
    Write-Host "Patched $($mainApp.FullName)"
} else {
    Write-Host "MainApplication.kt not found; skipping package registration." -ForegroundColor Yellow
}

$gradleProps = Join-Path $AppDir "android\gradle.properties"
if (Test-Path $gradleProps) {
    $g = Get-Content $gradleProps -Raw -Encoding utf8
    if ($g.Contains("newArchEnabled=")) {
        $g = [System.Text.RegularExpressions.Regex]::Replace($g, "(?m)^newArchEnabled=.*$", "newArchEnabled=false")
    } else {
        $g = $g.TrimEnd() + "`r`nnewArchEnabled=false`r`n"
    }
    Set-Content -Path $gradleProps -Value $g -Encoding utf8
    Write-Host "Set newArchEnabled=false (classic module bridge)"
} else {
    Write-Host "android/gradle.properties not found; skipping architecture flag." -ForegroundColor Yellow
}

# ---- 5. JS dependencies -------------------------------------------------------------
if (-not $SkipNpmInstall) {
    Push-Location $AppDir
    try {
        Write-Host "Installing Rifo JS dependencies ..."
        npm install @react-native-async-storage/async-storage `
            @react-navigation/native `
            @react-navigation/native-stack `
            react-native-screens `
            react-native-safe-area-context
        if ($LASTEXITCODE -ne 0) { Write-Error "npm install failed (exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }
}

# ---- done ----------------------------------------------------------------------------
Write-Host ""
Write-Host "Mobile app assembled at: $AppDir" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start the backend (see scripts/dev_verify.py / README)."
Write-Host "  2. If using a physical phone, set DEV_HOST to your machine's LAN IP in app/src/config.ts."
Write-Host "  3. cd app"
Write-Host "  4. npm start            (Metro, in one terminal)"
Write-Host "  5. npm run android      (builds + installs on a connected emulator/device)"
Write-Host ""
Write-Host "Notes:"
Write-Host "  - The Kotlin overlay requires newArchEnabled=false (already set)."
Write-Host "  - Screen capture + overlay debugging must happen on a device/emulator;"
Write-Host "    the projection needs fresh consent after the process is killed."
