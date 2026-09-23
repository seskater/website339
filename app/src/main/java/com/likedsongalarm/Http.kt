package com.likedsongalarm

import java.net.HttpURLConnection
import java.net.URL

class HttpResponse(val code: Int, val body: String, val retryAfterSeconds: Long?)

/** Tiny blocking HTTP helper; call from Dispatchers.IO. */
object Http {
    fun request(
        url: String,
        method: String = "GET",
        headers: Map<String, String> = emptyMap(),
        body: String? = null,
    ): HttpResponse {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 15_000
            conn.readTimeout = 15_000
            headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            if (body != null) {
                conn.doOutput = true
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code >= 400) conn.errorStream else conn.inputStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            return HttpResponse(code, text, conn.getHeaderField("Retry-After")?.toLongOrNull())
        } finally {
            conn.disconnect()
        }
    }
}
