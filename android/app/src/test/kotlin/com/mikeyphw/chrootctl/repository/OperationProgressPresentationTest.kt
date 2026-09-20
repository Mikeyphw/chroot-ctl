package com.mikeyphw.chrootctl.repository

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OperationProgressPresentationTest {
    @Test
    fun `live extraction progress includes bytes entries and current path`() {
        val payload = JSONObject()
            .put("phase", "extract")
            .put("percent", 61)
            .put("message", "Extracting root filesystem")
            .put("live", true)
            .put("bytes_done", 5L * 1024 * 1024 * 1024)
            .put("bytes_total", 10L * 1024 * 1024 * 1024)
            .put("entries", 33_921L)
            .put("current_path", "usr/lib/aarch64-linux-gnu/example/library.so")

        val text = payload.operationProgressDisplay("Working")
        assertTrue(text.contains("Extracting root filesystem"))
        assertTrue(text.contains("5.0 GiB / 10.0 GiB"))
        assertTrue(text.contains("33,921 entries"))
        assertTrue(text.contains("usr/lib/aarch64-linux-gnu/example/library.so"))
    }

    @Test
    fun `non live progress preserves the backend message`() {
        val payload = JSONObject()
            .put("phase", "validate")
            .put("message", "Validating imported root filesystem")

        assertEquals("Validating imported root filesystem", payload.operationProgressDisplay("Working"))
    }

    @Test
    fun `long extraction path keeps the useful tail`() {
        val payload = JSONObject()
            .put("message", "Extracting root filesystem")
            .put("live", true)
            .put("current_path", "very/long/path/that/keeps/going/through/usr/lib/aarch64-linux-gnu/libsomething.so")

        val text = payload.operationProgressDisplay("Working")
        assertTrue(text.contains("…"))
        assertTrue(text.endsWith("libsomething.so"))
    }
}

// Rich rclone transfer events use the same durable operation-detail presenter.
class RcloneOperationProgressPresentationTest {
    @Test
    fun `rclone progress includes rate eta and current object`() {
        val payload = JSONObject()
            .put("message", "Downloading remote archive")
            .put("live", true)
            .put("bytes_done", 7L * 1024 * 1024 * 1024)
            .put("bytes_total", 9L * 1024 * 1024 * 1024)
            .put("rate_bytes_per_second", 25L * 1024 * 1024)
            .put("eta_seconds", 99L)
            .put("current_object", "drive:chroots/androidos.tar.zst")

        val text = payload.operationProgressDisplay("Working")
        assertTrue(text.contains("7.0 GiB / 9.0 GiB"))
        assertTrue(text.contains("25.0 MiB/s"))
        assertTrue(text.contains("ETA 1m 39s"))
        assertTrue(text.contains("androidos.tar.zst"))
    }
}
