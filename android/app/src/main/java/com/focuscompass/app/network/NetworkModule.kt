package com.focuscompass.app.network

import android.util.Log
import com.focuscompass.app.BuildConfig
import com.focuscompass.app.security.TokenProvider
import com.google.gson.Gson
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

class BearerInterceptor(private val tokenProvider: TokenProvider) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val token = tokenProvider.currentToken()
        val request = chain.request().newBuilder().apply {
            if (!token.isNullOrBlank()) header("Authorization", "Bearer $token")
        }.build()
        return chain.proceed(request)
    }
}

/**
 * Debug-only request logging that never records query strings, headers, or bodies.
 * Goals travel as query parameters, so a standard HTTP logger would leak them to Logcat.
 */
internal class SafeLoggingInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val started = System.nanoTime()
        val response = chain.proceed(request)
        val elapsedMs = (System.nanoTime() - started) / 1_000_000
        Log.d(
            "FocusApi",
            "${request.method} ${request.url.encodedPath} -> ${response.code} (${elapsedMs}ms)",
        )
        return response
    }
}

object NetworkModule {
    fun createApi(tokenProvider: TokenProvider): FocusApi {
        val client = OkHttpClient.Builder()
            .addInterceptor(BearerInterceptor(tokenProvider))
            .apply {
                if (BuildConfig.DEBUG) addInterceptor(SafeLoggingInterceptor())
            }
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .callTimeout(20, TimeUnit.SECONDS)
            .build()
        return Retrofit.Builder()
            .baseUrl(BuildConfig.FOCUS_API_BASE_URL)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create(Gson()))
            .build()
            .create(FocusApi::class.java)
    }
}
