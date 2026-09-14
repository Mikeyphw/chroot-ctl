package com.mikeyphw.chrootctl.ui

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidAppSealPolicyTest {
    private fun repoRoot(): File {
        var current = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(8) {
            if (File(current, ".devtool.toml").isFile && File(current, "android/build.gradle.kts").isFile) {
                return current
            }
            current = current.parentFile ?: error("Unable to locate repository root from ${System.getProperty("user.dir")}")
        }
        error("Unable to locate repository root from ${System.getProperty("user.dir")}")
    }

    @Test
    fun `CHR21 Android app seal is wired into Devtool and Gradle`() {
        val root = repoRoot()
        val androidBuild = File(root, "android/build.gradle.kts").readText()
        val devtool = File(root, ".devtool.toml").readText()

        listOf(
            "tasks.register(\"chrootctlAndroidAppSeal\")",
            "dependsOn(chrootctlDebugValidation)",
            ":app:testDebugUnitTest",
            ":app:assembleDebug",
            "chrootctlAndroidLintConfigurationSeal",
            "warningsAsErrors = true",
        ).forEach { token ->
            assertTrue("Android Gradle seal wiring missing $token", token in androidBuild)
        }

        listOf(
            "[targets.chrootctl_android]",
            "runner = \"android\"",
            "platform = \"android\"",
            "preflight = [\":chrootctlAndroidAppSeal\"]",
            "unit-test = [\":app:testDebugUnitTest\"]",
            "package = [\":app:assembleDebug\"]",
            "lint = [\":chrootctlAndroidLintConfigurationSeal\"]",
        ).forEach { token ->
            assertTrue("Android Devtool seal wiring missing $token", token in devtool)
        }
    }

    @Test
    fun `CHR21 Android app seal keeps schema contracts and policy tests discoverable`() {
        val root = repoRoot()
        listOf(
            "android/app/schemas/com.mikeyphw.chrootctl.data.ChrootCtlDatabase/5.json",
            "migration/contracts/v1/bridge.json",
            "migration/contracts/v1/foundations.json",
            "android/app/src/test/kotlin/com/mikeyphw/chrootctl/repository/HomeRefreshCoordinatorTest.kt",
            "android/app/src/test/kotlin/com/mikeyphw/chrootctl/repository/OperationRecoveryContractTest.kt",
            "android/app/src/test/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModelsTest.kt",
            "android/app/src/test/kotlin/com/mikeyphw/chrootctl/root/RootTrustBoundaryTest.kt",
            "android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/NavigationReleasePolicyChr20Test.kt",
            "android/app/src/test/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicyTest.kt",
        ).forEach { relativePath ->
            assertTrue("Android app seal required file missing: $relativePath", File(root, relativePath).isFile)
        }
    }

    @Test
    fun `CHR21 Android seal keeps external lint engine explicit but not blocking Termux bootstrap`() {
        val root = repoRoot()
        val androidBuild = File(root, "android/build.gradle.kts").readText()
        val validateScript = File(root, ".devtool-artifact/validate.sh").readText()

        assertTrue(
            "Seal must document that :app:lintDebug remains the full external lint engine",
            "externalLintEngine=:app:lintDebug" in androidBuild,
        )
        assertTrue(
            "Artifact validator must use deterministic lint config seal instead of resolving androidLintTool",
            ":chrootctlAndroidLintConfigurationSeal" in validateScript && ":app:lintDebug" !in validateScript,
        )
    }


    @Test
    fun `CHR21 Android compile blockers stay fixed`() {
        val root = repoRoot()
        val bridgeProcess = File(root, "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/BridgeProcess.kt").readText()
        val rootService = File(root, "android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt").readText()

        assertTrue("BridgeProcess must avoid Android-incompatible Process.pid()", "process.pid()" !in bridgeProcess)
        assertTrue("BridgeProcess must keep a fallback PID resolver for process-tree termination", "processPidCompat(process)" in bridgeProcess)
        assertTrue("ChrootRootService must avoid unavailable OsConstants.O_DIRECTORY", "OsConstants.O_DIRECTORY" !in rootService)
        assertTrue("ChrootRootService must define the Linux O_DIRECTORY compatibility bit", "O_DIRECTORY_COMPAT = 0x10000" in rootService)
    }

    @Test
    fun `CHR22 Android seal task actions are configuration-cache safe`() {
        val root = repoRoot()
        val androidBuild = File(root, "android/build.gradle.kts").readText()
        val gradleProperties = File(root, "android/gradle.properties").readText()

        assertTrue(
            "Android project must keep Gradle configuration cache enabled",
            "org.gradle.configuration-cache=true" in gradleProperties,
        )
        assertTrue(
            "Lint seal must resolve execution files inside task-registration scope",
            "val appBuildFile = layout.projectDirectory.file(\"app/build.gradle.kts\").asFile" in androidBuild &&
                "val stampFile = layout.buildDirectory.file(\"verification/chrootctl-android-lint-configuration-seal.txt\").get().asFile" in androidBuild,
        )
        assertTrue(
            "Android app seal must resolve required paths before task execution",
            "val requiredFiles = listOf(" in androidBuild &&
                "check(requiredFile.isFile)" in androidBuild &&
                "file(relativePath)" !in androidBuild,
        )
        listOf(
            "stableVersionsFile",
            "stableAppBuildFile",
            "stableWrapperFile",
            "stableDevtoolFile",
            "stableGradlePropertiesFile",
            "androidAppSealStamp",
        ).forEach { forbiddenTopLevelCapture ->
            assertTrue(
                "Configuration-cache-unsafe top-level task state must stay removed: $forbiddenTopLevelCapture",
                forbiddenTopLevelCapture !in androidBuild,
            )
        }
        assertTrue(
            "Seal stamps must record configuration-cache safety",
            androidBuild.split("configurationCacheSafe=true").size == 3,
        )
    }

}
