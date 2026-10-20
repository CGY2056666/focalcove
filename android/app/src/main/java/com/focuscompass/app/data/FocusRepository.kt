package com.focuscompass.app.data

import com.focuscompass.app.model.AuthPayload
import com.focuscompass.app.model.AuthRequest
import com.focuscompass.app.model.BootstrapPayload
import com.focuscompass.app.model.CompleteRequest
import com.focuscompass.app.model.CompletionPayload
import com.focuscompass.app.model.DenConfig
import com.focuscompass.app.model.DenPayload
import com.focuscompass.app.model.DenUpdateRequest
import com.focuscompass.app.model.ExchangeRequest
import com.focuscompass.app.model.FocusSessionPayload
import com.focuscompass.app.model.HistoryItem
import com.focuscompass.app.model.StartFocusRequest
import com.focuscompass.app.network.FocusApi
import com.focuscompass.app.security.TokenVault
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

interface FocusRepository {
    suspend fun register(username: String, password: String): AuthPayload
    suspend fun login(username: String, password: String): AuthPayload
    suspend fun logout()
    suspend fun bootstrap(goal: String? = null): BootstrapPayload
    suspend fun currentSession(): FocusSessionPayload?
    suspend fun startSession(goal: String, durationMinutes: Int, reminderMode: String): FocusSessionPayload
    suspend fun getSession(sessionId: String): FocusSessionPayload
    suspend fun uploadFrame(
        sessionId: String,
        jpeg: ByteArray,
        frameId: String,
        capturedAt: String,
    ): FocusSessionPayload
    suspend fun completeSession(sessionId: String, reason: String): CompletionPayload
    suspend fun abandonSession(sessionId: String)
    suspend fun history(limit: Int = 50): List<HistoryItem>
    suspend fun den(): DenPayload
    suspend fun updateDen(config: DenConfig): DenPayload
    suspend fun exchangeFurniture(itemId: String): DenPayload
}

class NetworkFocusRepository(
    private val api: FocusApi,
    private val tokenVault: TokenVault,
    private val preferences: AppPreferences,
) : FocusRepository {
    override suspend fun register(username: String, password: String): AuthPayload =
        api.register(AuthRequest(username.trim(), password)).also(::saveAuth)

    override suspend fun login(username: String, password: String): AuthPayload =
        api.login(AuthRequest(username.trim(), password)).also(::saveAuth)

    override suspend fun logout() {
        try {
            protectedCall {
                val response = api.logout()
                if (!response.isSuccessful) throw HttpException(response)
            }
        } finally {
            tokenVault.clear()
            preferences.setActiveSessionId(null)
        }
    }

    override suspend fun bootstrap(goal: String?): BootstrapPayload =
        protectedCall { api.bootstrap(goal) }

    override suspend fun currentSession(): FocusSessionPayload? = protectedCall {
        val response = api.currentSession()
        if (response.code() == 204 || response.code() == 404) return@protectedCall null
        if (!response.isSuccessful) throw HttpException(response)
        response.body()
    }

    override suspend fun startSession(
        goal: String,
        durationMinutes: Int,
        reminderMode: String,
    ): FocusSessionPayload = protectedCall {
        api.startSession(StartFocusRequest(goal.trim(), durationMinutes, reminderMode))
    }

    override suspend fun getSession(sessionId: String): FocusSessionPayload =
        protectedCall { api.getSession(sessionId) }

    override suspend fun uploadFrame(
        sessionId: String,
        jpeg: ByteArray,
        frameId: String,
        capturedAt: String,
    ): FocusSessionPayload {
        val image = jpeg.toRequestBody("image/jpeg".toMediaType())
        return protectedCall {
            api.uploadFrame(
                sessionId,
                MultipartBody.Part.createFormData("screenshot", "$frameId.jpg", image),
                frameId.toRequestBody("text/plain".toMediaType()),
                capturedAt.toRequestBody("text/plain".toMediaType()),
            )
        }
    }

    override suspend fun completeSession(sessionId: String, reason: String): CompletionPayload =
        protectedCall { api.completeSession(sessionId, CompleteRequest(reason)) }

    override suspend fun abandonSession(sessionId: String) {
        protectedCall {
            val response = api.abandonSession(sessionId)
            if (!response.isSuccessful) throw HttpException(response)
        }
    }

    override suspend fun history(limit: Int): List<HistoryItem> =
        protectedCall { api.history(limit.coerceIn(1, 50)).items }

    override suspend fun den(): DenPayload = protectedCall { api.den() }

    override suspend fun updateDen(config: DenConfig): DenPayload =
        protectedCall { api.updateDen(DenUpdateRequest(config)) }

    override suspend fun exchangeFurniture(itemId: String): DenPayload =
        protectedCall { api.exchangeFurniture(ExchangeRequest(itemId)) }

    private fun saveAuth(payload: AuthPayload) {
        tokenVault.save(payload.token, payload.expiresAt)
    }

    private suspend fun <T> protectedCall(block: suspend () -> T): T = try {
        block()
    } catch (throwable: HttpException) {
        if (com.focuscompass.app.security.AuthenticationFailure.requiresLogout(throwable.code())) {
            tokenVault.clear()
            preferences.setActiveSessionId(null)
        }
        throw throwable
    }
}
