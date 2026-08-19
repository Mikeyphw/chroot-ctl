plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.compose.compiler) apply false
    alias(libs.plugins.ksp) apply false
}

val verifyStableToolchainBaseline = tasks.register("verifyStableToolchainBaseline") {
    group = "verification"
    description = "Verifies the fleet-wide stable Android/Java toolchain baseline."

    doLast {
        val versionsText = file("gradle/libs.versions.toml").readText()
        val appBuildText = file("app/build.gradle.kts").readText()
        val wrapperText = file("gradle/wrapper/gradle-wrapper.properties").readText()
        val devtoolText = file("../.devtool.toml").readText()

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
            check(Regex("(?m)^${Regex.escape(name)}\\s*=\\s*\\\"${Regex.escape(version)}\\\"\\s*$").containsMatchIn(versionsText)) {
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
    }
}

tasks.register<Delete>("clean") {
    delete(layout.buildDirectory)
}
