import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.focuscompass.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.focuscompass.app"
        minSdk = 29
        targetSdk = 36
        versionCode = 6
        versionName = "0.6.0"

        val rawBaseUrl = providers.gradleProperty("FOCUS_API_BASE_URL")
            .orElse("https://example.invalid/")
            .get()
            .trim()
        val parsedBaseUrl = URI(rawBaseUrl)
        require(parsedBaseUrl.scheme.equals("https", ignoreCase = true)) {
            "FOCUS_API_BASE_URL must use HTTPS"
        }
        require(!parsedBaseUrl.host.isNullOrBlank()) {
            "FOCUS_API_BASE_URL must include a valid hostname"
        }
        require(
            parsedBaseUrl.rawUserInfo == null &&
                parsedBaseUrl.rawQuery == null &&
                parsedBaseUrl.rawFragment == null
        ) {
            "FOCUS_API_BASE_URL cannot contain credentials, query parameters, or fragments"
        }
        val configuredBaseUrl = rawBaseUrl
            .let { if (it.endsWith('/')) it else "$it/" }
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
        buildConfigField("String", "FOCUS_API_BASE_URL", "\"$configuredBaseUrl\"")
        buildConfigField(
            "boolean",
            "FOCUS_SERVER_CONFIGURED",
            (!parsedBaseUrl.host.equals("example.invalid", ignoreCase = true)).toString(),
        )
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.06.00"))
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")
    implementation("androidx.navigation:navigation-compose:2.9.1")
    implementation("androidx.datastore:datastore-preferences:1.1.7")
    implementation("androidx.work:work-runtime-ktx:2.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation("junit:junit:4.13.2")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
