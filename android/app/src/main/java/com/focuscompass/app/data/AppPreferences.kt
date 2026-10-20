package com.focuscompass.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.appDataStore by preferencesDataStore(name = "app_preferences")

class AppPreferences(private val context: Context) {
    val privacyAccepted: Flow<Boolean> = context.appDataStore.data.map { preferences ->
        preferences[PRIVACY_ACCEPTED] ?: false
    }

    val soundEnabled: Flow<Boolean> = context.appDataStore.data.map { preferences ->
        preferences[SOUND_ENABLED] ?: true
    }

    val activeSessionId: Flow<String?> = context.appDataStore.data.map { preferences ->
        preferences[ACTIVE_SESSION_ID]
    }

    suspend fun setPrivacyAccepted(accepted: Boolean) {
        context.appDataStore.edit { it[PRIVACY_ACCEPTED] = accepted }
    }

    suspend fun setSoundEnabled(enabled: Boolean) {
        context.appDataStore.edit { it[SOUND_ENABLED] = enabled }
    }

    suspend fun setActiveSessionId(sessionId: String?) {
        context.appDataStore.edit { preferences ->
            if (sessionId == null) preferences.remove(ACTIVE_SESSION_ID)
            else preferences[ACTIVE_SESSION_ID] = sessionId
        }
    }

    private companion object {
        val PRIVACY_ACCEPTED = booleanPreferencesKey("privacy_accepted")
        val SOUND_ENABLED = booleanPreferencesKey("sound_enabled")
        val ACTIVE_SESSION_ID = stringPreferencesKey("active_session_id")
    }
}
