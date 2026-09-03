package com.rifo.overlay

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.view.WindowManager
import android.widget.Toast
import com.facebook.react.bridge.Arguments
import java.util.concurrent.Executors

/**
 * Foreground service that owns the screen-capture session and the floating
 * bubble (FR-1/FR-2/FR-3). One MediaProjection + one reusable VirtualDisplay +
 * ImageReader are created per session and reused for every capture (FR-2:
 * "no per-capture recreation").
 *
 * A MediaProjection grant does NOT survive process death and the consent token
 * is single-use on recent Android, so whenever the service is (re)started the
 * JS layer must first obtain fresh consent (OverlayModule -> requestScreenCapture).
 *
 * Bubble gesture contract (implemented in OverlayBubble, driven from here):
 *   ACTION_DOWN   -> begin a capture attempt immediately (FR-2)
 *   600 ms hold   -> haptic + commit (prepare off the main thread + emit)
 *   early lift    -> discard the pending bitmap, emit nothing
 *   drag          -> cancels the pending capture, moves the bubble, snaps to edge
 *   tap (verdict) -> emit 'RifoBubbleTapped' so the app opens the Detail screen
 */
class OverlayService : Service() {

    // ---- projection / capture session ---------------------------------------

    private val mainHandler = Handler(Looper.getMainLooper())
    private val prepareExecutor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "rifo-image-prep").apply { priority = Thread.NORM_PRIORITY }
    }

    private var mediaProjection: MediaProjection? = null
    private var imageReader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var projectionCallback: MediaProjection.Callback? = null

    private var pendingBitmap: Bitmap? = null
    private var preparing = false
    private var cleaning = false

    private var bubble: OverlayBubble? = null
    private var bubbleOnScreen = false
    private var bubbleX = 0
    private var bubbleY = 0
    private var screenW = 0
    private var screenH = 0
    private var bubbleSizePx = 0

    private val wm by lazy { getSystemService(WINDOW_SERVICE) as WindowManager }
    private val density by lazy { resources.displayMetrics.density }

    // ---- service lifecycle ----------------------------------------------------

    override fun onCreate() {
        super.onCreate()
        instance = this
        ensureNotificationChannel()
        val size = (BUBBLE_DP * density).toInt()
        bubbleSizePx = size
        val display = wm.defaultDisplay
        val out = android.graphics.Point()
        display.getRealSize(out) // whole screen incl. system bars
        screenW = out.x
        screenH = out.y
        bubbleX = screenW - size - (BUBBLE_MARGIN_DP * density).toInt()
        bubbleY = (screenH / 3).coerceAtLeast((BUBBLE_MARGIN_DP * density).toInt())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val data: Intent? =
            if (Build.VERSION.SDK_INT >= 33) {
                intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(EXTRA_RESULT_DATA)
            }
        if (resultCode == Activity.RESULT_OK && data != null) {
            startForegroundSession(resultCode, data)
        } else {
            // No fresh consent token: cannot project. Nothing else to do.
            stopSelf()
        }
        return START_NOT_STICKY // never auto-restart — re-consent is required (FR-2)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        cleanup()
        instance = null
        super.onDestroy()
    }

    // ---- session setup ---------------------------------------------------------

    /**
     * Must be foreground before getMediaProjection on Android 14 (targetSdk 34).
     * Called on the main thread from onStartCommand.
     */
    private fun startForegroundSession(resultCode: Int, data: Intent) {
        if (mediaProjection != null) {
            // A session is already live (e.g. a duplicate start). Don't orphan the
            // first projection — just make sure the bubble is on screen.
            showBubble()
            return
        }
        try {
            startForegroundNotification()
        } catch (e: Exception) {
            Log.e(TAG, "startForeground failed", e)
            stopSelf()
            return
        }

        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        try {
            val proj = mpm.getMediaProjection(resultCode, data)
            mediaProjection = proj
            projectionCallback = object : MediaProjection.Callback() {
                override fun onStop() {
                    // The OS tore the projection down (user ended it, another app
                    // took over, or the capture session was invalidated). Unless the
                    // user asked us to stop, tell JS so it can re-request consent.
                    mainHandler.post {
                        if (!cleaning && !userStopped) {
                            RifoEventBus.emitSimple(EVT_SERVICE_STOPPED)
                        }
                        if (!cleaning) {
                            stopForegroundCompat()
                            cleanup()
                            stopSelf()
                        }
                    }
                }
            }
            proj.registerCallback(projectionCallback, mainHandler)
            setupCapturePipeline(proj)
            showBubble()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start media projection", e)
            Toast.makeText(this, "Rifo: could not start screen capture", Toast.LENGTH_SHORT).show()
            stopForegroundCompat()
            stopSelf()
        }
    }

    private fun startForegroundNotification() {
        val contentIntent = PendingIntent.getActivity(
            this, 0,
            packageManager.getLaunchIntentForPackage(packageName),
            PendingIntent.FLAG_IMMUTABLE
        )
        val notification: Notification =
            if (Build.VERSION.SDK_INT >= 26) {
                Notification.Builder(this, CHANNEL_ID)
                    .setContentTitle("Rifo is ready")
                    .setContentText("Long-press the bubble to verify on-screen content.")
                    .setSmallIcon(android.R.drawable.ic_menu_camera) // swap for the app launcher icon for polish
                    .setOngoing(true)
                    .setContentIntent(contentIntent)
                    .build()
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(this)
                    .setContentTitle("Rifo is ready")
                    .setContentText("Long-press the bubble to verify on-screen content.")
                    .setSmallIcon(android.R.drawable.ic_menu_camera)
                    .setOngoing(true)
                    .setContentIntent(contentIntent)
                    .build()
            }
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Rifo overlay", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    /** One VirtualDisplay + ImageReader for the whole session (FR-2). */
    private fun setupCapturePipeline(proj: MediaProjection) {
        val metrics = resources.displayMetrics
        val width = screenW
        val height = screenH
        val dpi = metrics.densityDpi
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        imageReader = reader
        virtualDisplay = proj.createVirtualDisplay(
            "RifoCapture",
            width, height, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface, null, mainHandler
        )
    }

    // ---- bubble window ---------------------------------------------------------

    private fun showBubble() {
        val b = bubble ?: OverlayBubble(this).also {
            it.onDown = { pendingBitmap = beginCapture() }
            it.onDiscard = { releasePending() }
            it.onLongPress = { commitPending() }
            it.onDragged = { dx, dy -> moveBubbleBy(dx.toInt(), dy.toInt()) }
            it.onDragEnd = { snapToEdge() }
            it.onTap = { RifoEventBus.emitSimple(EVT_BUBBLE_TAPPED) }
            bubble = it
        }
        if (!bubbleOnScreen) {
            val params = WindowManager.LayoutParams(
                bubbleSizePx, bubbleSizePx,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT
            ).apply {
                x = bubbleX
                y = bubbleY
            }
            try {
                wm.addView(b, params)
                bubbleOnScreen = true
            } catch (e: Exception) {
                // e.g. overlay permission revoked mid-flight.
                Log.e(TAG, "Could not show overlay bubble", e)
                emitError("overlay", "Cannot display the overlay bubble. Re-grant the overlay permission.")
            }
        }
    }

    private fun moveBubbleBy(dx: Int, dy: Int) {
        val b = bubble ?: return
        val params = b.layoutParams as WindowManager.LayoutParams
        val margin = (BUBBLE_MARGIN_DP * density).toInt()
        val maxX = (screenW - bubbleSizePx - margin).coerceAtLeast(margin)
        val maxY = (screenH - bubbleSizePx - margin).coerceAtLeast(margin)
        params.x = (params.x + dx).coerceIn(margin, maxX)
        params.y = (params.y + dy).coerceIn(margin, maxY)
        bubbleX = params.x
        bubbleY = params.y
        try {
            wm.updateViewLayout(b, params)
        } catch (_: Exception) {
            // Window may have just been removed; ignore.
        }
    }

    private fun snapToEdge() {
        val b = bubble ?: return
        val params = b.layoutParams as WindowManager.LayoutParams
        val margin = (BUBBLE_MARGIN_DP * density).toInt()
        val center = params.x + bubbleSizePx / 2
        val maxX = (screenW - bubbleSizePx - margin).coerceAtLeast(margin)
        params.x = if (center < screenW / 2) margin else maxX
        bubbleX = params.x
        try {
            wm.updateViewLayout(b, params)
        } catch (_: Exception) {
        }
    }

    private fun hideBubbleFromWindow() {
        val b = bubble ?: return
        if (bubbleOnScreen) {
            try {
                wm.removeView(b)
            } catch (_: Exception) {
            }
            bubbleOnScreen = false
        }
    }

    // ---- capture / prepare (FR-2 / FR-3) ----------------------------------------

    /** Grab the latest projected frame synchronously (touch handlers run on main). */
    private fun beginCapture(): Bitmap? {
        val reader = imageReader ?: return null
        return try {
            val image = reader.acquireLatestImage() ?: return null
            val plane = image.planes[0]
            val buffer = plane.buffer
            val width = image.width
            val height = image.height
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * width

            // ARGB_8888 read via copyPixelsFromBuffer from an RGBA_8888 plane is the
            // canonical screenshot recipe; copy into a padded buffer then crop.
            val padded = Bitmap.createBitmap(
                width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888
            )
            padded.copyPixelsFromBuffer(buffer)
            image.close()

            val cropped = if (rowPadding > 0) {
                Bitmap.createBitmap(padded, 0, 0, width, height)
            } else {
                padded
            }
            if (cropped !== padded) padded.recycle()
            cropped
        } catch (e: Exception) {
            Log.w(TAG, "beginCapture failed", e)
            null
        }
    }

    private fun releasePending() {
        pendingBitmap?.recycle()
        pendingBitmap = null
    }

    /**
     * Long-press fired: if the frame is black the screen is FLAG_SECURE and we
     * emit an error instead of uploading anything (PRD constraint: never OCR a
     * secure screen). Otherwise downscale + JPEG off the main thread (FR-3).
     */
    private fun commitPending() {
        if (preparing) return
        val bmp = pendingBitmap ?: run {
            emitError("capture", "Could not capture the screen. Try again.")
            return
        }
        pendingBitmap = null

        if (ImagePreparer.isMostlyBlack(bmp)) {
            bmp.recycle()
            emitError("flag_secure", "This screen can't be captured (secure app).")
            return
        }

        preparing = true
        prepareExecutor.execute {
            try {
                val scaled = ImagePreparer.downscaleToMaxEdge(bmp, MAX_EDGE_PX)
                if (scaled !== bmp) bmp.recycle()
                val jpeg = ImagePreparer.encodeJpegQuality(scaled, JPEG_QUALITY)
                if (jpeg.size > 300 * 1024) {
                    Log.w(TAG, "Prepared JPEG ${jpeg.size / 1024} KB (>300 KB target)")
                }
                val b64 = ImagePreparer.base64NoWrap(jpeg)
                val payload = Arguments.createMap().apply {
                    putString("jpegBase64", b64)
                    putInt("width", scaled.width)
                    putInt("height", scaled.height)
                }
                RifoEventBus.emit(EVT_CAPTURE_READY, payload)
                scaled.recycle()
            } catch (t: Throwable) {
                Log.e(TAG, "Image preparation failed", t)
                emitError("capture", t.message ?: "Could not prepare the image.")
            } finally {
                preparing = false
            }
        }
    }

    private fun emitError(code: String, message: String) {
        val payload = Arguments.createMap().apply {
            putString("code", code)
            putString("message", message)
        }
        RifoEventBus.emit(EVT_ERROR, payload)
    }

    // ---- cleanup ------------------------------------------------------------------

    private fun stopForegroundCompat() {
        try {
            if (Build.VERSION.SDK_INT >= 24) {
                stopForeground(STOP_FOREGROUND_REMOVE)
            } else {
                @Suppress("DEPRECATION")
                stopForeground(true)
            }
        } catch (_: Exception) {
        }
    }

    private fun cleanup() {
        if (cleaning) return
        cleaning = true
        hideBubbleFromWindow()
        try {
            virtualDisplay?.release()
        } catch (_: Exception) {
        }
        virtualDisplay = null
        try {
            imageReader?.close()
        } catch (_: Exception) {
        }
        imageReader = null
        try {
            projectionCallback?.let { c -> mediaProjection?.unregisterCallback(c) }
            mediaProjection?.stop()
        } catch (_: Exception) {
        }
        projectionCallback = null
        mediaProjection = null
        releasePending()
        cleaning = false
    }

    // ---- static surface used by OverlayModule ---------------------------------------

    companion object {
        private const val TAG = "RifoOverlay"
        private const val CHANNEL_ID = "rifo_overlay"
        private const val NOTIF_ID = 9001
        private const val BUBBLE_DP = 60
        private const val BUBBLE_MARGIN_DP = 8
        private const val MAX_EDGE_PX = 1280
        private const val JPEG_QUALITY = 75

        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"

        const val EVT_CAPTURE_READY = "RifoCaptureReady"
        const val EVT_BUBBLE_TAPPED = "RifoBubbleTapped"
        const val EVT_ERROR = "RifoError"
        const val EVT_SERVICE_STOPPED = "RifoServiceStopped"

        @Volatile
        private var instance: OverlayService? = null

        @Volatile
        private var userStopped = false

        fun isRunning(): Boolean = instance != null

        fun start(context: Context, resultCode: Int, data: Intent) {
            userStopped = false
            val intent = Intent(context, OverlayService::class.java).apply {
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, data)
            }
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            userStopped = true
            context.stopService(Intent(context, OverlayService::class.java))
        }

        fun setBubbleState(state: String, payload: String?) {
            val svc = instance ?: return
            svc.mainHandler.post {
                if (svc.cleaning) return@post
                svc.showBubble() // re-add if it had been dismissed
                svc.bubble?.applyState(state, payload)
            }
        }

        fun hideBubble(context: Context) {
            val svc = instance ?: return
            svc.mainHandler.post { svc.hideBubbleFromWindow() }
        }
    }
}
