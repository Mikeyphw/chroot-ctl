package com.mikeyphw.chrootctl.root;

import android.os.ParcelFileDescriptor;

/** Fixed privileged interface. Arbitrary shell execution is deliberately absent. */
interface IChrootRootService {
    String serviceInfo();
    String capabilities();
    String query(String requestJson);
    String preview(String requestJson);
    String startOperation(String requestJson, in ParcelFileDescriptor output);
    String operationState(String operationId);
    String reconcileOperation(String operationId);
    String cancelOperation(String operationId);
    String transferFromDescriptor(String requestJson, in ParcelFileDescriptor input);
    String transferToDescriptor(String requestJson, in ParcelFileDescriptor output);
    String transferState(String requestId);
    String cancelTransfer(String requestId);
}
