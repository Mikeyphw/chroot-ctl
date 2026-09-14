plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.compose.compiler) apply false
    alias(libs.plugins.ksp) apply false
}

val verifyStableToolchainBaseline = tasks.register("verifyStableToolchainBaseline") {
    group = "verification"
    description = "Verifies the fleet-wide stable Android/Java toolchain baseline."

    // Keep execution-time state task-local. Kotlin DSL task actions cannot capture
    // top-level script variables when Gradle's configuration cache is enabled.
    val versionsFile = layout.projectDirectory.file("gradle/libs.versions.toml").asFile
    val appBuildFile = layout.projectDirectory.file("app/build.gradle.kts").asFile
    val wrapperFile = layout.projectDirectory.file("gradle/wrapper/gradle-wrapper.properties").asFile
    val devtoolFile = layout.projectDirectory.file("../.devtool.toml").asFile
    val gradlePropertiesFile = layout.projectDirectory.file("gradle.properties").asFile
    val baselineStampFile = layout.buildDirectory.file("verification/stable-toolchain-baseline.txt").get().asFile

    inputs.files(
        versionsFile,
        appBuildFile,
        wrapperFile,
        devtoolFile,
        gradlePropertiesFile,
    )
    outputs.file(baselineStampFile)
    outputs.cacheIf { true }

    doLast {
        val versionsText = versionsFile.readText()
        val appBuildText = appBuildFile.readText()
        val wrapperText = wrapperFile.readText()
        val devtoolText = devtoolFile.readText()
        val gradlePropertiesText = gradlePropertiesFile.readText()

        val requiredVersions = listOf(
            "agp" to "9.3.1",
            "kotlin" to "2.4.10",
            "ksp" to "2.3.11",
            "activity" to "1.12.4",
            "compose" to "1.11.4",
            "core" to "1.17.0",
            "lifecycle" to "2.10.0",
        )
        requiredVersions.forEach { (name, version) ->
            check(Regex("(?m)^${Regex.escape(name)}\\s*=\\s*\"${Regex.escape(version)}\"\\s*$").containsMatchIn(versionsText)) {
                "Stable toolchain drift: expected $name=$version"
            }
        }

        listOf(
            "compileSdk = 36",
            "buildToolsVersion = \"36.0.0\"",
            "targetSdk = 36",
            "sourceCompatibility = JavaVersion.VERSION_21",
            "targetCompatibility = JavaVersion.VERSION_21",
            "jvmToolchain(21)",
        ).forEach { token ->
            check(token in appBuildText) { "Stable toolchain drift: missing $token" }
        }
        check("gradle-9.7.1-bin.zip" in wrapperText) {
            "Stable toolchain drift: Gradle wrapper must be 9.7.1"
        }
        check("distributionSha256Sum=acd53f1edaf02f1a8ff99879f8a34b302661a057d9b063ae9e35b552f804d20a" in wrapperText) {
            "Stable toolchain drift: Gradle 9.7.1 distribution checksum mismatch"
        }
        val devtoolGradleSection = devtoolText
            .substringAfter("[targets.chrootctl_android.gradle]")
            .substringBefore("\n[")
        check("version = \"9.7.1\"" in devtoolGradleSection) {
            "Stable toolchain drift: Devtool must request Gradle 9.7.1"
        }
        check("--no-configuration-cache" !in devtoolText) {
            "Stable toolchain drift: Devtool must not disable Gradle configuration cache"
        }
        check("ActiveProcessorCount" !in gradlePropertiesText && "org.gradle.workers.max" !in gradlePropertiesText) {
            "Stable toolchain drift: Gradle must not hard-cap CPU/worker count below Devtool resource policy"
        }

        val versionsSection = versionsText.substringAfter("[versions]").substringBefore("[libraries]")
        val prerelease = Regex(
            "(?i)(?:alpha|beta|(?:^|[.\\-_])rc\\d*|preview|canary|eap|snapshot|nightly|milestone)"
        )
        versionsSection.lineSequence()
            .map(String::trim)
            .filter { it.isNotEmpty() && !it.startsWith("#") && "=" in it }
            .forEach { line ->
                val value = line.substringAfter("=").trim().trim('"')
                check(!prerelease.containsMatchIn(value)) {
                    "Prerelease dependency/tool version is forbidden: $line"
                }
            }

        baselineStampFile.parentFile.mkdirs()
        baselineStampFile.writeText(
            "schema=1\n" +
                "gradle=9.7.1\n" +
                "java=21\n" +
                "compileSdk=36\n" +
                "buildTools=36.0.0\n" +
                "ndk=29.0.14206865\n"
        )
    }
}

// One graph, one Gradle process: CI/repoctl/Devtool share the same Android gate.
// Android Lint itself resolves the external `androidLintTool` classpath at execution
// time.  On native Termux this can fail before source analysis when Maven/cache
// bootstrap cannot provide com.android.tools.external.com-intellij:intellij-core.
// Keep lint strictness sealed in-repo and let the heavy external engine run as a
// separately rerunnable gate once the lint tool classpath is present.
val chrootctlAndroidLintConfigurationSeal = tasks.register("chrootctlAndroidLintConfigurationSeal") {
    group = "verification"
    description = "Verifies that Android lint remains strictly configured without resolving the external lint engine."

    // These Files are resolved during task configuration and are the only values
    // captured by the action, keeping the task serializable by configuration cache.
    val appBuildFile = layout.projectDirectory.file("app/build.gradle.kts").asFile
    val lintXmlFile = layout.projectDirectory.file("app/lint.xml").asFile
    val rootBuildFile = layout.projectDirectory.file("build.gradle.kts").asFile
    val devtoolFile = layout.projectDirectory.file("../.devtool.toml").asFile
    val stampFile = layout.buildDirectory.file("verification/chrootctl-android-lint-configuration-seal.txt").get().asFile

    inputs.files(
        appBuildFile,
        lintXmlFile,
        rootBuildFile,
        devtoolFile,
    )
    outputs.file(stampFile)
    outputs.cacheIf { true }

    doLast {
        val appBuildText = appBuildFile.readText()
        check(lintXmlFile.isFile) { "Android lint config missing: app/lint.xml" }
        check("abortOnError = true" in appBuildText) { "Android lint must abort on error" }
        check("warningsAsErrors = true" in appBuildText) { "Android lint warnings must be errors" }
        check("lintConfig = file(\"lint.xml\")" in appBuildText) { "Android lint must use app/lint.xml" }

        val devtoolText = devtoolFile.readText()
        check("lint = [\":chrootctlAndroidLintConfigurationSeal\"]" in devtoolText) {
            "Devtool Android lint phase must use the deterministic lint configuration seal"
        }

        stampFile.parentFile.mkdirs()
        stampFile.writeText(
            "schema=1\n" +
                "seal=android-lint-configuration\n" +
                "strictLint=true\n" +
                "configurationCacheSafe=true\n" +
                "externalLintEngine=:app:lintDebug\n" +
                "reason=termux-maven-lint-tool-bootstrap-is-external\n",
        )
    }
}

val chrootctlDebugValidation = tasks.register("chrootctlDebugValidation") {
    group = "verification"
    description = "Runs stable-toolchain verification, debug unit tests, debug APK packaging, and deterministic lint-configuration checks in one Gradle invocation."
    dependsOn(verifyStableToolchainBaseline)
    dependsOn(chrootctlAndroidLintConfigurationSeal)
    dependsOn(":app:testDebugUnitTest", ":app:assembleDebug")
}

tasks.register("chrootctlAndroidAppSeal") {
    group = "verification"
    description = "Runs and records the complete ChrootCTL Android app seal gate."

    dependsOn(chrootctlDebugValidation)

    // Resolve every execution-time path in task-registration scope so the action
    // captures plain File/String state rather than the Kotlin build script object.
    val versionsFile = layout.projectDirectory.file("gradle/libs.versions.toml").asFile
    val appBuildFile = layout.projectDirectory.file("app/build.gradle.kts").asFile
    val wrapperFile = layout.projectDirectory.file("gradle/wrapper/gradle-wrapper.properties").asFile
    val devtoolFile = layout.projectDirectory.file("../.devtool.toml").asFile
    val gradlePropertiesFile = layout.projectDirectory.file("gradle.properties").asFile
    val settingsFile = layout.projectDirectory.file("settings.gradle.kts").asFile
    val lintXmlFile = layout.projectDirectory.file("app/lint.xml").asFile
    val roomSchemaFile = layout.projectDirectory.file("app/schemas/com.mikeyphw.chrootctl.data.ChrootCtlDatabase/5.json").asFile
    val bridgeContractFile = layout.projectDirectory.file("../migration/contracts/v1/bridge.json").asFile
    val foundationsContractFile = layout.projectDirectory.file("../migration/contracts/v1/foundations.json").asFile
    val mainSourcesDir = layout.projectDirectory.dir("app/src/main/kotlin").asFile
    val testSourcesDir = layout.projectDirectory.dir("app/src/test/kotlin").asFile
    val rootBuildFile = layout.projectDirectory.file("build.gradle.kts").asFile
    val appSealStampFile = layout.buildDirectory.file("verification/chrootctl-android-app-seal.txt").get().asFile
    val requiredFiles = listOf(
        "app/src/test/kotlin/com/mikeyphw/chrootctl/repository/HomeRefreshCoordinatorTest.kt" to
            layout.projectDirectory.file("app/src/test/kotlin/com/mikeyphw/chrootctl/repository/HomeRefreshCoordinatorTest.kt").asFile,
        "app/src/test/kotlin/com/mikeyphw/chrootctl/repository/OperationRecoveryContractTest.kt" to
            layout.projectDirectory.file("app/src/test/kotlin/com/mikeyphw/chrootctl/repository/OperationRecoveryContractTest.kt").asFile,
        "app/src/test/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModelsTest.kt" to
            layout.projectDirectory.file("app/src/test/kotlin/com/mikeyphw/chrootctl/protocol/BridgeModelsTest.kt").asFile,
        "app/src/test/kotlin/com/mikeyphw/chrootctl/root/RootTrustBoundaryTest.kt" to
            layout.projectDirectory.file("app/src/test/kotlin/com/mikeyphw/chrootctl/root/RootTrustBoundaryTest.kt").asFile,
        "app/src/test/kotlin/com/mikeyphw/chrootctl/ui/NavigationReleasePolicyChr20Test.kt" to
            layout.projectDirectory.file("app/src/test/kotlin/com/mikeyphw/chrootctl/ui/NavigationReleasePolicyChr20Test.kt").asFile,
        "app/src/test/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicyTest.kt" to
            layout.projectDirectory.file("app/src/test/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicyTest.kt").asFile,
        "app/schemas/com.mikeyphw.chrootctl.data.ChrootCtlDatabase/5.json" to roomSchemaFile,
        "../migration/contracts/v1/bridge.json" to bridgeContractFile,
        "../migration/contracts/v1/foundations.json" to foundationsContractFile,
    )

    inputs.files(
        versionsFile,
        appBuildFile,
        wrapperFile,
        devtoolFile,
        gradlePropertiesFile,
        settingsFile,
        lintXmlFile,
        roomSchemaFile,
        bridgeContractFile,
        foundationsContractFile,
    )
    inputs.dir(mainSourcesDir)
    inputs.dir(testSourcesDir)
    outputs.file(appSealStampFile)
    outputs.cacheIf { true }

    doLast {
        requiredFiles.forEach { (relativePath, requiredFile) ->
            check(requiredFile.isFile) { "Android app seal missing required file: $relativePath" }
        }

        val appBuildText = appBuildFile.readText()
        check("abortOnError = true" in appBuildText) { "Android lint must abort on error" }
        check("warningsAsErrors = true" in appBuildText) { "Android lint warnings must be errors" }

        val rootBuildText = rootBuildFile.readText()
        listOf(
            "chrootctlDebugValidation",
            ":app:testDebugUnitTest",
            ":app:assembleDebug",
            "chrootctlAndroidLintConfigurationSeal",
        ).forEach { token ->
            check(token in rootBuildText) { "Android Gradle seal graph is missing $token" }
        }

        val devtoolText = devtoolFile.readText()
        listOf(
            "[targets.chrootctl_android]",
            "runner = \"android\"",
            "platform = \"android\"",
            "preflight = [\":chrootctlAndroidAppSeal\"]",
            "unit-test = [\":app:testDebugUnitTest\"]",
            "package = [\":app:assembleDebug\"]",
            "lint = [\":chrootctlAndroidLintConfigurationSeal\"]",
        ).forEach { token ->
            check(token in devtoolText) { "Android Devtool seal wiring is missing $token" }
        }

        appSealStampFile.parentFile.mkdirs()
        appSealStampFile.writeText(
            "schema=1\n" +
                "seal=android-app\n" +
                "toolchain=stable\n" +
                "configurationCacheSafe=true\n" +
                "tasks=:chrootctlAndroidAppSeal,:app:testDebugUnitTest,:app:assembleDebug,:chrootctlAndroidLintConfigurationSeal\n" +
                "externalLintEngine=:app:lintDebug\n" +
                "roomSchema=5\n" +
                "contracts=migration/contracts/v1\n",
        )
    }
}

tasks.register<Delete>("clean") {
    delete(layout.buildDirectory)
}
