package com.focuscompass.app.network

import com.focuscompass.app.model.ApiErrorBody
import com.focuscompass.app.model.ApiErrorEnvelope
import com.google.gson.Gson
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

class ApiErrorParserTest {
    @Test
    fun parsesBackendErrorCodesAndMessages() {
        val cases = listOf(
            Case(401, text('i', 'n', 'v', 'a', 'l', 'i', 'd', '_', 'c', 'r', 'e', 'd', 'e', 'n', 't', 'i', 'a', 'l', 's'), text('用', '户', '名', '或', '密', '码', '错', '误')),
            Case(409, text('u', 's', 'e', 'r', 'n', 'a', 'm', 'e', '_', 'e', 'x', 'i', 's', 't', 's'), text('用', '户', '名', '已', '存', '在')),
            Case(409, text('a', 'c', 't', 'i', 'v', 'e', '_', 's', 'e', 's', 's', 'i', 'o', 'n', '_', 'e', 'x', 'i', 's', 't', 's'), text('已', '有', '进', '行', '中', '的', '专', '注', '会', '话')),
            Case(429, text('r', 'a', 't', 'e', '_', 'l', 'i', 'm', 'i', 't', 'e', 'd'), text('认', '证', '请', '求', '过', '于', '频', '繁', '，', '请', '稍', '后', '再', '试'), retryable = true),
        )

        cases.forEach { case ->
            val exception = apiException(case)
            val parsed = ApiErrorParser.parse(exception)

            assertEquals(case.code, parsed?.code)
            assertEquals(case.message, ApiErrorParser.message(exception))
            assertEquals(case.retryable, parsed?.retryable)
        }
    }

    @Test
    fun invalidJsonHasNoBackendMessage() {
        val response = Response.error<Any>(
            503,
            text('n', 'o', 't', '-', 'j', 's', 'o', 'n').toResponseBody(),
        )

        assertTrue(ApiErrorParser.message(HttpException(response)) == null)
    }

    private fun apiException(case: Case): HttpException {
        val envelope = ApiErrorEnvelope(
            ApiErrorBody(case.code, case.message, case.retryable),
        )
        val body = Gson().toJson(envelope).toResponseBody()
        return HttpException(Response.error<Any>(case.status, body))
    }

    private fun text(vararg characters: Char): String = String(characters)

    private data class Case(
        val status: Int,
        val code: String,
        val message: String,
        val retryable: Boolean = false,
    )
}
