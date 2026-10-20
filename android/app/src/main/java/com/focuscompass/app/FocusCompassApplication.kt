package com.focuscompass.app

import android.app.Application
import com.focuscompass.app.capture.CaptureRuntime
import com.focuscompass.app.capture.FocusRepositoryCaptureBackend
import com.focuscompass.app.data.AppPreferences
import com.focuscompass.app.data.FocusRepository
import com.focuscompass.app.data.NetworkFocusRepository
import com.focuscompass.app.network.NetworkModule
import com.focuscompass.app.security.TokenVault

class FocusCompassApplication : Application() {
    lateinit var repository: FocusRepository
        private set
    lateinit var preferences: AppPreferences
        private set
    lateinit var tokenVault: TokenVault
        private set

    override fun onCreate() {
        super.onCreate()
        tokenVault = TokenVault(this)
        preferences = AppPreferences(this)
        repository = NetworkFocusRepository(NetworkModule.createApi(tokenVault), tokenVault, preferences)
        CaptureRuntime.install(FocusRepositoryCaptureBackend(repository))
    }
}
