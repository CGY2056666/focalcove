package com.focuscompass.app.network

import com.focuscompass.app.model.AuthPayload
import com.focuscompass.app.model.AuthRequest
import com.focuscompass.app.model.BootstrapPayload
import com.focuscompass.app.model.CompleteRequest
import com.focuscompass.app.model.CompletionPayload
import com.focuscompass.app.model.DenPayload
import com.focuscompass.app.model.DenUpdateRequest
import com.focuscompass.app.model.ExchangeRequest
import com.focuscompass.app.model.FocusSessionPayload
import com.focuscompass.app.model.HistoryPayload
import com.focuscompass.app.model.StartFocusRequest
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.PUT

interface FocusApi {
    @POST("api/v1/auth/register")
    suspend fun register(@Body request: AuthRequest): AuthPayload

    @POST("api/v1/auth/login")
    suspend fun login(@Body request: AuthRequest): AuthPayload

    @POST("api/v1/auth/logout")
    suspend fun logout(): Response<Unit>

    @GET("api/v1/bootstrap")
    suspend fun bootstrap(@Query("goal") goal: String?): BootstrapPayload

    @GET("api/v1/focus-sessions/current")
    suspend fun currentSession(): Response<FocusSessionPayload>

    @POST("api/v1/focus-sessions")
    suspend fun startSession(@Body request: StartFocusRequest): FocusSessionPayload

    @Multipart
    @POST("api/v1/focus-sessions/{id}/frames")
    suspend fun uploadFrame(
        @Path("id") sessionId: String,
        @Part screenshot: MultipartBody.Part,
        @Part("frame_id") frameId: RequestBody,
        @Part("captured_at") capturedAt: RequestBody,
    ): FocusSessionPayload

    @GET("api/v1/focus-sessions/{id}")
    suspend fun getSession(@Path("id") sessionId: String): FocusSessionPayload

    @POST("api/v1/focus-sessions/{id}/complete")
    suspend fun completeSession(
        @Path("id") sessionId: String,
        @Body request: CompleteRequest,
    ): CompletionPayload

    @DELETE("api/v1/focus-sessions/{id}")
    suspend fun abandonSession(@Path("id") sessionId: String): Response<Unit>

    @GET("api/v1/history")
    suspend fun history(@Query("limit") limit: Int): HistoryPayload

    @GET("api/v1/den")
    suspend fun den(): DenPayload

    @PUT("api/v1/den")
    suspend fun updateDen(@Body request: DenUpdateRequest): DenPayload

    @POST("api/v1/shop/exchanges")
    suspend fun exchangeFurniture(@Body request: ExchangeRequest): DenPayload
}
