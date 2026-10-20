package com.focuscompass.app.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.nio.ByteBuffer
import java.time.Instant
import java.time.format.DateTimeParseException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

interface TokenProvider {
    fun currentToken(): String?
}

object TokenExpiry {
    fun isExpired(expiresAt: String?, nowEpochSeconds: Long = Instant.now().epochSecond): Boolean {
        if (expiresAt.isNullOrBlank()) return true
        return try {
            Instant.parse(expiresAt).epochSecond <= nowEpochSeconds
        } catch (_: DateTimeParseException) {
            true
        }
    }
}

object AuthenticationFailure {
    fun requiresLogout(httpStatus: Int?, errorCode: String? = null): Boolean =
        httpStatus == 401 || errorCode == "token_expired"
}

class TokenVault(context: Context) : TokenProvider {
    private val preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun save(token: String, expiresAt: String) {
        val encrypted = encrypt(token.toByteArray(Charsets.UTF_8))
        preferences.edit()
            .putString(KEY_TOKEN, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .putString(KEY_EXPIRES_AT, expiresAt)
            .apply()
    }

    override fun currentToken(): String? {
        val expiresAt = preferences.getString(KEY_EXPIRES_AT, null)
        if (TokenExpiry.isExpired(expiresAt)) {
            clear()
            return null
        }
        val encoded = preferences.getString(KEY_TOKEN, null) ?: return null
        return runCatching {
            val encrypted = Base64.decode(encoded, Base64.NO_WRAP)
            decrypt(encrypted).toString(Charsets.UTF_8)
        }.getOrElse {
            clear()
            null
        }
    }

    fun clear() {
        preferences.edit().remove(KEY_TOKEN).remove(KEY_EXPIRES_AT).apply()
    }

    private fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val cipherText = cipher.doFinal(plain)
        return ByteBuffer.allocate(4 + cipher.iv.size + cipherText.size)
            .putInt(cipher.iv.size)
            .put(cipher.iv)
            .put(cipherText)
            .array()
    }

    private fun decrypt(payload: ByteArray): ByteArray {
        val buffer = ByteBuffer.wrap(payload)
        val ivSize = buffer.int
        require(ivSize in 12..32 && buffer.remaining() > ivSize) { "Invalid token payload" }
        val iv = ByteArray(ivSize).also(buffer::get)
        val cipherText = ByteArray(buffer.remaining()).also(buffer::get)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
        return cipher.doFinal(cipherText)
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val PREFS_NAME = "secure_auth"
        const val KEY_TOKEN = "encrypted_access_token"
        const val KEY_EXPIRES_AT = "token_expires_at"
        const val KEY_ALIAS = "focus_compass_auth_aes"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
