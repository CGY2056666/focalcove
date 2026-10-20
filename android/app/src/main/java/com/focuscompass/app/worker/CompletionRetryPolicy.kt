package com.focuscompass.app.worker

enum class CompletionFailureAction {
    RETRY,
    AUTH_EXPIRED,
    FORBIDDEN,
    NOT_FOUND,
    FAIL,
}

fun classifyCompletionFailure(
    httpStatus: Int?,
    isNetworkFailure: Boolean,
): CompletionFailureAction = when {
    httpStatus == 401 -> CompletionFailureAction.AUTH_EXPIRED
    httpStatus == 403 -> CompletionFailureAction.FORBIDDEN
    httpStatus == 404 -> CompletionFailureAction.NOT_FOUND
    httpStatus == 429 || httpStatus != null && httpStatus >= 500 ->
        CompletionFailureAction.RETRY
    httpStatus != null -> CompletionFailureAction.FAIL
    isNetworkFailure -> CompletionFailureAction.RETRY
    else -> CompletionFailureAction.FAIL
}
