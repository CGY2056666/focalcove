package com.focuscompass.app.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GuideContentTest {
    @Test
    fun guide_has_the_six_mobile_chapters_in_display_order() {
        assertEquals(
            listOf(
                GuideSectionId.QUICK_START,
                GuideSectionId.STATUS_AND_REPORT,
                GuideSectionId.PROJECTION_AND_PRIVACY,
                GuideSectionId.POINTS_AND_DEN,
                GuideSectionId.FAQ,
                GuideSectionId.LICENSE_AND_OPEN_SOURCE,
            ),
            guideSections.map { it.id },
        )
        assertTrue(guideSections.all { it.items.isNotEmpty() })
    }

    @Test
    fun guide_keeps_mobile_privacy_and_reliability_boundaries_visible() {
        val text = guideContentText()

        listOf(
            "HTTPS",
            "云端视觉模型",
            "客户端不保存截图",
            "华为",
            "近黑画面",
            "不会判为确定分心",
            "仅供参考",
            "小窝",
            "Apache License 2.0",
            "THIRD_PARTY_NOTICES.md",
        ).forEach { required ->
            assertTrue("Missing guide statement: $required", text.contains(required))
        }
    }

    @Test
    fun guide_does_not_reintroduce_web_only_or_developer_copy() {
        val text = guideContentText()

        listOf(
            "浏览器",
            "标签页",
            "开发者备注",
            "评测采样",
            "本地原型",
        ).forEach { forbidden ->
            assertFalse("Unexpected obsolete guide statement: $forbidden", text.contains(forbidden))
        }
    }
}
