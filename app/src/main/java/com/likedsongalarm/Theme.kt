package com.likedsongalarm

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val SpotifyGreen = Color(0xFF1ED760)
private val Warm = Color(0xFFF09A4A)

private val Dark = darkColorScheme(
    primary = SpotifyGreen,
    onPrimary = Color(0xFF04200C),
    secondary = Warm,
    background = Color(0xFF0F1115),
    surface = Color(0xFF0F1115),
    surfaceContainer = Color(0xFF181B21),
    surfaceContainerHigh = Color(0xFF22262E),
)

private val Light = lightColorScheme(
    primary = Color(0xFF15883E),
    onPrimary = Color.White,
    secondary = Color(0xFFB45A12),
    background = Color(0xFFF6F4EF),
    surface = Color(0xFFF6F4EF),
    surfaceContainer = Color.White,
    surfaceContainerHigh = Color(0xFFEFECE5),
)

@Composable
fun AlarmTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (dark) Dark else Light, content = content)
}
