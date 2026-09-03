package com.rifo.overlay

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import org.json.JSONObject
import kotlin.math.hypot
import kotlin.math.min

/**
 * The floating verification bubble (FR-1). A plain android.view.View — no
 * androidx, no XML, rendered entirely in code so the native build needs no new
 * dependencies. Colours mirror BUBBLE_COLORS in mobile/src/overlay.ts.
 *
 * Gesture contract (driven here, owned by OverlayService):
 *   - ACTION_DOWN arms a 600 ms long-press timer and tells the service to begin
 *     a capture attempt immediately (FR-2: "capture begins on ACTION_DOWN").
 *   - A finger lift before the timer discards the pending capture (emit nothing).
 *   - Holding past 600 ms fires haptics and commits the capture.
 *   - Movement beyond touch slop cancels the long press, discards the pending
 *     capture and drags the bubble (dragging never triggers a capture).
 *   - A short tap on a *verdict* bubble emits 'RifoBubbleTapped'.
 */
class OverlayBubble(context: Context) : View(context) {

    // Callbacks wired by OverlayService. All run on the main (touch) thread.
    var onDown: (() -> Unit)? = null
    var onDiscard: (() -> Unit)? = null
    var onLongPress: (() -> Unit)? = null
    var onDragged: ((dx: Float, dy: Float) -> Unit)? = null
    var onDragEnd: (() -> Unit)? = null
    var onTap: (() -> Unit)? = null

    enum class Ui { IDLE, WORKING, VERDICT, ERROR }

    private var ui = Ui.IDLE
    private var fillColor = BRAND_NAVY

    private val density = resources.displayMetrics.density
    private val touchSlop = (ViewConfiguration.get(context).scaledTouchSlop).toFloat()
    private val longPressMs = 600L

    private var downRawX = 0f
    private var downRawY = 0f
    private var lastRawX = 0f
    private var lastRawY = 0f
    private var dragged = false
    private var longFired = false
    private var pointerDown = false

    private var longPressRunnable: Runnable? = null
    private var spinRunnable: Runnable? = null
    private var spinAngle = 0f

    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val bodyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val markPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val spinnerArc = RectF()

    // ---- state from JS ----------------------------------------------------------

    /**
     * `state` in idle|working|verdict|error. For verdict, payload is JSON carrying
     * a "label" (genuine|misleading|fake|manipulated|insufficient); for error it
     * carries {code,message} (message is surfaced as a transient tooltip by JS).
     */
    fun applyState(state: String, payloadJson: String?) {
        ui = when (state) {
            "working" -> Ui.WORKING
            "verdict" -> {
                fillColor = verdictColor(payloadJson)
                Ui.VERDICT
            }
            "error" -> {
                fillColor = ERROR_RED
                Ui.ERROR
            }
            else -> {
                fillColor = BRAND_NAVY
                Ui.IDLE
            }
        }
        if (ui == Ui.WORKING) startSpinning() else stopSpinning()
        invalidate()
    }

    private fun verdictColor(payloadJson: String?): Int {
        val label = try {
            JSONObject(payloadJson ?: "{}").optString("label")
        } catch (_: Exception) {
            ""
        }
        return when (label) {
            "genuine" -> Color.parseColor("#0A7B3E")
            "misleading" -> Color.parseColor("#B26A00")
            "fake" -> Color.parseColor("#B3261E")
            "manipulated" -> Color.parseColor("#7B1FA2")
            else -> Color.parseColor("#616161") // insufficient + unknown fallback
        }
    }

    // ---- gestures -----------------------------------------------------------------

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                pointerDown = true
                dragged = false
                longFired = false
                downRawX = event.rawX
                downRawY = event.rawY
                lastRawX = event.rawX
                lastRawY = event.rawY
                onDown?.invoke()
                armLongPress()
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (!pointerDown) return true
                val dx = event.rawX - lastRawX
                val dy = event.rawY - lastRawY
                lastRawX = event.rawX
                lastRawY = event.rawY
                if (!longFired) {
                    val dist = hypot((event.rawX - downRawX).toDouble(), (event.rawY - downRawY).toDouble())
                    if (!dragged && dist > touchSlop) {
                        // Movement cancels the long press: this is now a drag, and a
                        // drag must never trigger a capture (FR-1).
                        dragged = true
                        cancelLongPress()
                        onDiscard?.invoke()
                    }
                    if (dragged) onDragged?.invoke(dx, dy)
                }
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                if (!pointerDown) return true
                pointerDown = false
                cancelLongPress()
                when {
                    longFired -> Unit // capture already committed on the hold
                    dragged -> onDragEnd?.invoke()
                    else -> {
                        onDiscard?.invoke() // drop the frame captured at ACTION_DOWN
                        if (ui == Ui.VERDICT) onTap?.invoke() // short tap opens the detail
                    }
                }
                dragged = false
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    private fun armLongPress() {
        cancelLongPress()
        val r = Runnable {
            if (!dragged && pointerDown) {
                longFired = true
                performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                onLongPress?.invoke()
            }
        }
        longPressRunnable = r
        postDelayed(r, longPressMs)
    }

    private fun cancelLongPress() {
        longPressRunnable?.let { removeCallbacks(it) }
        longPressRunnable = null
    }

    // ---- spinner -------------------------------------------------------------------

    private fun startSpinning() {
        if (spinRunnable != null) return
        val r = object : Runnable {
            override fun run() {
                spinAngle = (spinAngle + 18f) % 360f
                invalidate()
                if (ui == Ui.WORKING) postDelayed(this, 16L)
            }
        }
        spinRunnable = r
        post(r)
    }

    private fun stopSpinning() {
        spinRunnable?.let { removeCallbacks(it) }
        spinRunnable = null
    }

    // ---- drawing ---------------------------------------------------------------------

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        val cx = w / 2f
        val cy = h / 2f
        val stroke = 3f * density
        val radius = min(w, h) / 2f - stroke * 0.6f

        if (ui == Ui.IDLE) {
            // Brand ring + dot: reads as an idle control, not a verdict.
            ringPaint.color = Color.WHITE
            ringPaint.strokeWidth = stroke
            canvas.drawCircle(cx, cy, radius * 0.82f, ringPaint)
            ringPaint.color = BRAND_NAVY
            ringPaint.strokeWidth = stroke * 0.7f
            canvas.drawCircle(cx, cy, radius * 0.52f, ringPaint)
            markPaint.color = Color.WHITE
            markPaint.strokeWidth = stroke
            canvas.drawCircle(cx, cy, radius * 0.28f, markPaint)
            return
        }

        // Verdict / error / working all share a filled disc in their colour.
        bodyPaint.color = fillColor
        canvas.drawCircle(cx, cy, radius, bodyPaint)

        markPaint.color = Color.WHITE
        markPaint.strokeWidth = stroke * 1.1f
        when (ui) {
            Ui.VERDICT -> drawCheck(canvas, cx, cy, radius * 0.5f)
            Ui.ERROR -> drawExclamation(canvas, cx, cy, radius * 0.55f)
            Ui.WORKING -> drawSpinner(canvas, cx, cy, radius * 0.72f, stroke)
            Ui.IDLE -> Unit
        }
    }

    private fun drawCheck(canvas: Canvas, cx: Float, cy: Float, r: Float) {
        val p = Path()
        p.moveTo(cx - r * 0.75f, cy + r * 0.05f)
        p.lineTo(cx - r * 0.15f, cy + r * 0.62f)
        p.lineTo(cx + r * 0.85f, cy - r * 0.68f)
        canvas.drawPath(p, markPaint)
    }

    private fun drawExclamation(canvas: Canvas, cx: Float, cy: Float, r: Float) {
        val barW = r * 0.34f
        val top = cy - r * 0.85f
        val bottom = cy - r * 0.15f
        canvas.drawRoundRect(
            cx - barW / 2f, top, cx + barW / 2f, bottom,
            barW / 3f, barW / 3f, markPaint
        )
        canvas.drawCircle(cx, cy + r * 0.42f, r * 0.18f, markPaint)
    }

    private fun drawSpinner(canvas: Canvas, cx: Float, cy: Float, r: Float, stroke: Float) {
        spinnerArc.set(cx - r, cy - r, cx + r, cy + r)
        markPaint.strokeWidth = stroke
        canvas.drawArc(spinnerArc, spinAngle, 100f, false, markPaint)
    }

    companion object {
        private val BRAND_NAVY = Color.parseColor("#0A2E5C")
        private val ERROR_RED = Color.parseColor("#B3261E")
    }
}
