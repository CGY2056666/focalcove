package com.focuscompass.app.capture

import android.app.Activity
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import android.util.DisplayMetrics
import android.view.WindowManager
import androidx.work.Data
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.focuscompass.app.data.AppPreferences
import com.focuscompass.app.worker.CompleteSessionWorker
import com.focuscompass.app.worker.CompletionFailureAction
import com.focuscompass.app.worker.classifyCompletionFailure
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import retrofit2.HttpException

class FocusCaptureService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val completionStarted = AtomicBoolean(false)
    private val suppressCompletion = AtomicBoolean(false)
    private val projectionLock = Any()
    private val deliveredAlertIds = ConcurrentHashMap.newKeySet<String>()
    private val nearBlackDetector = NearBlackFrameDetector()
    private val nearBlackTracker = NearBlackFrameTracker()
    private var policy = CapturePolicy()
    private var samplingGate = FrameSamplingGate(
        policy.intervalMillis,
        policy.firstCaptureImmediate,
    )

    private lateinit var captureThread: HandlerThread
    private lateinit var captureHandler: Handler
    private var mediaProjection: MediaProjection? = null
    private var projectionCallback: MediaProjection.Callback? = null
    private val projectionGeneration = AtomicLong(0)
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var displayManager: DisplayManager? = null
    private var sessionId: String? = null
    private var durationSeconds: Long = 0
    private var startedAtElapsedMillis: Long = 0
    private var timerJob: Job? = null
    private var uploadJob: Job? = null
    private var completionJob: Job? = null
    private var soundEnabled: Boolean = true

    private val displayListener = object : DisplayManager.DisplayListener {
        override fun onDisplayAdded(displayId: Int) = Unit
        override fun onDisplayRemoved(displayId: Int) = Unit
        override fun onDisplayChanged(displayId: Int) {
            if (displayId == android.view.Display.DEFAULT_DISPLAY) {
                resizeCaptureSurface(currentGeometry())
            }
        }
    }

    private fun newProjectionCallback(generation: Long): MediaProjection.Callback =
        object : MediaProjection.Callback() {
            override fun onCapturedContentResize(width: Int, height: Int) {
                if (width <= 0 || height <= 0) return
                resizeCaptureSurface(
                    ScreenGeometry(width, height, resources.displayMetrics.densityDpi),
                    expectedGeneration = generation,
                )
            }

            override fun onStop() {
                synchronized(projectionLock) {
                    if (generation != projectionGeneration.get()) return
                    if (!suppressCompletion.get()) {
                        finishSession("projection_stopped", projectionAlreadyStopped = true)
                    }
                }
            }
        }

    override fun onCreate() {
        super.onCreate()
        CaptureNotifications.createChannels(this)
        captureThread = HandlerThread("focus-capture").apply { start() }
        captureHandler = Handler(captureThread.looper)
        displayManager = getSystemService(DisplayManager::class.java).also {
            it.registerDisplayListener(displayListener, captureHandler)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_COMPLETE -> {
                finishSession(intent.getStringExtra(EXTRA_COMPLETE_REASON) ?: "manual")
                return START_NOT_STICKY
            }
            ACTION_ABANDON -> {
                abandonCapture(intent.getStringExtra(EXTRA_SESSION_ID))
                return START_NOT_STICKY
            }
            ACTION_START -> startFromConsent(intent)
            ACTION_REAUTHORIZE -> reauthorizeFromConsent(intent)
            else -> {
                CaptureStateStore.interrupted("采集服务被系统重建，请重新开始本轮")
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun startFromConsent(intent: Intent) {
        // Android 10+ requires foreground promotion before MediaProjection is obtained.
        startForeground(
            CaptureNotifications.ONGOING_NOTIFICATION_ID,
            CaptureNotifications.ongoing(this),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION,
        )

        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val resultData = projectionIntent(intent)
        val newSessionId = intent.getStringExtra(EXTRA_SESSION_ID)
        val newDuration = intent.getLongExtra(EXTRA_DURATION_SECONDS, 0L)
        if (resultCode != Activity.RESULT_OK || resultData == null || newSessionId.isNullOrBlank() || newDuration <= 0) {
            CaptureStateStore.error("缺少有效的屏幕录制授权或专注会话")
            stopSelf()
            return
        }
        if (mediaProjection != null) return

        sessionId = newSessionId
        durationSeconds = newDuration
        soundEnabled = intent.getBooleanExtra(EXTRA_SOUND_ENABLED, true)
        policy = CapturePolicy.sanitized(
            firstCaptureImmediate = intent.getBooleanExtra(EXTRA_FIRST_CAPTURE_IMMEDIATE, true),
            intervalMillis = intent.getLongExtra(EXTRA_INTERVAL_MILLIS, 20_000L),
            requestTimeoutMillis = intent.getLongExtra(EXTRA_REQUEST_TIMEOUT_MILLIS, 18_000L),
            maxImageDimension = intent.getIntExtra(EXTRA_MAX_IMAGE_DIMENSION, 1_024),
            jpegQuality = intent.getIntExtra(EXTRA_JPEG_QUALITY, 72),
        )
        samplingGate = FrameSamplingGate(
            policy.intervalMillis,
            policy.firstCaptureImmediate,
        )
        startedAtElapsedMillis = SystemClock.elapsedRealtime()
        CaptureStateStore.started(newSessionId, newDuration)
        CaptureNotifications.clearCaptureProblem(this)

        val projection = projectionFromConsent(resultCode, resultData) ?: run {
            CaptureStateStore.error("屏幕录制授权已失效，请重新授权")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }
        if (!installProjection(projection)) {
            CaptureStateStore.error("无法启动整屏共享，请重新授权")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }
        startTimer()
    }

    private fun reauthorizeFromConsent(intent: Intent) {
        val requestedSessionId = intent.getStringExtra(EXTRA_SESSION_ID)
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val resultData = projectionIntent(intent)
        if (sessionId == null) {
            CaptureStateStore.captureProblem("采集服务已经停止，请从专注页重新授权。")
            stopSelf()
            return
        }
        if (
            requestedSessionId.isNullOrBlank() ||
            requestedSessionId != sessionId ||
            resultCode != Activity.RESULT_OK ||
            resultData == null ||
            completionStarted.get()
        ) {
            CaptureStateStore.captureProblem("重新授权未生效，请确认本轮仍在进行后重试。")
            return
        }

        // Invalidate the old callback before stopping its projection. A delayed onStop() from the
        // old generation must never settle the session that is being reauthorized.
        releaseProjectionResources()
        if (completionStarted.get()) return
        val replacement = projectionFromConsent(resultCode, resultData)
        if (replacement == null) {
            CaptureStateStore.captureProblem("屏幕录制授权已失效，请重新授权。")
            return
        }
        if (!installProjection(replacement)) {
            CaptureStateStore.captureProblem("无法恢复整屏共享，请重新授权或结束本轮。")
            return
        }
        nearBlackTracker.reset()
        CaptureStateStore.captureRecovered("整屏共享已重新授权，正在等待下一次画面确认。")
        CaptureNotifications.clearCaptureProblem(this)
    }

    private fun projectionFromConsent(resultCode: Int, resultData: Intent): MediaProjection? =
        getSystemService(MediaProjectionManager::class.java)
            .getMediaProjection(resultCode, resultData)

    private fun installProjection(projection: MediaProjection): Boolean =
        synchronized(projectionLock) {
            val generation = projectionGeneration.incrementAndGet()
            val callback = newProjectionCallback(generation)
            mediaProjection = projection
            projectionCallback = callback
            runCatching {
                projection.registerCallback(callback, captureHandler)
                createVirtualDisplayOnce(projection)
            }.fold(
                onSuccess = { true },
                onFailure = {
                    releaseProjectionResources()
                    false
                },
            )
        }

    private fun createVirtualDisplayOnce(projection: MediaProjection) {
        check(virtualDisplay == null) { "A projection consent token may create only one VirtualDisplay" }
        val geometry = currentGeometry()
        val reader = newImageReader(geometry.width, geometry.height)
        imageReader = reader
        virtualDisplay = projection.createVirtualDisplay(
            "FocusCompassCapture",
            geometry.width,
            geometry.height,
            geometry.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface,
            null,
            captureHandler,
        )
    }

    private fun resizeCaptureSurface(
        geometry: ScreenGeometry,
        expectedGeneration: Long? = null,
    ) {
        synchronized(projectionLock) {
            if (
                expectedGeneration != null &&
                expectedGeneration != projectionGeneration.get()
            ) {
                return
            }
            if (completionStarted.get()) return
            val display = virtualDisplay ?: return
            val oldReader = imageReader ?: return
            if (geometry.width == oldReader.width && geometry.height == oldReader.height) return

            val replacement = newImageReader(geometry.width, geometry.height)
            // Do not create a second VirtualDisplay for the same Android 14+ consent token.
            val resized = runCatching {
                display.resize(geometry.width, geometry.height, geometry.densityDpi)
                display.setSurface(replacement.surface)
            }.isSuccess
            if (!resized) {
                replacement.setOnImageAvailableListener(null, null)
                replacement.close()
                return
            }
            imageReader = replacement
            oldReader.setOnImageAvailableListener(null, null)
            oldReader.close()
        }
    }

    private fun newImageReader(
        width: Int,
        height: Int,
        generation: Long = projectionGeneration.get(),
    ): ImageReader =
        ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2).also { reader ->
            reader.setOnImageAvailableListener({ source ->
                val isActive = synchronized(projectionLock) {
                    generation == projectionGeneration.get() && source === imageReader
                }
                if (isActive) {
                    onImageAvailable(source, generation)
                } else {
                    runCatching { source.acquireLatestImage()?.close() }
                }
            }, captureHandler)
        }

    private fun onImageAvailable(reader: ImageReader, generation: Long) {
        val image = runCatching { reader.acquireLatestImage() }.getOrNull() ?: return
        if (!samplingGate.tryAcquire(SystemClock.elapsedRealtime())) {
            image.close()
            return
        }

        val prepared = try {
            try {
                prepareFrame(image)
            } finally {
                image.close()
            }
        } catch (_: Throwable) {
            samplingGate.release()
            CaptureStateStore.skipped("当前画面无法读取")
            return
        }
        val isNearBlack = prepared.inspection.verdict == NearBlackVerdict.NEAR_BLACK
        synchronized(projectionLock) {
            if (generation != projectionGeneration.get() || completionStarted.get()) {
                prepared.jpeg?.fill(0)
                samplingGate.release()
                return
            }
            val signal = nearBlackTracker.observe(prepared.inspection.verdict)
            if (isNearBlack) {
                CaptureStateStore.nearBlack(signal)
                if (signal.event == NearBlackSignalEvent.CONFIRMED) {
                    CaptureNotifications.showCaptureProblem(this, soundEnabled)
                }
            } else if (signal.event == NearBlackSignalEvent.RECOVERED) {
                CaptureStateStore.captureRecovered()
                CaptureNotifications.clearCaptureProblem(this)
            }
        }
        if (isNearBlack) {
            samplingGate.release()
            return
        }
        val jpeg = prepared.jpeg ?: run {
            samplingGate.release()
            CaptureStateStore.skipped("当前画面样本不足，本采集点已跳过")
            return
        }
        upload(jpeg, generation)
    }

    private fun upload(jpeg: ByteArray, generation: Long) {
        val activeSessionId = sessionId
        if (
            activeSessionId == null ||
            completionStarted.get() ||
            generation != projectionGeneration.get()
        ) {
            jpeg.fill(0)
            samplingGate.release()
            return
        }
        val capturedAt = System.currentTimeMillis() / 1_000.0
        val frameId = UUID.randomUUID().toString()
        uploadJob = serviceScope.launch {
            try {
                val result = withTimeout(policy.requestTimeoutMillis) {
                    withContext(Dispatchers.IO) {
                        CaptureRuntime.requireBackend(applicationContext).uploadFrame(
                            sessionId = activeSessionId,
                            jpeg = jpeg,
                            frameId = frameId,
                            capturedAt = capturedAt,
                        )
                    }
                }
                CaptureStateStore.uploaded(result)
                result.alertEvent?.let(::deliverAlertOnce)
            } catch (_: TimeoutCancellationException) {
                CaptureStateStore.skipped("上传超时，本采集点已跳过")
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (throwable: Throwable) {
                when (classifyFrameUploadFailure((throwable as? HttpException)?.code())) {
                    FrameUploadFailureAction.SESSION_LOST -> terminateWithoutCompletion(
                        message = "服务重启，本轮专注会话已丢失，未生成报告。",
                        sessionLost = true,
                    )
                    FrameUploadFailureAction.AUTH_EXPIRED -> terminateWithoutCompletion(
                        message = "登录已过期，采集已停止。",
                    )
                    FrameUploadFailureAction.FORBIDDEN -> terminateWithoutCompletion(
                        message = "无权上传此专注会话，采集已停止。",
                    )
                    FrameUploadFailureAction.SKIP_FRAME ->
                        CaptureStateStore.skipped("上传失败，本采集点已跳过")
                }
            } finally {
                jpeg.fill(0)
                samplingGate.release()
            }
        }
    }

    private fun deliverAlertOnce(event: CaptureAlertEvent) {
        if (deliveredAlertIds.add(event.eventId)) {
            CaptureNotifications.showAlert(this, event, soundEnabled)
        }
    }

    private fun startTimer() {
        timerJob = serviceScope.launch {
            while (!completionStarted.get()) {
                val elapsedSeconds = (SystemClock.elapsedRealtime() - startedAtElapsedMillis) / 1_000L
                val remaining = (durationSeconds - elapsedSeconds).coerceAtLeast(0)
                CaptureStateStore.tick(remaining)
                if (remaining == 0L) {
                    finishSession("timer_finished")
                    break
                }
                delay(1_000L)
            }
        }
    }

    private fun finishSession(reason: String, projectionAlreadyStopped: Boolean = false) {
        if (suppressCompletion.get()) return
        if (!completionStarted.compareAndSet(false, true)) return
        timerJob?.cancel()
        CaptureStateStore.completing(reason)
        CaptureNotifications.clearCaptureProblem(this)
        releaseProjectionResources(projectionAlreadyStopped)
        val activeSessionId = sessionId
        if (activeSessionId == null) {
            CaptureStateStore.interrupted("专注会话已不存在")
            stopSelf()
            return
        }

        completionJob = serviceScope.launch {
            try {
                uploadJob?.cancelAndJoin()
                val result = withContext(Dispatchers.IO) {
                    CaptureRuntime.requireBackend(applicationContext).completeSession(activeSessionId, reason)
                }
                AppPreferences(applicationContext).setActiveSessionId(null)
                CaptureStateStore.completed(result)
            } catch (cancelled: CancellationException) {
                if (!suppressCompletion.get()) throw cancelled
            } catch (throwable: Throwable) {
                if (suppressCompletion.get()) return@launch
                when (
                    classifyCompletionFailure(
                        httpStatus = (throwable as? HttpException)?.code(),
                        isNetworkFailure = throwable is IOException,
                    )
                ) {
                    CompletionFailureAction.RETRY -> {
                        enqueueCompletion(activeSessionId, reason)
                        CaptureStateStore.interrupted("结算已进入后台重试；截图不会被缓存或补传")
                    }
                    CompletionFailureAction.AUTH_EXPIRED ->
                        CaptureStateStore.interrupted("登录已过期，无法继续结算")
                    CompletionFailureAction.FORBIDDEN ->
                        CaptureStateStore.interrupted("无权结算此专注会话")
                    CompletionFailureAction.NOT_FOUND ->
                        CaptureStateStore.interrupted("专注会话已不存在，无法结算")
                    CompletionFailureAction.FAIL ->
                        CaptureStateStore.interrupted("结算失败且不可重试")
                }
            } finally {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun abandonCapture(requestedSessionId: String?) {
        val activeSessionId = sessionId
        if (activeSessionId == null || requestedSessionId != activeSessionId) return
        suppressCompletion.set(true)
        completionStarted.set(true)

        timerJob?.cancel()
        uploadJob?.cancel()
        completionJob?.cancel()
        CaptureNotifications.clearCaptureProblem(this)
        releaseProjectionResources()
        CaptureStateStore.reset()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun terminateWithoutCompletion(message: String, sessionLost: Boolean = false) {
        suppressCompletion.set(true)
        completionStarted.set(true)
        timerJob?.cancel()
        completionJob?.cancel()
        CaptureNotifications.clearCaptureProblem(this)
        releaseProjectionResources()
        CaptureStateStore.interrupted(message, sessionLost = sessionLost)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun enqueueCompletion(sessionId: String, reason: String) {
        val input = Data.Builder()
            .putString(CompleteSessionWorker.KEY_SESSION_ID, sessionId)
            .putString(CompleteSessionWorker.KEY_REASON, reason)
            .build()
        val request = OneTimeWorkRequestBuilder<CompleteSessionWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(input)
            .build()
        WorkManager.getInstance(applicationContext).enqueueUniqueWork(
            "complete_$sessionId",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    private fun releaseProjectionResources(projectionAlreadyStopped: Boolean = false) {
        var reader: ImageReader? = null
        var display: VirtualDisplay? = null
        var projection: MediaProjection? = null
        var callback: MediaProjection.Callback? = null
        synchronized(projectionLock) {
            projectionGeneration.incrementAndGet()
            reader = imageReader
            imageReader = null
            display = virtualDisplay
            virtualDisplay = null
            projection = mediaProjection
            mediaProjection = null
            callback = projectionCallback
            projectionCallback = null
        }

        runCatching { reader?.setOnImageAvailableListener(null, null) }
        runCatching { reader?.close() }
        runCatching { display?.release() }
        if (projection != null && callback != null) {
            runCatching { projection.unregisterCallback(callback) }
        }
        if (!projectionAlreadyStopped) runCatching { projection?.stop() }
    }

    private fun prepareFrame(image: Image): PreparedFrame {
        val plane = image.planes.first()
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val bitmapWidth = rowStride / pixelStride
        var padded: Bitmap? = null
        var cropped: Bitmap? = null
        var scaled: Bitmap? = null
        try {
            val paddedBitmap =
                Bitmap.createBitmap(bitmapWidth, image.height, Bitmap.Config.ARGB_8888)
            padded = paddedBitmap
            plane.buffer.rewind()
            paddedBitmap.copyPixelsFromBuffer(plane.buffer)

            val croppedBitmap =
                Bitmap.createBitmap(paddedBitmap, 0, 0, image.width, image.height)
            cropped = croppedBitmap
            val target = scaleToFit(
                croppedBitmap.width,
                croppedBitmap.height,
                policy.maxImageDimension,
            )
            val scaledBitmap =
                if (target.width == croppedBitmap.width && target.height == croppedBitmap.height) {
                    croppedBitmap
                } else {
                    Bitmap.createScaledBitmap(
                        croppedBitmap,
                        target.width,
                        target.height,
                        true,
                    )
                }
            scaled = scaledBitmap
            val sample = sampleCenterPixels(scaledBitmap)
            val inspection = nearBlackDetector.inspectArgb(
                argbPixels = sample,
                sampleWidth = FRAME_HEALTH_SAMPLE_SIZE,
                sampleHeight = FRAME_HEALTH_SAMPLE_SIZE,
            )
            if (inspection.verdict == NearBlackVerdict.NEAR_BLACK) {
                return PreparedFrame(jpeg = null, inspection = inspection)
            }
            val jpeg = ByteArrayOutputStream().use { output ->
                check(scaledBitmap.compress(Bitmap.CompressFormat.JPEG, policy.jpegQuality, output))
                output.toByteArray()
            }
            return PreparedFrame(jpeg = jpeg, inspection = inspection)
        } finally {
            scaled?.takeIf { !it.isRecycled }?.recycle()
            cropped
                ?.takeIf { it !== scaled && !it.isRecycled }
                ?.recycle()
            padded
                ?.takeIf { it !== cropped && it !== scaled && !it.isRecycled }
                ?.recycle()
        }
    }

    private fun sampleCenterPixels(bitmap: Bitmap): IntArray {
        val innerWidth = (bitmap.width * 8 / 10).coerceAtLeast(1)
        val innerHeight = (bitmap.height * 8 / 10).coerceAtLeast(1)
        val left = (bitmap.width - innerWidth) / 2
        val top = (bitmap.height - innerHeight) / 2
        return IntArray(FRAME_HEALTH_SAMPLE_SIZE * FRAME_HEALTH_SAMPLE_SIZE) { index ->
            val column = index % FRAME_HEALTH_SAMPLE_SIZE
            val row = index / FRAME_HEALTH_SAMPLE_SIZE
            val x = (
                left + (2 * column + 1) * innerWidth / (2 * FRAME_HEALTH_SAMPLE_SIZE)
            ).coerceIn(0, bitmap.width - 1)
            val y = (
                top + (2 * row + 1) * innerHeight / (2 * FRAME_HEALTH_SAMPLE_SIZE)
            ).coerceIn(0, bitmap.height - 1)
            bitmap.getPixel(x, y)
        }
    }

    @Suppress("DEPRECATION")
    private fun currentGeometry(): ScreenGeometry {
        val windowManager = getSystemService(WindowManager::class.java)
        val densityDpi = resources.displayMetrics.densityDpi
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds = windowManager.maximumWindowMetrics.bounds
            ScreenGeometry(bounds.width(), bounds.height(), densityDpi)
        } else {
            val metrics = DisplayMetrics()
            windowManager.defaultDisplay.getRealMetrics(metrics)
            ScreenGeometry(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi)
        }
    }

    override fun onDestroy() {
        displayManager?.unregisterDisplayListener(displayListener)
        CaptureNotifications.clearCaptureProblem(this)
        releaseProjectionResources()
        captureThread.quitSafely()
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private data class ScreenGeometry(val width: Int, val height: Int, val densityDpi: Int)
    private data class PreparedFrame(
        val jpeg: ByteArray?,
        val inspection: NearBlackInspection,
    )

    companion object {
        const val ACTION_START = "com.focuscompass.app.capture.START"
        const val ACTION_REAUTHORIZE = "com.focuscompass.app.capture.REAUTHORIZE"
        const val ACTION_COMPLETE = "com.focuscompass.app.capture.COMPLETE"
        const val ACTION_ABANDON = "com.focuscompass.app.capture.ABANDON"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val EXTRA_SESSION_ID = "session_id"
        const val EXTRA_DURATION_SECONDS = "duration_seconds"
        const val EXTRA_COMPLETE_REASON = "complete_reason"
        const val EXTRA_SOUND_ENABLED = "sound_enabled"
        const val EXTRA_FIRST_CAPTURE_IMMEDIATE = "first_capture_immediate"
        const val EXTRA_INTERVAL_MILLIS = "interval_millis"
        const val EXTRA_REQUEST_TIMEOUT_MILLIS = "request_timeout_millis"
        const val EXTRA_MAX_IMAGE_DIMENSION = "max_image_dimension"
        const val EXTRA_JPEG_QUALITY = "jpeg_quality"
        private const val FRAME_HEALTH_SAMPLE_SIZE = 32

        fun start(
            context: Context,
            resultCode: Int,
            resultData: Intent,
            sessionId: String,
            durationSeconds: Long,
            soundEnabled: Boolean = true,
            firstCaptureImmediate: Boolean = true,
            intervalMillis: Long = 20_000L,
            requestTimeoutMillis: Long = 18_000L,
            maxImageDimension: Int = 1_024,
            jpegQuality: Int = 72,
        ) {
            val serviceIntent = Intent(context, FocusCaptureService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, resultData)
                putExtra(EXTRA_SESSION_ID, sessionId)
                putExtra(EXTRA_DURATION_SECONDS, durationSeconds)
                putExtra(EXTRA_SOUND_ENABLED, soundEnabled)
                putExtra(EXTRA_FIRST_CAPTURE_IMMEDIATE, firstCaptureImmediate)
                putExtra(EXTRA_INTERVAL_MILLIS, intervalMillis)
                putExtra(EXTRA_REQUEST_TIMEOUT_MILLIS, requestTimeoutMillis)
                putExtra(EXTRA_MAX_IMAGE_DIMENSION, maxImageDimension)
                putExtra(EXTRA_JPEG_QUALITY, jpegQuality)
            }
            context.startForegroundService(serviceIntent)
        }

        fun reauthorize(
            context: Context,
            resultCode: Int,
            resultData: Intent,
            sessionId: String,
        ) {
            val serviceIntent = Intent(context, FocusCaptureService::class.java).apply {
                action = ACTION_REAUTHORIZE
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, resultData)
                putExtra(EXTRA_SESSION_ID, sessionId)
            }
            context.startService(serviceIntent)
        }

        @Suppress("DEPRECATION")
        private fun projectionIntent(intent: Intent): Intent? =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
            } else {
                intent.getParcelableExtra(EXTRA_RESULT_DATA)
            }
    }
}
