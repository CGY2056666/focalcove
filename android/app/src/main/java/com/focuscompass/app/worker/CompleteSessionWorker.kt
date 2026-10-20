package com.focuscompass.app.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.focuscompass.app.capture.CaptureRuntime
import com.focuscompass.app.capture.CaptureStateStore
import com.focuscompass.app.data.AppPreferences
import java.io.IOException
import retrofit2.HttpException

/** Retries only the idempotent, image-free completion request. */
class CompleteSessionWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val sessionId = inputData.getString(KEY_SESSION_ID) ?: return Result.failure()
        val reason = inputData.getString(KEY_REASON) ?: "background_retry"
        return try {
            val completion = CaptureRuntime.requireBackend(applicationContext).completeSession(sessionId, reason)
            AppPreferences(applicationContext).setActiveSessionId(null)
            CaptureStateStore.completed(completion)
            Result.success()
        } catch (throwable: Throwable) {
            when (
                classifyCompletionFailure(
                    httpStatus = (throwable as? HttpException)?.code(),
                    isNetworkFailure = throwable is IOException,
                )
            ) {
                CompletionFailureAction.RETRY -> {
                    if (runAttemptCount >= MAX_RETRIES - 1) {
                        CaptureStateStore.interrupted("结算重试次数已用尽，请稍后在历史记录中确认")
                        Result.failure()
                    } else {
                        Result.retry()
                    }
                }
                CompletionFailureAction.AUTH_EXPIRED -> {
                    CaptureStateStore.interrupted("登录已过期，无法继续结算")
                    Result.failure()
                }
                CompletionFailureAction.FORBIDDEN -> {
                    CaptureStateStore.interrupted("无权结算此专注会话")
                    Result.failure()
                }
                CompletionFailureAction.NOT_FOUND -> {
                    CaptureStateStore.interrupted("专注会话已不存在，无法结算")
                    Result.failure()
                }
                CompletionFailureAction.FAIL -> {
                    CaptureStateStore.interrupted("结算请求失败且不可重试")
                    Result.failure()
                }
            }
        }
    }

    companion object {
        const val KEY_SESSION_ID = "session_id"
        const val KEY_REASON = "reason"
        private const val MAX_RETRIES = 5
    }
}
