package com.focuscompass.app.ui.den

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DenAssetRegistryTest {
    @Test
    fun `registry covers every current den item`() {
        val expectedIds = setOf(
            "base_floor",
            "base_wall",
            "wood_floor",
            "star_wall",
            "study_desk",
            "bookshelf",
            "cat_nest",
            "desk_lamp",
            "window_curtain",
            "plant_pot",
            "cushion",
            "wall_clock",
        )

        assertEquals(expectedIds, DenAssetRegistry.itemIds)
        expectedIds.forEach { itemId ->
            assertNotNull(itemId, DenAssetRegistry.drawableFor(itemId))
        }
    }

    @Test
    fun `registry excludes utility reward previews`() {
        val utilityRewardIds = setOf(
            "premium_member_1m",
            "premium_member_3m",
            "coffee_voucher",
            "snack_combo",
            "bubble_tea",
            "energy_drink",
            "coupon_50",
            "coupon_100",
            "book_credit",
            "music_membership_1m",
        )

        assertTrue(DenAssetRegistry.itemIds.intersect(utilityRewardIds).isEmpty())
        utilityRewardIds.forEach { itemId ->
            assertNull(itemId, DenAssetRegistry.drawableFor(itemId))
        }
    }
}
