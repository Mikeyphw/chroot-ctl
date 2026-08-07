package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.InstallDraft
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ServiceUnitSummary
import com.mikeyphw.chrootctl.model.UserSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkflowUxPolicyTest {
    @Test
    fun `chroot search covers distro status path and health`() {
        val chroot = sampleChroot(name = "ubuntu", distro = "Ubuntu", status = "running", health = "warn")
        assertTrue(chrootMatchesQuery(chroot, "ubuntu"))
        assertTrue(chrootMatchesQuery(chroot, "running"))
        assertTrue(chrootMatchesQuery(chroot, "/data"))
        assertFalse(chrootMatchesQuery(chroot, "arch"))
    }

    @Test
    fun `chroot filters separate running stopped and attention`() {
        val running = sampleChroot(status = "active", warnings = 0)
        val stopped = sampleChroot(status = "stopped", warnings = 0)
        val warning = sampleChroot(status = "stopped", warnings = 2)
        assertTrue(chrootMatchesFilter(running, ChrootListFilter.Running))
        assertTrue(chrootMatchesFilter(stopped, ChrootListFilter.Stopped))
        assertTrue(chrootMatchesFilter(warning, ChrootListFilter.Attention))
        assertFalse(chrootMatchesFilter(running, ChrootListFilter.Stopped))
    }

    @Test
    fun `install draft validation is strict but practical`() {
        assertTrue(validateInstallDraft(InstallDraft(distro = "ubuntu", name = "ubuntu-dev", username = "mike")).valid)
        assertFalse(validateInstallDraft(InstallDraft(distro = "", name = "ubuntu", username = "mike")).valid)
        assertFalse(validateInstallDraft(InstallDraft(distro = "ubuntu", name = " bad", username = "mike")).valid)
        assertFalse(validateInstallDraft(InstallDraft(distro = "ubuntu", name = "ubuntu", username = "Mike")).valid)
    }



    @Test
    fun `chroot list launches workspace instead of rendering inline management`() {
        val chroot = sampleChroot(name = "androidos", distro = "Ubuntu", status = "registered", health = "stale")
        assertTrue(chrootListIsWorkspaceLauncherOnly())
        assertTrue(chrootWorkspaceSummary(chroot).contains("Ubuntu"))
        assertTrue(chrootWorkspaceSummary(chroot).contains("/data/local/chroots/androidos"))
        assertTrue(chrootWorkspaceTabs().contains(ChrootWorkspaceTab.Services))
        assertTrue(chrootWorkspaceTabs().contains(ChrootWorkspaceTab.Users))
    }

    @Test
    fun `bridge shape errors become human readable workspace messages`() {
        val raw = "Bridge response data was array; expected a JSON object"
        assertTrue(isBridgeShapeError(raw))
        assertTrue(bridgeShapePrimaryMessage(raw).contains("backend returned a list", ignoreCase = true))
    }


    @Test
    fun `service workspace filters keep noisy service lists focused`() {
        val running = sampleService(status = "running", enabled = true)
        val failed = sampleService(status = "failed", enabled = false, description = "Unit failed")
        val stopped = sampleService(status = "stopped", enabled = false)
        val journalOnly = sampleService(status = "running", enabled = true, journalText = "recent healthy log output")
        val unknown = sampleService(status = "unknown", enabled = false)
        assertTrue(serviceMatchesWorkspaceFilter(running, ServiceWorkspaceFilter.Running))
        assertTrue(serviceMatchesWorkspaceFilter(running, ServiceWorkspaceFilter.Enabled))
        assertTrue(serviceMatchesWorkspaceFilter(failed, ServiceWorkspaceFilter.Stale))
        assertTrue(serviceMatchesWorkspaceFilter(failed, ServiceWorkspaceFilter.Failed))
        assertFalse(serviceMatchesWorkspaceFilter(stopped, ServiceWorkspaceFilter.Running))
        assertFalse(serviceMatchesWorkspaceFilter(stopped, ServiceWorkspaceFilter.Failed))
        assertFalse(serviceNeedsAttention(stopped))
        assertFalse(serviceNeedsAttention(journalOnly))
        assertFalse(serviceNeedsAttention(unknown))
    }


    @Test
    fun `user workspace hides system accounts by default but keeps normal login users`() {
        val login = sampleUser(username = "mike", uid = "1000", shell = "/bin/bash", sudo = true)
        val daemon = sampleUser(username = "daemon", uid = "1", shell = "/usr/sbin/nologin")
        val highUidNoLogin = sampleUser(username = "worker", uid = "1001", shell = "/bin/false")
        val root = sampleUser(username = "root", uid = "0", shell = "/bin/bash", sudo = true)

        assertTrue(userMatchesWorkspaceFilter(login, UserWorkspaceFilter.Managed))
        assertTrue(userMatchesWorkspaceFilter(login, UserWorkspaceFilter.LoginUsers))
        assertFalse(userMatchesWorkspaceFilter(login, UserWorkspaceFilter.SystemUsers))
        assertTrue(userIsSystem(daemon))
        assertTrue(userIsSystem(highUidNoLogin))
        assertFalse(userMatchesWorkspaceFilter(daemon, UserWorkspaceFilter.Managed))
        assertTrue(userMatchesWorkspaceFilter(daemon, UserWorkspaceFilter.SystemUsers))
        assertTrue(userMatchesWorkspaceFilter(root, UserWorkspaceFilter.Managed))
        assertFalse(userIsSystem(root))
    }

    @Test
    fun `user workspace actions keep mutations inside review flow`() {
        val existing = userWorkspaceActions(existingUser = true)
        assertTrue(existing.contains(UserWorkspaceAction.SetShell))
        assertTrue(existing.contains(UserWorkspaceAction.SetPassword))
        assertTrue(existing.contains(UserWorkspaceAction.Remove))
        assertFalse(existing.contains(UserWorkspaceAction.Add))
        assertTrue(userWorkspaceActions(existingUser = false) == listOf(UserWorkspaceAction.Add))
    }

    @Test
    fun `phase 39 workspace exposes recovery storage logs and advanced rooms`() {
        val tabs = chrootWorkspaceTabs()
        assertTrue(tabs.contains(ChrootWorkspaceTab.Snapshots))
        assertTrue(tabs.contains(ChrootWorkspaceTab.Storage))
        assertTrue(tabs.contains(ChrootWorkspaceTab.Logs))
        assertTrue(tabs.contains(ChrootWorkspaceTab.Advanced))
        assertTrue(SnapshotWorkspaceAction.entries.containsAll(listOf(SnapshotWorkspaceAction.Create, SnapshotWorkspaceAction.Restore, SnapshotWorkspaceAction.Export)))
    }

    @Test
    fun `log workspace filters map only to allowlisted severity values`() {
        assertEquals(null, logWorkspaceBridgeLevel(LogWorkspaceFilter.All))
        assertEquals("WARNING", logWorkspaceBridgeLevel(LogWorkspaceFilter.Warning))
        assertEquals("ERROR", logWorkspaceBridgeLevel(LogWorkspaceFilter.Error))
        assertEquals(LogWorkspaceFilter.All, selectedLogWorkspaceFilter("unknown"))
    }

    @Test
    fun `failed chroot operation offers snapshot recovery but completed work does not`() {
        val failed = sampleOperation(state = "failed", target = "androidos")
        val interrupted = sampleOperation(state = "interrupted", target = "androidos")
        val blocked = sampleOperation(state = "blocked", target = "androidos")
        val complete = sampleOperation(state = "complete", target = "androidos")
        val other = sampleOperation(state = "failed", target = "ubuntu")
        assertTrue(operationNeedsSnapshotRecovery(failed, "androidos"))
        assertTrue(operationNeedsSnapshotRecovery(interrupted, "androidos"))
        assertTrue(operationNeedsSnapshotRecovery(blocked, "androidos"))
        assertFalse(operationNeedsSnapshotRecovery(complete, "androidos"))
        assertFalse(operationNeedsSnapshotRecovery(other, "androidos"))
    }

    @Test
    fun `snapshot execution requires preview for the exact reviewed action and snapshot`() {
        assertTrue(snapshotPreviewMatches(SnapshotWorkspaceAction.Restore, "snap-2", "restore", "snap-2"))
        assertTrue(snapshotPreviewMatches(SnapshotWorkspaceAction.Export, "snap-2", "EXPORT", "snap-2"))
        assertFalse(snapshotPreviewMatches(SnapshotWorkspaceAction.Restore, "snap-2", "export", "snap-2"))
        assertFalse(snapshotPreviewMatches(SnapshotWorkspaceAction.Restore, "snap-2", "restore", "snap-1"))
        assertFalse(snapshotPreviewMatches(SnapshotWorkspaceAction.Create, "", "create", ""))
    }

    @Test
    fun `storage formatting stays compact and deterministic`() {
        assertEquals("0 B", formatStorageBytes(-1))
        assertEquals("1 KiB", formatStorageBytes(1024))
        assertEquals("1 MiB", formatStorageBytes(1024L * 1024L))
        assertEquals("1 GiB", formatStorageBytes(1024L * 1024L * 1024L))
    }

    private fun sampleChroot(
        name: String = "ubuntu",
        distro: String = "Ubuntu",
        status: String = "running",
        health: String = "ok",
        warnings: Int = 0,
    ): ChrootSummary = ChrootSummary(
        name = name,
        distribution = distro,
        release = "24.04",
        architecture = "arm64",
        path = "/data/local/chroots/$name",
        status = status,
        mountState = status,
        health = health,
        warningCount = warnings,
        rawJson = "{}",
        lastRefreshAt = 1L,
        stale = false,
    )
    private fun sampleService(
        status: String = "running",
        enabled: Boolean = true,
        description: String = "Service",
        journalText: String = "",
    ): ServiceUnitSummary = ServiceUnitSummary(
        service = "vscode-web",
        chrootName = "androidos",
        status = status,
        enabled = enabled,
        boot = enabled,
        description = description,
        journalText = journalText,
    )


    private fun sampleOperation(
        state: String,
        target: String,
    ): OperationSummary = OperationSummary(
        operationId = "op-1",
        kind = "chroots.upgrade",
        title = "Upgrade chroot",
        state = state,
        targetName = target,
        phase = null,
        progressPercent = null,
        progressText = "",
        errorCode = if (state == "failed") "TEST_FAILURE" else null,
        errorMessage = null,
        createdAt = 1L,
        stale = false,
    )


    private fun sampleUser(
        username: String,
        uid: String,
        shell: String,
        sudo: Boolean = false,
    ): UserSummary = UserSummary(
        username = username,
        uid = uid,
        gid = uid,
        home = "/home/$username",
        shell = shell,
        sudo = sudo,
    )

}
