package ai.jarvis.ultimate.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import kotlin.math.cos
import kotlin.math.sin

val Cyan = Color(0xFF22D3EE)
val Blue = Color(0xFF3B82F6)
val Bg = Color(0xFF03070D)
val Panel = Color(0xFF0A1A28)
val Muted = Color(0xFF7AA3B8)
val Danger = Color(0xFFF87171)
val Ok = Color(0xFF34D399)
val Amber = Color(0xFFFBBF24)

fun stateColor(s: AssistantState) = when (s) {
    AssistantState.IDLE -> Cyan
    AssistantState.LISTENING -> Danger
    AssistantState.PROCESSING -> Color(0xFF60A5FA)
    AssistantState.SPEAKING -> Ok
}

/** The animated core. Waveform amplitude comes only from the real microphone level / speaking state. */
@Composable
fun JarvisCore(state: AssistantState, micLevel: Float, modifier: Modifier = Modifier) {
    val t by rememberInfiniteTransition(label = "core").animateFloat(
        0f, 360f, infiniteRepeatable(tween(12_000, easing = LinearEasing), RepeatMode.Restart), label = "t")
    val c = stateColor(state)
    val speed = when (state) { AssistantState.IDLE -> 1f; AssistantState.LISTENING -> 3f; AssistantState.PROCESSING -> 8f; AssistantState.SPEAKING -> 4f }
    val amp = when (state) {
        AssistantState.LISTENING -> 4f + micLevel * 22f
        AssistantState.SPEAKING -> 8f
        AssistantState.PROCESSING -> 2f
        AssistantState.IDLE -> 0f
    }
    Canvas(modifier.aspectRatio(1f)) {
        val center = Offset(size.width / 2, size.height / 2)
        val r = size.minDimension * 0.36f
        drawCircle(Brush.radialGradient(listOf(c.copy(alpha = 0.35f), Color.Transparent), center, r * 1.3f), r * 1.3f, center)
        listOf(Triple(1f, 0.9f, 1f), Triple(0.86f, 0.5f, -1.4f), Triple(0.72f, 0.35f, 2.2f)).forEachIndexed { i, (k, alpha, dir) ->
            rotate(t * speed * dir, center) {
                for (s in 0 until 6) {
                    drawArc(c.copy(alpha = alpha), s * 60f, 50f, false,
                        topLeft = Offset(center.x - r * k, center.y - r * k), size = Size(2 * r * k, 2 * r * k),
                        style = Stroke(width = (6 - i * 2).toFloat().coerceAtLeast(2f), cap = StrokeCap.Round))
                }
            }
        }
        val phase = Math.toRadians(t.toDouble() * 20).toFloat()
        val path = Path()
        for (i in 0..180) {
            val a = (i / 180f) * 2f * Math.PI.toFloat()
            val rr = r * 0.56f + amp * sin(a * 9 + phase) * sin(a * 3 - phase / 2)
            val p = Offset(center.x + rr * cos(a), center.y + rr * sin(a))
            if (i == 0) path.moveTo(p.x, p.y) else path.lineTo(p.x, p.y)
        }
        path.close()
        drawPath(path, c, style = Stroke(width = 3f))
        drawCircle(c, r * 0.12f + micLevel * 8f, center)
    }
}
