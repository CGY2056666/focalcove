package com.focuscompass.app.model

import org.junit.Assert.assertEquals
import org.junit.Test

class DenConfigReducerTest {
    private fun item(
        id: String,
        group: String,
        owned: Boolean = true,
    ) = DenItem(
        id = id,
        name = id,
        price = 1,
        description = "",
        sceneGroup = group,
        sceneSlot = "",
        owned = owned,
    )

    @Test
    fun floorAndWallSelectionsReplaceOnlyTheirOwnSlot() {
        val initial = DenConfig(decoration = listOf("cushion"))
        val floor = updateDenConfig(initial, item("wood_floor", "floor"))
        val wall = updateDenConfig(floor, item("star_wall", "wall"))

        assertEquals("wood_floor", wall.floor)
        assertEquals("star_wall", wall.wall)
        assertEquals(listOf("cushion"), wall.decoration)
    }

    @Test
    fun decorationSelectionTogglesWithoutDuplicating() {
        val item = item("cushion", "decoration")
        val added = updateDenConfig(DenConfig(), item)
        val removed = updateDenConfig(added, item)

        assertEquals(listOf("cushion"), added.decoration)
        assertEquals(emptyList<String>(), removed.decoration)
    }

    @Test
    fun lockedOrUnknownItemsCannotChangeTheRoom() {
        val initial = DenConfig()

        assertEquals(initial, updateDenConfig(initial, item("cushion", "decoration", owned = false)))
        assertEquals(initial, updateDenConfig(initial, item("mystery", "unknown")))
    }

    @Test
    fun ambienceFallsBackToDayForUnknownValues() {
        assertEquals("night", updateDenAmbience(DenConfig(), "night").ambience)
        assertEquals("day", updateDenAmbience(DenConfig(ambience = "night"), "dusk").ambience)
    }
}
