package com.focuscompass.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.media.projection.MediaProjectionConfig
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.lifecycle.ViewModel
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Cottage
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.annotation.ChecksSdkIntAtLeast
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.focuscompass.app.capture.CapturePhase
import com.focuscompass.app.capture.CaptureStateStore
import com.focuscompass.app.capture.FocusCaptureService
import com.focuscompass.app.capture.shouldForceDefaultDisplayCapture
import com.focuscompass.app.model.CompletionPayload
import com.focuscompass.app.model.FocusReport
import com.focuscompass.app.model.findHistoryItem
import com.focuscompass.app.ui.AppViewModel
import com.focuscompass.app.ui.SessionTimer
import com.focuscompass.app.ui.screens.AuthScreen
import com.focuscompass.app.ui.screens.DenScreen
import com.focuscompass.app.ui.screens.FocusSessionScreen
import com.focuscompass.app.ui.screens.GuideScreen
import com.focuscompass.app.ui.screens.HistoryScreen
import com.focuscompass.app.ui.screens.HistoryDetailScreen
import com.focuscompass.app.ui.screens.HomeScreen
import com.focuscompass.app.ui.screens.PrivacyScreen
import com.focuscompass.app.ui.screens.ReportScreen
import com.focuscompass.app.ui.screens.SettingsScreen
import com.focuscompass.app.ui.theme.FocusCompassTheme

class MainActivity : ComponentActivity() {
    private val viewModel: AppViewModel by viewModels {
        val app = application as FocusCompassApplication
        AppViewModel.Factory(app.repository, app.preferences, app.tokenVault)
    }
    private val projectionHandshake: ProjectionHandshakeViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            FocusCompassTheme {
                FocusCompassApp(viewModel, projectionHandshake)
            }
        }
    }
}

internal data class PendingStart(
    val goal: String,
    val durationMinutes: Int,
    val reminderMode: String,
)

internal data class StoredProjectionConsent<T>(
    val resultCode: Int,
    val data: T,
)

internal data class AuthorizedStart<T>(
    val request: PendingStart,
    val consent: StoredProjectionConsent<T>,
)

internal data class AuthorizedReauthorization<T>(
    val sessionId: String,
    val consent: StoredProjectionConsent<T>,
)

internal class SingleUseProjectionHandshake<T> {
    private var request: PendingStart? = null
    private var consent: StoredProjectionConsent<T>? = null

    @Synchronized
    fun prepare(request: PendingStart) {
        this.request = request
        consent = null
    }

    @Synchronized
    fun pending(): PendingStart? = request

    @Synchronized
    fun store(resultCode: Int, data: T): Boolean {
        if (request == null) return false
        consent = StoredProjectionConsent(resultCode, data)
        return true
    }

    @Synchronized
    fun take(): AuthorizedStart<T>? {
        val readyRequest = request ?: return null
        val readyConsent = consent ?: return null
        request = null
        consent = null
        return AuthorizedStart(readyRequest, readyConsent)
    }

    @Synchronized
    fun cancel() {
        request = null
        consent = null
    }

    @Synchronized
    fun hasConsent(): Boolean = consent != null
}

internal class SingleUseReauthorizationHandshake<T> {
    private var sessionId: String? = null
    private var consent: StoredProjectionConsent<T>? = null

    @Synchronized
    fun prepare(sessionId: String) {
        require(sessionId.isNotBlank()) { "sessionId must not be blank" }
        this.sessionId = sessionId
        consent = null
    }

    @Synchronized
    fun pendingSessionId(): String? = sessionId

    @Synchronized
    fun store(resultCode: Int, data: T): Boolean {
        if (sessionId == null) return false
        consent = StoredProjectionConsent(resultCode, data)
        return true
    }

    @Synchronized
    fun take(): AuthorizedReauthorization<T>? {
        val readySessionId = sessionId ?: return null
        val readyConsent = consent ?: return null
        sessionId = null
        consent = null
        return AuthorizedReauthorization(readySessionId, readyConsent)
    }

    @Synchronized
    fun cancel() {
        sessionId = null
        consent = null
    }
}

internal fun selectReauthorizationRemainingSeconds(
    hasStartedAt: Boolean,
    calculatedRemainingSeconds: Long,
    uiRemainingSeconds: Long,
    serverRemainingSeconds: Long?,
): Long? =
    if (hasStartedAt) {
        calculatedRemainingSeconds.takeIf { it > 0 }
    } else {
        sequenceOf(uiRemainingSeconds, serverRemainingSeconds ?: 0L)
            .firstOrNull { it > 0 }
    }

internal class ProjectionHandshakeViewModel : ViewModel() {
    private val handshake = SingleUseProjectionHandshake<Intent>()
    private val reauthorization = SingleUseReauthorizationHandshake<Intent>()

    fun prepare(request: PendingStart) = handshake.prepare(request)
    fun pending(): PendingStart? = handshake.pending()
    fun store(resultCode: Int, data: Intent): Boolean = handshake.store(resultCode, data)
    fun take(): AuthorizedStart<Intent>? = handshake.take()
    fun cancel() = handshake.cancel()
    fun hasConsent(): Boolean = handshake.hasConsent()
    fun prepareReauthorization(sessionId: String) = reauthorization.prepare(sessionId)
    fun pendingReauthorizationSessionId(): String? = reauthorization.pendingSessionId()
    fun storeReauthorization(resultCode: Int, data: Intent): Boolean =
        reauthorization.store(resultCode, data)
    fun takeReauthorization(): AuthorizedReauthorization<Intent>? = reauthorization.take()
    fun cancelReauthorization() = reauthorization.cancel()
}

@ChecksSdkIntAtLeast(api = 34)
private fun shouldUseDefaultDisplayCapture(): Boolean =
    shouldForceDefaultDisplayCapture(Build.VERSION.SDK_INT)

private object Routes {
    const val PRIVACY = "privacy"
    const val AUTH = "auth"
    val HOME = MainDestination.HOME.route
    val DEN = MainDestination.DEN.route
    const val FOCUS = "focus"
    const val REPORT = "report"
    const val GUIDE = "guide"
    val HISTORY = MainDestination.HISTORY.route
    const val HISTORY_DETAIL = HISTORY_DETAIL_ROUTE_PATTERN
    val SETTINGS = MainDestination.SETTINGS.route
}

@Composable
private fun MainBottomNavigation(
    selectedDestination: MainDestination?,
    onDestinationSelected: (MainDestination) -> Unit,
) {
    NavigationBar {
        MainDestination.entries.forEach { destination ->
            val label = when (destination) {
                MainDestination.HOME -> "首页"
                MainDestination.DEN -> "小窝"
                MainDestination.HISTORY -> "记录"
                MainDestination.SETTINGS -> "我的"
            }
            val icon = when (destination) {
                MainDestination.HOME -> Icons.Rounded.Home
                MainDestination.DEN -> Icons.Rounded.Cottage
                MainDestination.HISTORY -> Icons.Rounded.History
                MainDestination.SETTINGS -> Icons.Rounded.Person
            }
            NavigationBarItem(
                selected = selectedDestination == destination,
                onClick = { onDestinationSelected(destination) },
                icon = { Icon(icon, contentDescription = label) },
                label = { Text(label) },
            )
        }
    }
}

@Composable
private fun FocusCompassApp(
    viewModel: AppViewModel,
    projectionHandshake: ProjectionHandshakeViewModel,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val state by viewModel.uiState.collectAsState()
    val captureState by CaptureStateStore.state.collectAsState()
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val route = backStackEntry?.destination?.route
    val snackbarHostState = remember { SnackbarHostState() }
    val projectionManager = remember {
        context.getSystemService(MediaProjectionManager::class.java)
    }
    var permissionDenied by remember { mutableStateOf(false) }
    var handledCaptureCompletion by remember { mutableStateOf<String?>(null) }
    var handledLostSession by remember { mutableStateOf<String?>(null) }

    fun createWholeDisplayCaptureIntent(): Intent =
        if (shouldUseDefaultDisplayCapture()) {
            projectionManager.createScreenCaptureIntent(
                MediaProjectionConfig.createConfigForDefaultDisplay(),
            )
        } else {
            projectionManager.createScreenCaptureIntent()
        }

    val projectionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val request = projectionHandshake.pending()
        val data = result.data
        if (result.resultCode == Activity.RESULT_OK && data != null && request != null) {
            projectionHandshake.store(result.resultCode, data)
            viewModel.startSession(request.goal, request.durationMinutes, request.reminderMode)
        } else {
            projectionHandshake.cancel()
        }
    }
    val reauthorizationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val expectedSessionId = projectionHandshake.pendingReauthorizationSessionId()
        val data = result.data
        if (
            result.resultCode == Activity.RESULT_OK &&
            data != null &&
            expectedSessionId != null &&
            projectionHandshake.storeReauthorization(result.resultCode, data)
        ) {
            val authorized = projectionHandshake.takeReauthorization()
            val session = state.activeSession
            if (authorized != null && session?.sessionId == authorized.sessionId) {
                val captureIsActive =
                    captureState.phase == CapturePhase.CAPTURING &&
                        captureState.sessionId == authorized.sessionId
                if (captureIsActive) {
                    FocusCaptureService.reauthorize(
                        context = context,
                        resultCode = authorized.consent.resultCode,
                        resultData = authorized.consent.data,
                        sessionId = authorized.sessionId,
                    )
                } else {
                    val calculatedRemaining = SessionTimer.remainingSeconds(
                        session.startedAt,
                        session.durationMinutes,
                    )
                    val remainingSeconds = selectReauthorizationRemainingSeconds(
                        hasStartedAt = session.startedAt != null,
                        calculatedRemainingSeconds = calculatedRemaining,
                        uiRemainingSeconds = state.remainingSeconds,
                        serverRemainingSeconds = session.remainingSeconds,
                    )
                    if (remainingSeconds == null) {
                        viewModel.completeSession("timer_finished")
                    } else {
                        val policy = session.capturePolicy ?: state.bootstrap?.capturePolicy
                        FocusCaptureService.start(
                            context = context,
                            resultCode = authorized.consent.resultCode,
                            resultData = authorized.consent.data,
                            sessionId = authorized.sessionId,
                            durationSeconds = remainingSeconds,
                            soundEnabled = state.soundEnabled,
                            firstCaptureImmediate = policy?.initialCaptureImmediately ?: true,
                            intervalMillis = (policy?.intervalSeconds ?: 20) * 1_000L,
                            requestTimeoutMillis = (policy?.requestTimeoutSeconds ?: 18) * 1_000L,
                            maxImageDimension = policy?.maxLongEdgePx ?: 1_024,
                            jpegQuality = policy?.jpegQuality ?: 72,
                        )
                    }
                }
                if (route != Routes.FOCUS) {
                    navController.navigate(Routes.FOCUS) { launchSingleTop = true }
                }
            }
        } else {
            projectionHandshake.cancelReauthorization()
        }
    }
    val notificationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) projectionLauncher.launch(createWholeDisplayCaptureIntent())
        else {
            projectionHandshake.cancel()
            permissionDenied = true
        }
    }

    fun requestStart(goal: String, durationMinutes: Int, reminderMode: String) {
        projectionHandshake.prepare(PendingStart(goal, durationMinutes, reminderMode))
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            projectionLauncher.launch(createWholeDisplayCaptureIntent())
        }
    }

    fun requestReauthorization() {
        val activeSessionId = state.activeSession?.sessionId ?: return
        if (projectionHandshake.pendingReauthorizationSessionId() != null) return
        projectionHandshake.prepareReauthorization(activeSessionId)
        reauthorizationLauncher.launch(createWholeDisplayCaptureIntent())
    }

    LaunchedEffect(state.ready, state.privacyAccepted, state.authenticated, route) {
        if (!state.ready) return@LaunchedEffect
        val target = when {
            !state.privacyAccepted -> Routes.PRIVACY
            !state.authenticated -> Routes.AUTH
            else -> Routes.HOME
        }
        val needsRedirect = when {
            route == null -> true
            !state.privacyAccepted -> route != Routes.PRIVACY
            !state.authenticated -> route != Routes.AUTH
            else -> route == Routes.PRIVACY || route == Routes.AUTH
        }
        if (needsRedirect) {
            val currentRoute = route
            navController.navigate(target) {
                when {
                    target != Routes.HOME &&
                        currentRoute != null &&
                        currentRoute != Routes.PRIVACY &&
                        currentRoute != Routes.AUTH -> {
                        popUpTo(Routes.HOME) { inclusive = true }
                    }
                    currentRoute != null -> {
                        popUpTo(currentRoute) { inclusive = true }
                    }
                }
                launchSingleTop = true
            }
        }
    }

    LaunchedEffect(state.activeSession?.sessionId) {
        val session = state.activeSession ?: return@LaunchedEffect
        val authorizedStart = projectionHandshake.take()
        if (authorizedStart != null) {
            val calculatedRemaining = SessionTimer.remainingSeconds(
                session.startedAt,
                session.durationMinutes,
            )
            val remainingSeconds = (session.remainingSeconds ?: calculatedRemaining)
                .takeIf { it > 0 }
                ?: if (session.startedAt == null) {
                    (authorizedStart.request.durationMinutes.takeIf { it > 0 }
                        ?: session.durationMinutes
                        ?: 25) * 60L
                } else {
                    1L
                }
            val policy = session.capturePolicy ?: state.bootstrap?.capturePolicy
            FocusCaptureService.start(
                context = context,
                resultCode = authorizedStart.consent.resultCode,
                resultData = authorizedStart.consent.data,
                sessionId = session.sessionId,
                durationSeconds = remainingSeconds,
                soundEnabled = state.soundEnabled,
                firstCaptureImmediate = policy?.initialCaptureImmediately ?: true,
                intervalMillis = (policy?.intervalSeconds ?: 20) * 1_000L,
                requestTimeoutMillis = (policy?.requestTimeoutSeconds ?: 18) * 1_000L,
                maxImageDimension = policy?.maxLongEdgePx ?: 1_024,
                jpegQuality = policy?.jpegQuality ?: 72,
            )
        }
        if (route != Routes.FOCUS) navController.navigate(Routes.FOCUS) { launchSingleTop = true }
    }

    LaunchedEffect(state.loading, state.activeSession?.sessionId, state.error) {
        if (
            !state.loading &&
            state.activeSession == null &&
            state.error != null &&
            projectionHandshake.hasConsent()
        ) {
            projectionHandshake.cancel()
        }
    }

    LaunchedEffect(
        captureState.phase,
        captureState.completion?.sessionId,
        captureState.skippedFrames,
    ) {
        val result = captureState.completion
        if (
            captureState.phase == CapturePhase.COMPLETED &&
            result != null &&
            handledCaptureCompletion != result.sessionId
        ) {
            handledCaptureCompletion = result.sessionId
            viewModel.acceptCaptureCompletion(
                CompletionPayload(
                    sessionId = result.sessionId,
                    pointsEarned = result.pointsEarned,
                    report = FocusReport(
                        focusScore = result.focusScore,
                        effectiveCoverage = result.effectiveCoverage,
                        reliable = result.reliable,
                        summary = result.message,
                    ),
                ),
            )
        }
        if (
            captureState.phase == CapturePhase.ERROR ||
            (captureState.phase == CapturePhase.INTERRUPTED && !captureState.sessionLost) ||
            captureState.skippedFrames > 0
        ) {
            viewModel.recheckAuthentication()
        }
    }

    LaunchedEffect(captureState.sessionLost, captureState.sessionId) {
        val lostSessionId = captureState.sessionId
        if (captureState.sessionLost && lostSessionId != null && handledLostSession != lostSessionId) {
            handledLostSession = lostSessionId
            viewModel.clearInterruptedSession(
                captureState.message ?: "服务重启，本轮专注会话已丢失，未生成报告。",
            )
            navController.navigate(Routes.HOME) {
                popUpTo(Routes.HOME) { inclusive = true }
                launchSingleTop = true
            }
            CaptureStateStore.reset()
        }
    }

    LaunchedEffect(state.completion?.sessionId) {
        if (state.completion != null && route != Routes.REPORT) {
            navController.navigate(Routes.REPORT) { launchSingleTop = true }
        }
    }

    LaunchedEffect(state.activeSession?.sessionId, state.loading, state.completion?.sessionId) {
        if (
            route == Routes.FOCUS &&
            state.activeSession == null &&
            state.completion == null &&
            !state.loading
        ) {
            navController.navigate(Routes.HOME) {
                popUpTo(Routes.HOME) { inclusive = true }
            }
        }
    }

    LaunchedEffect(state.error) {
        state.error?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearError()
        }
    }

    LaunchedEffect(permissionDenied) {
        if (permissionDenied) {
            val result = snackbarHostState.showSnackbar(
                message = "必须允许通知，整屏共享期间才能持续显示运行状态。",
                actionLabel = "打开设置",
            )
            if (result == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                context.startActivity(
                    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                        .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
                )
            }
            permissionDenied = false
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (shouldShowBottomNavigation(route, state.authenticated)) {
                MainBottomNavigation(
                    selectedDestination = selectedMainDestination(route),
                    onDestinationSelected = { destination ->
                        if (destination == MainDestination.HISTORY) {
                            viewModel.loadHistory()
                        }
                        navController.navigate(destination.route) {
                            popUpTo(Routes.HOME) {
                                saveState = true
                            }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                )
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Routes.PRIVACY,
            modifier = Modifier.fillMaxSize().padding(padding),
        ) {
            composable(Routes.PRIVACY) {
                PrivacyScreen {
                    viewModel.acceptPrivacy()
                    navController.navigate(Routes.AUTH) {
                        popUpTo(Routes.PRIVACY) { inclusive = true }
                    }
                }
            }
            composable(Routes.AUTH) {
                AuthScreen(state.loading, viewModel::authenticate)
            }
            composable(Routes.HOME) {
                HomeScreen(
                    username = state.bootstrap?.username,
                    points = state.bootstrap?.points ?: 0,
                    recommendedDuration = state.bootstrap?.recommendedDurationMinutes,
                    serverHost = remember {
                        runCatching { java.net.URI(BuildConfig.FOCUS_API_BASE_URL).host }
                            .getOrNull()
                            ?: BuildConfig.FOCUS_API_BASE_URL
                    },
                    serverConfigured = BuildConfig.FOCUS_SERVER_CONFIGURED,
                    loading = state.loading,
                    onStart = ::requestStart,
                )
            }
            composable(Routes.DEN) {
                LaunchedEffect(Unit) {
                    viewModel.loadDen().join()
                }
                DenScreen(
                    den = state.den,
                    loading = state.loading,
                    saving = state.denSaving,
                    exchangingItemId = state.exchangingItemId,
                    onRefresh = viewModel::loadDen,
                    onConfigChanged = viewModel::updateDen,
                    onExchange = viewModel::exchangeFurniture,
                )
            }
            composable(Routes.FOCUS) {
                val captureSessionMatches =
                    captureState.sessionId == state.activeSession?.sessionId
                val captureRunning = captureSessionMatches &&
                    captureState.phase in setOf(CapturePhase.CAPTURING, CapturePhase.COMPLETING)
                val captureCompleting =
                    captureSessionMatches && captureState.phase == CapturePhase.COMPLETING
                FocusSessionScreen(
                    session = state.activeSession,
                    remainingSeconds = if (captureRunning) {
                        captureState.remainingSeconds
                    } else {
                        state.remainingSeconds
                    },
                    liveStatus = captureState.classification.takeIf { captureRunning },
                    liveSummary = captureState.rollingSummary.takeIf { captureRunning },
                    monitoringInterrupted = state.monitoringInterrupted ||
                        captureSessionMatches && captureState.phase in
                        setOf(CapturePhase.INTERRUPTED, CapturePhase.ERROR),
                    captureHealthWarning = captureState.captureHealthWarning,
                    reauthorizationAvailable =
                        captureState.captureHealthWarning != null ||
                            captureState.phase in setOf(CapturePhase.IDLE, CapturePhase.ERROR),
                    isCompleting = captureCompleting,
                    onRefresh = viewModel::refreshSession,
                    onReauthorize = ::requestReauthorization,
                    onComplete = {
                        if (captureRunning) {
                            context.startService(
                                Intent(context, FocusCaptureService::class.java).apply {
                                    action = FocusCaptureService.ACTION_COMPLETE
                                    putExtra(
                                        FocusCaptureService.EXTRA_COMPLETE_REASON,
                                        "user_completed",
                                    )
                                },
                            )
                        } else {
                            viewModel.completeSession("monitoring_interrupted")
                        }
                    },
                    onAbandon = {
                        val activeSessionId = state.activeSession?.sessionId
                        val captureIsActive =
                            captureState.phase == CapturePhase.CAPTURING &&
                                captureState.sessionId == activeSessionId
                        if (captureIsActive && activeSessionId != null) {
                            context.startService(
                                Intent(context, FocusCaptureService::class.java).apply {
                                    action = FocusCaptureService.ACTION_ABANDON
                                    putExtra(FocusCaptureService.EXTRA_SESSION_ID, activeSessionId)
                                },
                            )
                        } else {
                            CaptureStateStore.reset()
                        }
                        viewModel.abandonSession()
                        navController.navigate(Routes.HOME) {
                            popUpTo(Routes.HOME) { inclusive = true }
                        }
                    },
                )
            }
            composable(Routes.REPORT) {
                ReportScreen(
                    completion = state.completion,
                    onHome = {
                        CaptureStateStore.reset()
                        navController.navigate(Routes.HOME) {
                            popUpTo(Routes.HOME) { inclusive = true }
                        }
                    }
                )
            }
            composable(Routes.HISTORY) {
                HistoryScreen(
                    history = state.history,
                    onOpenHistoryItem = { item ->
                        navController.navigate(historyDetailRoute(item.sessionId)) {
                            launchSingleTop = true
                        }
                    },
                )
            }
            composable(Routes.HISTORY_DETAIL) { entry ->
                val sessionId = entry.arguments?.getString("sessionId")
                val historyItem = findHistoryItem(state.history, sessionId)
                var detailLoading by remember(sessionId) {
                    mutableStateOf(historyItem == null)
                }
                LaunchedEffect(sessionId) {
                    if (historyItem == null) {
                        viewModel.loadHistory().join()
                    }
                    detailLoading = false
                }
                HistoryDetailScreen(
                    item = findHistoryItem(state.history, sessionId),
                    loading = detailLoading,
                    onBack = {
                        if (!navController.popBackStack()) {
                            navController.navigate(Routes.HISTORY) {
                                launchSingleTop = true
                            }
                        }
                    },
                )
            }
            composable(Routes.SETTINGS) {
                SettingsScreen(
                    username = state.bootstrap?.username,
                    points = state.bootstrap?.points ?: 0,
                    baseUrl = BuildConfig.FOCUS_API_BASE_URL,
                    appVersion = BuildConfig.VERSION_NAME,
                    serverConfigured = BuildConfig.FOCUS_SERVER_CONFIGURED,
                    soundEnabled = state.soundEnabled,
                    onSoundChanged = viewModel::setSoundEnabled,
                    onOpenGuide = {
                        navController.navigate(Routes.GUIDE) { launchSingleTop = true }
                    },
                    onLogout = viewModel::logout,
                )
            }
            composable(Routes.GUIDE) {
                GuideScreen(
                    onBack = {
                        if (!navController.popBackStack()) {
                            navController.navigate(Routes.SETTINGS) { launchSingleTop = true }
                        }
                    },
                )
            }
        }
    }
}
