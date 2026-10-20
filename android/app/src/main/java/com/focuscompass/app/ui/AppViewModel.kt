package com.focuscompass.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.focuscompass.app.data.AppPreferences
import com.focuscompass.app.data.FocusRepository
import com.focuscompass.app.model.BootstrapPayload
import com.focuscompass.app.model.CompletionPayload
import com.focuscompass.app.model.DenConfig
import com.focuscompass.app.model.DenPayload
import com.focuscompass.app.model.FocusSessionPayload
import com.focuscompass.app.model.HistoryItem
import com.focuscompass.app.network.ApiErrorParser
import com.focuscompass.app.security.TokenVault
import com.focuscompass.app.security.AuthenticationFailure
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant

data class AppUiState(
    val ready: Boolean = false,
    val privacyAccepted: Boolean = false,
    val soundEnabled: Boolean = true,
    val authenticated: Boolean = false,
    val loading: Boolean = false,
    val bootstrap: BootstrapPayload? = null,
    val activeSession: FocusSessionPayload? = null,
    val monitoringInterrupted: Boolean = false,
    val remainingSeconds: Long = 0,
    val completion: CompletionPayload? = null,
    val history: List<HistoryItem> = emptyList(),
    val den: DenPayload? = null,
    val denSaving: Boolean = false,
    val exchangingItemId: String? = null,
    val error: String? = null,
)

object SessionTimer {
    fun remainingSeconds(
        startedAt: Double?,
        durationMinutes: Int?,
        nowEpochSeconds: Long = Instant.now().epochSecond,
    ): Long {
        if (startedAt == null || !startedAt.isFinite() || durationMinutes == null) return 0
        val end = startedAt.toLong() + durationMinutes.coerceAtLeast(0) * 60L
        return (end - nowEpochSeconds).coerceAtLeast(0)
    }
}

class AppViewModel(
    private val repository: FocusRepository,
    private val preferences: AppPreferences,
    private val tokenVault: TokenVault,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AppUiState())
    val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()
    private var timerJob: Job? = null
    private val denOperationMutex = Mutex()
    private var pendingNetworkCalls = 0

    init {
        viewModelScope.launch {
            val privacyAccepted = preferences.privacyAccepted.first()
            val soundEnabled = preferences.soundEnabled.first()
            val activeId = preferences.activeSessionId.first()
            val authenticated = tokenVault.currentToken() != null
            _uiState.update {
                it.copy(
                    ready = true,
                    privacyAccepted = privacyAccepted,
                    soundEnabled = soundEnabled,
                    authenticated = authenticated,
                )
            }
            if (authenticated) {
                loadBootstrap()
                restoreSession(activeId)
            }
        }
    }

    fun acceptPrivacy() = viewModelScope.launch {
        preferences.setPrivacyAccepted(true)
        _uiState.update { it.copy(privacyAccepted = true) }
    }

    fun authenticate(username: String, password: String, register: Boolean) =
        launchNetwork(invalidateOnUnauthorized = false) {
        require(username.isNotBlank() && password.isNotBlank()) { "请输入用户名和密码" }
        if (register) repository.register(username, password) else repository.login(username, password)
        _uiState.update { it.copy(authenticated = true, den = null) }
        loadBootstrap()
        restoreSession(preferences.activeSessionId.first())
    }

    fun logout() = viewModelScope.launch {
        beginNetworkCall()
        var logoutError: String? = null
        try {
            repository.logout()
        } catch (throwable: Throwable) {
            logoutError = if (AuthenticationFailure.requiresLogout(
                    (throwable as? retrofit2.HttpException)?.code(),
                )
            ) {
                null
            } else {
                "服务器退出失败，已清除本机登录信息。"
            }
        } finally {
            clearLocalAuthentication(logoutError)
            finishNetworkCall()
        }
    }

    fun loadBootstrap(goal: String? = null) = launchNetwork {
        denOperationMutex.withLock {
            val payload = repository.bootstrap(goal?.trim()?.ifBlank { null })
            _uiState.update { it.copy(bootstrap = payload) }
        }
    }

    fun startSession(goal: String, durationMinutes: Int, reminderMode: String) = launchNetwork {
        require(goal.isNotBlank()) { "请填写本轮专注目标" }
        val session = try {
            repository.startSession(goal, durationMinutes, reminderMode)
        } catch (throwable: retrofit2.HttpException) {
            if (throwable.code() == 409) repository.currentSession() ?: throw throwable else throw throwable
        }
        preferences.setActiveSessionId(session.sessionId)
        _uiState.update {
            it.copy(activeSession = session, monitoringInterrupted = false, completion = null)
        }
        startTimer(session)
    }

    fun refreshSession() {
        val id = _uiState.value.activeSession?.sessionId ?: return
        launchNetwork {
            try {
                val session = repository.getSession(id)
                _uiState.update { it.copy(activeSession = session) }
                startTimer(session)
            } catch (throwable: retrofit2.HttpException) {
                if (throwable.code() == 404) {
                    clearLostSession("服务重启会话已丢失，未生成报告。")
                } else {
                    throw throwable
                }
            }
        }
    }

    fun completeSession(reason: String = "user_completed") {
        val id = _uiState.value.activeSession?.sessionId ?: return
        launchNetwork {
            try {
                val completion = repository.completeSession(id, reason)
                timerJob?.cancel()
                preferences.setActiveSessionId(null)
                _uiState.update {
                    it.copy(
                        activeSession = null,
                        monitoringInterrupted = false,
                        remainingSeconds = 0,
                        completion = completion,
                    )
                }
                loadHistory()
                loadBootstrap()
            } catch (throwable: retrofit2.HttpException) {
                if (throwable.code() == 404) {
                    clearLostSession("服务重启会话已丢失，未生成报告。")
                } else {
                    throw throwable
                }
            }
        }
    }

    fun acceptCaptureCompletion(completion: CompletionPayload) = viewModelScope.launch {
        timerJob?.cancel()
        preferences.setActiveSessionId(null)
        _uiState.update {
            it.copy(
                activeSession = null,
                monitoringInterrupted = false,
                remainingSeconds = 0,
                completion = completion,
            )
        }
        loadHistory()
        loadBootstrap()
    }

    fun abandonSession() {
        val id = _uiState.value.activeSession?.sessionId ?: return
        launchNetwork {
            try {
                repository.abandonSession(id)
                clearLostSession(error = null)
            } catch (throwable: retrofit2.HttpException) {
                if (throwable.code() == 404) {
                    clearLostSession(error = null)
                } else {
                    throw throwable
                }
            }
        }
    }

    fun clearInterruptedSession(message: String) = viewModelScope.launch {
        timerJob?.cancel()
        preferences.setActiveSessionId(null)
        _uiState.update {
            it.copy(
                activeSession = null,
                monitoringInterrupted = false,
                remainingSeconds = 0,
                error = message,
            )
        }
    }

    fun loadHistory() = launchNetwork {
        _uiState.update { it.copy(history = repository.history()) }
    }

    fun loadDen() = launchNetwork {
        denOperationMutex.withLock {
            applyDen(repository.den())
        }
    }

    fun updateDen(config: DenConfig) = launchNetwork {
        _uiState.update { it.copy(denSaving = true) }
        try {
            denOperationMutex.withLock {
                applyDen(repository.updateDen(config))
            }
        } finally {
            _uiState.update { it.copy(denSaving = false) }
        }
    }

    fun exchangeFurniture(itemId: String) = launchNetwork {
        _uiState.update { it.copy(exchangingItemId = itemId) }
        try {
            denOperationMutex.withLock {
                applyDen(repository.exchangeFurniture(itemId))
            }
        } finally {
            _uiState.update { it.copy(exchangingItemId = null) }
        }
    }

    fun setSoundEnabled(enabled: Boolean) = viewModelScope.launch {
        preferences.setSoundEnabled(enabled)
        _uiState.update { it.copy(soundEnabled = enabled) }
    }

    fun clearError() = _uiState.update { it.copy(error = null) }

    fun recheckAuthentication() = viewModelScope.launch {
        if (tokenVault.currentToken() == null) {
            clearLocalAuthentication("登录已过期，请重新登录。")
        }
    }

    private suspend fun restoreSession(localSessionId: String?) {
        if (localSessionId == null) return
        runCatching { repository.currentSession() }.fold(
            onSuccess = { session ->
                if (session == null || session.sessionId != localSessionId) {
                    preferences.setActiveSessionId(null)
                    _uiState.update {
                        it.copy(error = "本轮因服务重启未完整保存，已清除本地会话。")
                    }
                } else {
                    _uiState.update {
                        it.copy(activeSession = session, monitoringInterrupted = true)
                    }
                    startTimer(session)
                }
            },
            onFailure = { throwable ->
                if (AuthenticationFailure.requiresLogout(
                        (throwable as? retrofit2.HttpException)?.code(),
                    )
                ) {
                    clearLocalAuthentication("登录已过期，请重新登录。")
                } else {
                    _uiState.update { it.copy(error = throwable.userMessage()) }
                }
            },
        )
    }

    private fun startTimer(session: FocusSessionPayload) {
        timerJob?.cancel()
        val serverRemaining = session.remainingSeconds
        val calculated = SessionTimer.remainingSeconds(session.startedAt, session.durationMinutes)
        val initial = serverRemaining ?: calculated
        _uiState.update { it.copy(remainingSeconds = initial.coerceAtLeast(0)) }
        timerJob = viewModelScope.launch {
            while (_uiState.value.remainingSeconds > 0) {
                delay(1_000)
                _uiState.update { state ->
                    state.copy(remainingSeconds = (state.remainingSeconds - 1).coerceAtLeast(0))
                }
            }
        }
    }

    private fun launchNetwork(
        invalidateOnUnauthorized: Boolean = true,
        block: suspend () -> Unit,
    ): Job = viewModelScope.launch {
        beginNetworkCall()
        try {
            block()
        } catch (throwable: Throwable) {
            if (
                invalidateOnUnauthorized &&
                AuthenticationFailure.requiresLogout(
                    (throwable as? retrofit2.HttpException)?.code(),
                )
            ) {
                clearLocalAuthentication("登录已过期，请重新登录。")
            } else {
                _uiState.update { it.copy(error = throwable.userMessage()) }
            }
        } finally {
            finishNetworkCall()
        }
    }

    private fun beginNetworkCall() {
        pendingNetworkCalls += 1
        _uiState.update { it.copy(loading = true, error = null) }
    }

    private fun finishNetworkCall() {
        pendingNetworkCalls = (pendingNetworkCalls - 1).coerceAtLeast(0)
        _uiState.update { it.copy(loading = pendingNetworkCalls > 0) }
    }

    private suspend fun clearLocalAuthentication(error: String?) {
        timerJob?.cancel()
        tokenVault.clear()
        preferences.setActiveSessionId(null)
        _uiState.update {
            it.copy(
                authenticated = false,
                bootstrap = null,
                activeSession = null,
                monitoringInterrupted = false,
                remainingSeconds = 0,
                completion = null,
                history = emptyList(),
                den = null,
                denSaving = false,
                exchangingItemId = null,
                error = error,
            )
        }
    }

    private suspend fun clearLostSession(error: String?) {
        timerJob?.cancel()
        preferences.setActiveSessionId(null)
        _uiState.update {
            it.copy(
                activeSession = null,
                monitoringInterrupted = false,
                remainingSeconds = 0,
                completion = null,
                error = error,
            )
        }
    }

    private fun applyDen(payload: DenPayload) {
        _uiState.update { state ->
            state.copy(
                den = payload,
                bootstrap = state.bootstrap?.copy(points = payload.points),
            )
        }
    }

    private fun Throwable.userMessage(): String = when (this) {
        is java.net.UnknownHostException -> "无法解析服务器地址，请检查网络。"
        is java.net.ConnectException -> "服务器暂时无法连接，请稍后重试。"
        is java.net.SocketTimeoutException -> "服务器响应超时，请稍后重试。"
        is javax.net.ssl.SSLException ->
            "服务器 HTTPS 证书校验失败，请停止使用并联系维护者。"
        is retrofit2.HttpException -> ApiErrorParser.message(this)
            ?: when (code()) {
            401 -> "登录已过期，请重新登录。"
            409 -> "已有一轮专注正在进行。"
            else -> "服务器请求失败（${code()}）。"
        }
        is java.io.IOException -> "网络连接中断，请检查网络后重试。"
        is IllegalArgumentException -> message ?: "输入不符合要求。"
        else -> message ?: "发生未知错误。"
    }

    class Factory(
        private val repository: FocusRepository,
        private val preferences: AppPreferences,
        private val tokenVault: TokenVault,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(AppViewModel::class.java))
            return AppViewModel(repository, preferences, tokenVault) as T
        }
    }
}
