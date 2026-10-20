package com.focuscompass.app.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.focuscompass.app.R

internal object CaptureNotifications {
    const val ONGOING_CHANNEL_ID = "focus_capture"
    const val ALERT_SOUND_CHANNEL_ID = "focus_alerts_sound"
    const val ALERT_SILENT_CHANNEL_ID = "focus_alerts_silent"
    const val ONGOING_NOTIFICATION_ID = 7_201
    internal const val ALERT_NOTIFICATION_BASE_ID = 8_000
    internal const val ALERT_NOTIFICATION_ID_MASK = 0x0fff
    internal const val CAPTURE_WARNING_NOTIFICATION_ID = 13_001

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                ONGOING_CHANNEL_ID,
                "专注监控",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "专注期间必须显示的屏幕采集状态"
                setSound(null, null)
                enableVibration(false)
            },
        )
        manager.createNotificationChannel(
            NotificationChannel(
                ALERT_SOUND_CHANNEL_ID,
                "专注提醒（有声）",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "检测到分心风险或整屏共享异常时发出声音和振动提醒"
                enableVibration(true)
            },
        )
        manager.createNotificationChannel(
            NotificationChannel(
                ALERT_SILENT_CHANNEL_ID,
                "专注提醒（静音）",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "检测到分心风险或整屏共享异常时仅显示提醒"
                setSound(null, null)
                enableVibration(false)
            },
        )
    }

    fun ongoing(context: Context): Notification {
        val endIntent = Intent(context, FocusCaptureService::class.java).apply {
            action = FocusCaptureService.ACTION_COMPLETE
            putExtra(FocusCaptureService.EXTRA_COMPLETE_REASON, "manual_notification")
        }
        val endPendingIntent = PendingIntent.getService(
            context,
            1,
            endIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = NotificationCompat.Builder(context, ONGOING_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification_capture)
            .setContentTitle("专注小窝正在监控")
            .setContentText("每 20 秒分析一次当前屏幕，截图不会保存到本机")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .addAction(0, "结束本轮", endPendingIntent)

        context.packageManager.getLaunchIntentForPackage(context.packageName)?.let { launchIntent ->
            builder.setContentIntent(
                PendingIntent.getActivity(
                    context,
                    2,
                    launchIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                ),
            )
        }
        return builder.build()
    }

    fun showAlert(context: Context, event: CaptureAlertEvent, soundEnabled: Boolean) {
        val manager = context.getSystemService(NotificationManager::class.java)
        val channelId = if (soundEnabled) ALERT_SOUND_CHANNEL_ID else ALERT_SILENT_CHANNEL_ID
        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(R.drawable.ic_notification_alert)
            .setContentTitle(event.title)
            .setContentText(event.message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(event.message))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .apply {
                if (soundEnabled) setDefaults(Notification.DEFAULT_SOUND or Notification.DEFAULT_VIBRATE)
            }
            .build()
        manager.notify(
            ALERT_NOTIFICATION_BASE_ID + event.eventId.hashCode().and(ALERT_NOTIFICATION_ID_MASK),
            notification,
        )
    }

    fun showCaptureProblem(context: Context, soundEnabled: Boolean) {
        val manager = context.getSystemService(NotificationManager::class.java)
        val channelId = if (soundEnabled) ALERT_SOUND_CHANNEL_ID else ALERT_SILENT_CHANNEL_ID
        val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
        val launchPendingIntent = launchIntent?.let {
            PendingIntent.getActivity(
                context,
                3,
                it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }
        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(R.drawable.ic_notification_alert)
            .setContentTitle("投屏画面可能已失效")
            .setContentText("连续收到近黑画面，请返回专注小窝检查或重新授权。")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    "连续收到近黑画面，可能是安全页面，也可能是系统已停止整屏共享。" +
                        "这不会被记为分心，请返回专注小窝检查或重新授权。",
                ),
            )
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ERROR)
            .setAutoCancel(true)
            .apply {
                launchPendingIntent?.let {
                    setContentIntent(it)
                    addAction(0, "返回专注页", it)
                }
                if (soundEnabled) setDefaults(Notification.DEFAULT_SOUND or Notification.DEFAULT_VIBRATE)
            }
            .build()
        manager.notify(CAPTURE_WARNING_NOTIFICATION_ID, notification)
    }

    fun clearCaptureProblem(context: Context) {
        context.getSystemService(NotificationManager::class.java)
            .cancel(CAPTURE_WARNING_NOTIFICATION_ID)
    }
}
