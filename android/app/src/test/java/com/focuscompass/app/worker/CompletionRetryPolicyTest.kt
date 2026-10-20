package com.focuscompass.app.worker

import org.junit.Assert.assertEquals
import org.junit.Test

class CompletionRetryPolicyTest {
    @Test
    fun `only transient failures retry`() {
        assertEquals(
            CompletionFailureAction.RETRY,
            classifyCompletionFailure(httpStatus = null, isNetworkFailure = true),
        )
        assertEquals(
            CompletionFailureAction.RETRY,
            classifyCompletionFailure(httpStatus = 429, isNetworkFailure = false),
        )
        assertEquals(
            CompletionFailureAction.RETRY,
            classifyCompletionFailure(httpStatus = 503, isNetworkFailure = false),
        )
    }

    @Test
    fun `authorization and missing session failures are permanent`() {
        assertEquals(
            CompletionFailureAction.AUTH_EXPIRED,
            classifyCompletionFailure(httpStatus = 401, isNetworkFailure = false),
        )
        assertEquals(
            CompletionFailureAction.FORBIDDEN,
            classifyCompletionFailure(httpStatus = 403, isNetworkFailure = false),
        )
        assertEquals(
            CompletionFailureAction.NOT_FOUND,
            classifyCompletionFailure(httpStatus = 404, isNetworkFailure = false),
        )
        assertEquals(
            CompletionFailureAction.FAIL,
            classifyCompletionFailure(httpStatus = 422, isNetworkFailure = false),
        )
    }
}
