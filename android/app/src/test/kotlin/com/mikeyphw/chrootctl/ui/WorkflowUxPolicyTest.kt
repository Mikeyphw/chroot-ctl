package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.InstallDraft
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
}
