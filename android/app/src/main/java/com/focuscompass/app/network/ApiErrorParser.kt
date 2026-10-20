package com.focuscompass.app.network

import com.focuscompass.app.model.ApiErrorBody
import com.focuscompass.app.model.ApiErrorEnvelope
import com.google.gson.Gson
import retrofit2.HttpException

object ApiErrorParser {
    private val gson = Gson()

    fun parse(exception: HttpException): ApiErrorBody? = runCatching {
        val source = exception.response()?.errorBody()?.source() ?: return@runCatching null
        source.request(Long.MAX_VALUE)
        gson.fromJson(source.buffer.clone().readUtf8(), ApiErrorEnvelope::class.java)?.error
    }.getOrNull()

    fun message(exception: HttpException): String? =
        parse(exception)?.message?.takeIf { it.isNotBlank() }
}
