package com.focuscompass.app.model

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiContractTest {
    private val gson = Gson()

    @Test
    fun startRequestUsesBackendMonitoringModeAndMediumValue() {
        val json = gson.toJson(StartFocusRequest("写论文", 25, "medium"))
        assertTrue(json.contains("monitoring_mode"))
        assertTrue(json.contains("medium"))
        assertFalse(json.contains("reminder_mode"))
    }

    @Test
    fun reportAcceptsFractionalDurationSeconds() {
        val report = gson.fromJson(
            """{"focused_seconds":123.5,"distracted_seconds":6.25}""",
            FocusReport::class.java,
        )
        assertEquals(123.5, report.focusedSeconds ?: 0.0, 0.0)
        assertEquals(6.25, report.distractedSeconds ?: 0.0, 0.0)
    }

    @Test
    fun historyAcceptsLegacyEndedAtAlias() {
        val item = gson.fromJson(
            """{"session_id":"s1","ended_at":1787875200.5}""",
            HistoryItem::class.java,
        )
        assertEquals(1787875200.5, item.completedAt ?: 0.0, 0.0)
    }

    @Test
    fun historyAcceptsReportDetailFields() {
        val item = gson.fromJson(
            """
            {
              "session_id":"s2",
              "focused_seconds":123.5,
              "distracted_seconds":6.25,
              "summary":"保持了稳定节奏"
            }
            """.trimIndent(),
            HistoryItem::class.java,
        )
        assertEquals(123.5, item.focusedSeconds ?: 0.0, 0.0)
        assertEquals(6.25, item.distractedSeconds ?: 0.0, 0.0)
        assertEquals("保持了稳定节奏", item.summary)
    }

    @Test
    fun denRequestsUseBackendFieldNames() {
        val config = DenConfig(decoration = listOf("cushion"), ambience = "night")
        val updateMap = gson.fromJson(
            gson.toJson(DenUpdateRequest(config)),
            Map::class.java,
        )
        val configMap = updateMap["den_config"] as Map<*, *>
        val exchangeMap = gson.fromJson(
            gson.toJson(ExchangeRequest("cushion")),
            Map::class.java,
        )

        assertEquals(listOf("cushion"), configMap["decoration"])
        assertEquals("cushion", exchangeMap["item_id"])
    }

    @Test
    fun denPayloadAcceptsServerSceneMetadata() {
        val payload = gson.fromJson(
            """
            {
              "points":350,
              "items":[{
                "id":"desk_lamp",
                "name":"阅读落地灯",
                "price":350,
                "description":"暖光",
                "scene_group":"decoration",
                "scene_slot":"desk-side",
                "owned":true
              }],
              "config":{
                "floor":"base_floor",
                "wall":"base_wall",
                "decoration":["desk_lamp"],
                "ambience":"day"
              }
            }
            """.trimIndent(),
            DenPayload::class.java,
        )

        assertEquals(350, payload.points)
        assertEquals("decoration", payload.items.single().sceneGroup)
        assertEquals("desk-side", payload.items.single().sceneSlot)
        assertTrue(payload.items.single().owned)
        assertEquals(listOf("desk_lamp"), payload.config.decoration)
    }
}
