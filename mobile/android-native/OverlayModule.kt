package com.rifo.overlay

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.provider.Settings
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap
import com.facebook.react.modules.core.DeviceEventManagerModule

/**
 * Native bridge for the Rifo overlay. Exposed to JS as `NativeModules.RifoOverlay`
 * (see mobile/src/overlay.ts). All of the projection / capture / bubble / image
 * work lives in [OverlayService]; this module only brokers permission prompts,
 * service lifecycle calls and forwards events to JS.
 *
 * React Native <-> native events (DeviceEventEmitter -> JS):
 *   'RifoCaptureReady'  { jpegBase64, width, height }   a long-press completed
 *   'RifoBubbleTapped'  {}                              a verdict bubble was tapped
 *   'RifoError'         { code, message }               flag_secure | capture | ...
 *   'RifoServiceStopped'{}                              projection died -> re-consent
 *
 * The module is a *classic* ReactContextBaseJavaModule (PRD constraint #1: no
 * RN-rendered overlay; this code only). Requires newArchEnabled=false on the
 * host app (see PATCHES.md).
 */
class OverlayModule(reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext), ActivityEventListener {

    init {
        reactContext.addActivityEventListener(this)
        RifoEventBus.attach(reactContext)
    }

    private var pendingOverlayPromise: Promise? = null
    private var pendingCapturePromise: Promise? = null

    override fun getName(): String = "RifoOverlay"

    // ---- JS-callable methods ------------------------------------------------

    /** SYSTEM_ALERT_WINDOW. Prompts via the system intent when not yet granted. */
    @ReactMethod
    fun requestOverlayPermission(promise: Promise) {
        val ctx = reactApplicationContext
        if (Settings.System.canDrawOverlays(ctx)) {
            promise.resolve(true)
            return
        }
        val activity = currentActivity
        if (activity == null) {
            promise.resolve(false) // no resumed activity to host the intent
            return
        }
        if (pendingOverlayPromise != null) {
            promise.resolve(false) // one prompt at a time
            return
        }
        pendingOverlayPromise = promise
        try {
            activity.startActivityForResult(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:${ctx.packageName}")
                ),
                REQ_OVERLAY
            )
        } catch (e: Exception) {
            pendingOverlayPromise = null
            promise.resolve(false)
        }
    }

    /**
     * MediaProjection consent. On RESULT_OK the consent token is handed to
     * OverlayService which starts a foreground service and shows the bubble.
     * Overlay permission must already be granted (onboarding order, FR-9).
     */
    @ReactMethod
    fun requestScreenCapture(promise: Promise) {
        if (!Settings.System.canDrawOverlays(reactApplicationContext)) {
            // The bubble cannot render without SYSTEM_ALERT_WINDOW; resolve false
            // rather than granting a useless projection.
            promise.resolve(false)
            return
        }
        promptScreenCapture(promise)
    }

    /**
     * (Re)start the bubble. A MediaProjection grant does NOT survive a service
     * stop or process death (FR-2 re-consent), so unless the service is already
     * running we ask the user to re-grant. Mirrors requestScreenCapture.
     */
    @ReactMethod
    fun startOverlay(promise: Promise) {
        if (OverlayService.isRunning()) {
            promise.resolve(true)
            return
        }
        if (!Settings.System.canDrawOverlays(reactApplicationContext)) {
            promise.resolve(false)
            return
        }
        promptScreenCapture(promise)
    }

    /** Stop the foreground service and remove the bubble. */
    @ReactMethod
    fun stopOverlay(promise: Promise) {
        OverlayService.stop(reactApplicationContext)
        promise.resolve(null)
    }

    @ReactMethod
    fun isOverlayActive(promise: Promise) {
        promise.resolve(OverlayService.isRunning())
    }

    /**
     * Update the bubble's visual state. `state` in idle|working|verdict|error.
     * `payload` is a JSON string: for verdict {label,confidence,claim_id},
     * for error {code,message}. The bubble renders without the JS thread.
     */
    @ReactMethod
    fun setBubbleState(state: String, payload: String?) {
        OverlayService.setBubbleState(state, payload)
    }

    /** Hide the bubble (service keeps running and holding the projection). */
    @ReactMethod
    fun dismissBubble() {
        OverlayService.hideBubble(reactApplicationContext)
    }

    // NativeEventEmitter in JS calls into these when it subscribes. Events are
    // actually delivered through RCTDeviceEventEmitter (see RifoEventBus), so
    // these are no-ops that keep the classic bridge's emitter happy.
    @ReactMethod
    fun addListener(eventName: String) = Unit

    @ReactMethod
    fun removeListeners(count: Int) = Unit

    // ---- Activity results ----------------------------------------------------

    override fun onActivityResult(activity: Activity?, requestCode: Int, resultCode: Int, data: Intent?) {
        when (requestCode) {
            REQ_OVERLAY -> {
                // The settings screen may return RESULT_CANCELED even after the
                // user flipped the toggle; always re-check the actual permission.
                pendingOverlayPromise?.resolve(
                    Settings.System.canDrawOverlays(reactApplicationContext)
                )
                pendingOverlayPromise = null
            }
            REQ_CAPTURE -> {
                val pending = pendingCapturePromise ?: return
                pendingCapturePromise = null
                if (resultCode == Activity.RESULT_OK && data != null) {
                    try {
                        OverlayService.start(reactApplicationContext, resultCode, data)
                        pending.resolve(true)
                    } catch (e: Exception) {
                        pending.resolve(false)
                    }
                } else {
                    pending.resolve(false) // user declined the consent dialog
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent?) {
        // No-op; required by ActivityEventListener.
    }

    // ---- internal ------------------------------------------------------------

    private fun promptScreenCapture(promise: Promise) {
        val activity = currentActivity
        if (activity == null) {
            promise.resolve(false)
            return
        }
        if (pendingCapturePromise != null) {
            promise.resolve(false) // one consent prompt at a time
            return
        }
        pendingCapturePromise = promise
        try {
            val mpm = activity.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            activity.startActivityForResult(mpm.createScreenCaptureIntent(), REQ_CAPTURE)
        } catch (e: Exception) {
            pendingCapturePromise = null
            promise.resolve(false)
        }
    }

    companion object {
        private const val REQ_OVERLAY = 0x5101
        private const val REQ_CAPTURE = 0x5102
    }
}

/**
 * Tiny event bus: OverlayService (a plain android Service) reaches the React
 * runtime through the context this module attached in its init.
 */
internal object RifoEventBus {
    private var context: ReactApplicationContext? = null

    fun attach(ctx: ReactApplicationContext) {
        context = ctx
    }

    /** Emit a named event to JS. Safe to call from any thread. */
    fun emit(name: String, payload: WritableMap) {
        val ctx = context ?: return
        try {
            ctx.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
                .emit(name, payload)
        } catch (_: Exception) {
            // Module invalidated mid-emit; drop the event.
        }
    }

    fun emitSimple(name: String) {
        emit(name, Arguments.createMap())
    }
}
