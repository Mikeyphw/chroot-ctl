package com.mikeyphw.chrootctl.repository

import android.os.ParcelFileDescriptor
import com.mikeyphw.chrootctl.data.CheckResultEntity
import com.mikeyphw.chrootctl.data.ChrootEntity
import com.mikeyphw.chrootctl.data.HomeSnapshotEntity
import com.mikeyphw.chrootctl.data.OperationEntity
import com.mikeyphw.chrootctl.root.BridgeTransport
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeRefreshCoordinatorTest {
    @Test
    fun refreshPersistsOneCoherentSnapshot() = runBlocking {
        val transport = FakeBridgeTransport()
        val store = RecordingHomeStore()
        val result = HomeRefreshCoordinator(transport, store) { 123_456L }.refresh()

        assertTrue(result.isSuccess)
        val snapshot = result.getOrThrow()
        assertEquals(1, snapshot.chrootCount)
        assertEquals(1, snapshot.operationCount)
        assertEquals(2, snapshot.warningCount)
        assertEquals(123_456L, snapshot.refreshedAt)
        assertFalse(snapshot.stale)
        assertEquals(listOf("demo"), store.chroots.map { it.name })
        assertEquals(listOf("op-1"), store.operations.map { it.operationId })
        assertEquals(1, store.replaceCount)
        assertEquals(0, store.markStaleCount)
        assertEquals(
            listOf("system.dashboard", "release.readiness", "chroots.list", "operations.list"),
            transport.queriedOperations,
        )
    }

    @Test
    fun transportFailureMarksCachedHomeStale() = runBlocking {
        val store = RecordingHomeStore()
        val transport = FakeBridgeTransport(failOperation = "chroots.list")

        val result = HomeRefreshCoordinator(transport, store) { 42L }.refresh()

        assertTrue(result.isFailure)
        assertEquals(0, store.replaceCount)
        assertEquals(1, store.markStaleCount)
    }

    private class RecordingHomeStore : HomeSnapshotStore {
        var replaceCount = 0
        var markStaleCount = 0
        var chroots: List<ChrootEntity> = emptyList()
        var operations: List<OperationEntity> = emptyList()

        override suspend fun replace(
            chroots: List<ChrootEntity>,
            operations: List<OperationEntity>,
            checks: List<CheckResultEntity>,
            snapshot: HomeSnapshotEntity,
        ) {
            replaceCount += 1
            this.chroots = chroots
            this.operations = operations
        }

        override suspend fun markStale() {
            markStaleCount += 1
        }
    }

    private class FakeBridgeTransport(
        private val failOperation: String? = null,
    ) : BridgeTransport {
        val queriedOperations = mutableListOf<String>()

        override suspend fun serviceInfo(): String = JSONObject()
            .put("ok", true)
            .put("uid", 0)
            .put("gid", 0)
            .put("pid", 7)
            .put("backend", "go-native")
            .put("executable", "/data/adb/chrootctl/bin/chrootctl")
            .put("message", "ready")
            .toString()

        override suspend fun capabilities(): String = envelope(
            JSONObject()
                .put("protocolVersion", 1)
                .put("backendVersion", "test")
                .put("operations", JSONArray().put("chroots.list"))
                .put("arbitraryShell", false),
        )

        override suspend fun query(requestJson: String): String {
            val operation = JSONObject(requestJson).getString("operation")
            queriedOperations += operation
            if (operation == failOperation) error("simulated transport failure")
            return when (operation) {
                "system.dashboard" -> envelope(
                    JSONObject().put(
                        "checks",
                        JSONArray().put(
                            JSONObject()
                                .put("id", "storage")
                                .put("title", "Storage")
                                .put("message", "low")
                                .put("severity", "warning"),
                        ),
                    ),
                )
                "release.readiness" -> envelope(JSONObject().put("summary", "ready").put("checks", JSONArray()))
                "chroots.list" -> envelope(
                    JSONArray().put(
                        JSONObject()
                            .put("name", "demo")
                            .put("distribution", "ubuntu")
                            .put("status", "stopped")
                            .put("warningCount", 0),
                    ),
                )
                "operations.list" -> envelope(
                    JSONArray().put(
                        JSONObject()
                            .put("operationId", "op-1")
                            .put("kind", "install")
                            .put("title", "Install")
                            .put("state", "failed"),
                    ),
                )
                else -> error("unexpected query $operation")
            }
        }

        override suspend fun preview(requestJson: String): String = error("unused")
        override suspend fun operationState(operationId: String): String = error("unused")
        override suspend fun reconcileOperation(operationId: String): String = error("unused")
        override suspend fun cancelOperation(operationId: String): String = error("unused")
        override suspend fun transferFromDescriptor(requestJson: String, input: ParcelFileDescriptor): String = error("unused")
        override suspend fun transferToDescriptor(requestJson: String, output: ParcelFileDescriptor): String = error("unused")
        override suspend fun transferState(requestId: String): String = error("unused")
        override suspend fun cancelTransfer(requestId: String): String = error("unused")
        override suspend fun streamOperation(requestJson: String, onEvent: suspend (String) -> Unit): String = error("unused")
        override fun close() = Unit

        private fun envelope(data: Any): String = JSONObject()
            .put("protocolVersion", 1)
            .put("requestId", "test")
            .put("ok", true)
            .put("data", data)
            .put("warnings", JSONArray())
            .put("nextSteps", JSONArray())
            .toString()
    }
}
