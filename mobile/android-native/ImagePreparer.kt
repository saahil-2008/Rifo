package com.rifo.overlay

import android.graphics.Bitmap
import android.util.Base64
import java.io.ByteArrayOutputStream

/**
 * Pure image helpers for FR-3 (downscale to a max edge + JPEG q75 under ~200 KB,
 * off the main thread) and the FLAG_SECURE black-frame detector.
 */
object ImagePreparer {

    /**
     * Downscale so the longest edge is <= [maxEdge], preserving aspect ratio.
     * Returns the same instance when already small enough. Uses FILTER_BITMAP so
     * text-heavy UI stays legible for the vision model.
     */
    fun downscaleToMaxEdge(bitmap: Bitmap, maxEdge: Int = 1280): Bitmap {
        val longest = maxOf(bitmap.width, bitmap.height)
        if (longest <= maxEdge) return bitmap
        val scale = maxEdge.toFloat() / longest
        val w = (bitmap.width * scale).toInt().coerceAtLeast(1)
        val h = (bitmap.height * scale).toInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(bitmap, w, h, true)
    }

    /** Encode a bitmap to JPEG at [quality] (default 75). */
    fun encodeJpegQuality(bitmap: Bitmap, quality: Int = 75): ByteArray {
        val out = ByteArrayOutputStream(256 * 1024)
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        return out.toByteArray()
    }

    fun base64NoWrap(bytes: ByteArray): String =
        Base64.encodeToString(bytes, Base64.NO_WRAP)

    /**
     * Heuristic for a FLAG_SECURE screen: content we are not allowed to see is
     * rendered as a black frame, so a capture that is almost entirely near-black
     * should never be sent to the vision model. Sampled on a sparse grid for speed.
     *
     * NOTE: a legitimately all-black/dark screenshot could false-positive. In
     * practice almost every real screen has UI chrome, so the 0.90 near-black
     * ratio threshold is deliberately strict.
     *
     * @param blackThreshold per-pixel luminance below which counts as black (0-255)
     * @param blackRatio      minimum fraction of near-black samples to declare secure
     */
    fun isMostlyBlack(
        bitmap: Bitmap,
        sampleEvery: Int = 10,
        blackThreshold: Int = 8,
        blackRatio: Double = 0.90
    ): Boolean {
        val w = bitmap.width
        val h = bitmap.height
        if (w == 0 || h == 0) return true
        var total = 0
        var black = 0
        var y = 0
        while (y < h) {
            var x = 0
            while (x < w) {
                val px = bitmap.getPixel(x, y)
                val lum = ((px shr 16) and 0xFF) * 0.299 +
                    ((px shr 8) and 0xFF) * 0.587 +
                    (px and 0xFF) * 0.114
                if (lum < blackThreshold) black++
                total++
                x += sampleEvery
            }
            y += sampleEvery
        }
        return total > 0 && (black.toDouble() / total) >= blackRatio
    }
}
