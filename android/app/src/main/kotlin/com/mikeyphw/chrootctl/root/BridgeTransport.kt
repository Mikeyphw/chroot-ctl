package com.mikeyphw.chrootctl.root

import android.os.ParcelFileDescriptor

/**
 * Narrow transport boundary consumed by repositories.
 *
 * Keeping Binder ownership behind this interface makes privileged orchestration
 * directly unit-testable without weakening the fixed AIDL contract.
 */
public interface BridgeTransport {
    suspend fun serviceInfo(): String
    suspend fun capabilities(): String
    suspend fun query(requestJson: String): String
    suspend fun preview(requestJson: String): String
    suspend fun operationState(operationId: String): String
    suspend fun reconcileOperation(operationId: String): String
    suspend fun cancelOperation(operationId: String): String
    suspend fun transferFromDescriptor(requestJson: String, input: ParcelFileDescriptor): String
    suspend fun transferToDescriptor(requestJson: String, output: ParcelFileDescriptor): String
    suspend fun streamOperation(requestJson: String, onEvent: suspend (String) -> Unit): String
    fun close()
}
