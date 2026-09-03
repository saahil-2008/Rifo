# Rifo native overlay — wiring into a stock React Native Android project

The five Kotlin files in this directory live here in the source repo and are copied
into the generated RN project by `scripts/init_mobile.ps1`:

```
app/android/app/src/main/java/com/rifo/overlay/OverlayModule.kt
app/android/app/src/main/java/com/rifo/overlay/OverlayPackage.kt
app/android/app/src/main/java/com/rifo/overlay/OverlayService.kt
app/android/app/src/main/java/com/rifo/overlay/OverlayBubble.kt
app/android/app/src/main/java/com/rifo/overlay/ImagePreparer.kt
```

The JS side (`mobile/src/overlay.ts`) already calls `NativeModules.RifoOverlay`
and subscribes to `RifoCaptureReady` / `RifoBubbleTapped` / `RifoError` /
`RifoServiceStopped`. If you add the module by hand instead of running the
bootstrap script, apply the three edits below.

---

## 1. AndroidManifest.xml — `app/android/app/src/main/AndroidManifest.xml`

Add these `<uses-permission>` elements (before `<application>`, e.g. next to the
existing `INTERNET` one):

```xml
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

Declare the foreground service inside `<application>`, before `</application>`:

```xml
<service
    android:name="com.rifo.overlay.OverlayService"
    android:exported="false"
    android:foregroundServiceType="mediaProjection" />
```

Notes:
- `FOREGROUND_SERVICE_MEDIA_PROJECTION` is mandatory when targeting Android 14
  (API 34) — this is a **screen capture** foreground service.
- `POST_NOTIFICATIONS` must be guarded at runtime on API 33+ (see the JS
  Onboarding screen — it requests it only when `Build.VERSION.SDK_INT >= 33`).
- No `ACCESSIBILITY_SERVICE` — Rifo never uses an accessibility service
  (PRD §11).
- The overlay window is `TYPE_APPLICATION_OVERLAY`, which only needs
  `SYSTEM_ALERT_WINDOW` (granted at onboarding, re-checked by the module).

## 2. MainApplication.kt — `app/android/app/src/main/java/com/rifo/MainApplication.kt`

Add the import with the other `com.facebook.*` imports:

```kotlin
import com.rifo.overlay.OverlayPackage
```

Register the package in `getPackages()` (the template's generated method adds
autolinked packages; append ours so it is always present):

```kotlin
override fun getPackages(): List<ReactPackage> =
    PackageList(this).packages.apply {
        // Packages that cannot be autolinked yet can be added manually here.
        add(OverlayPackage())
    }
```

The manifest `android:name` above uses the fully-qualified
`com.rifo.overlay.OverlayService`, so nothing else is needed even though the
service class is outside the `com.rifo` application package.

## 3. gradle.properties — `app/android/gradle.properties`

The module is a **classic** (pre-TurboModule) `ReactPackage`. To keep the bridge
simple and avoid the New Architecture's interop layer, run the app with the
legacy architecture:

```properties
newArchEnabled=false
```

(A stock RN 0.75/0.76 init sets `newArchEnabled=true`. Setting it to `false` is
fine for this demo build. With New Architecture enabled the module would need a
TurboModule spec + codegen instead.)

## 4. No gradle dependency changes

The overlay is written against `android.*` APIs only — no androidx, no third-party
libs — so no additions to `build.gradle` or `settings.gradle` are required.

## 5. Runtime reminders

- **Re-consent is expected.** A `MediaProjection` grant is single-use and does
  not survive process death. If the service is killed, the app emits
  `RifoServiceStopped` and the next bubble start re-prompts the system consent
  dialog (FR-2). This is correct Android behaviour, not a bug.
- **Overlay debugging** (PRD §12 warning): the capture session ends when the
  system tears the projection down. Debug the overlay on a real device, and be
  aware the bubble itself is part of the captured frame (small, top area).
- **Target/compile SDK**: build against `compileSdk 34` (RN 0.75 default) so the
  `foregroundServiceType` and typed `getParcelableExtra` calls resolve.
