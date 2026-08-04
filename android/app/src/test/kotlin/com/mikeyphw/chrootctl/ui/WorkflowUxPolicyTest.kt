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
