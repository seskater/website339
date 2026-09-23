package com.likedsongalarm

import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

/** Full-screen ringing view, shown over the lock screen. */
class AlarmActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O_MR1) {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON,
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        setContent {
            AlarmTheme(dark = true) {
                val state by AlarmService.ringState.collectAsState()
                var seenRinging by remember { mutableStateOf(false) }
                LaunchedEffect(state) {
                    if (state != null) seenRinging = true
                    // Close once the alarm stops (from here, the notification, or auto-stop).
                    else if (seenRinging) finish()
                }
                LaunchedEffect(Unit) {
                    delay(3_000)
                    if (AlarmService.ringState.value == null) finish()
                }
                RingingScreen(
                    state = state ?: RingState("Good morning", ""),
                    onSnooze = { startService(AlarmService.intent(this, AlarmService.ACTION_SNOOZE)) },
                    onNextSong = { startService(AlarmService.intent(this, AlarmService.ACTION_NEXT_SONG)) },
                    onDismiss = { startService(AlarmService.intent(this, AlarmService.ACTION_DISMISS)) },
                    snoozeMinutes = Prefs(this).settings.snoozeMinutes,
                )
            }
        }
    }
}

@Composable
private fun RingingScreen(
    state: RingState,
    snoozeMinutes: Int,
    onSnooze: () -> Unit,
    onNextSong: () -> Unit,
    onDismiss: () -> Unit,
) {
    var now by remember { mutableStateOf(LocalTime.now()) }
    LaunchedEffect(Unit) {
        while (true) { now = LocalTime.now(); delay(1_000) }
    }
    val colors = MaterialTheme.colorScheme

    Surface(color = colors.background) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Brush.verticalGradient(listOf(colors.secondary.copy(alpha = 0.35f), colors.background)))
                .safeDrawingPadding()
                .padding(24.dp),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                Modifier.widthIn(max = 420.dp).fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    now.format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT)),
                    fontSize = 64.sp,
                    fontWeight = FontWeight.Light,
                )
                Spacer(Modifier.height(24.dp))
                Box(
                    Modifier
                        .fillMaxWidth(0.75f)
                        .aspectRatio(1f)
                        .clip(RoundedCornerShape(16.dp))
                        .background(colors.surfaceContainerHigh),
                ) {
                    state.art?.let {
                        Image(
                            it.asImageBitmap(),
                            contentDescription = "Album art",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
                Spacer(Modifier.height(20.dp))
                Text(
                    state.title,
                    style = MaterialTheme.typography.headlineSmall,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    state.subtitle,
                    color = colors.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                state.note?.let {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        it,
                        style = MaterialTheme.typography.bodyMedium,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .clip(RoundedCornerShape(10.dp))
                            .background(colors.surfaceContainerHigh)
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                    )
                }
                Spacer(Modifier.height(28.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                    FilledTonalButton(onClick = onSnooze, modifier = Modifier.weight(1f).height(64.dp)) {
                        Text("Snooze $snoozeMinutes min", fontSize = 17.sp)
                    }
                    Button(onClick = onDismiss, modifier = Modifier.weight(1f).height(64.dp)) {
                        Text("I'm up", fontSize = 17.sp)
                    }
                }
                TextButton(onClick = onNextSong, modifier = Modifier.padding(top = 8.dp)) {
                    Text("Play a different song")
                }
            }
        }
    }
}
