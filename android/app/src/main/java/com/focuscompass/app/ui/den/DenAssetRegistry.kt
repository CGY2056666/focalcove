package com.focuscompass.app.ui.den

import com.focuscompass.app.R

object DenAssetRegistry {
    private val drawables = mapOf(
        "base_floor" to R.drawable.den_base_floor,
        "base_wall" to R.drawable.den_base_wall,
        "wood_floor" to R.drawable.den_wood_floor,
        "star_wall" to R.drawable.den_star_wall,
        "study_desk" to R.drawable.den_study_desk,
        "bookshelf" to R.drawable.den_bookshelf,
        "cat_nest" to R.drawable.den_cat_nest,
        "desk_lamp" to R.drawable.den_desk_lamp,
        "window_curtain" to R.drawable.den_window_curtain,
        "plant_pot" to R.drawable.den_plant_pot,
        "cushion" to R.drawable.den_cushion,
        "wall_clock" to R.drawable.den_wall_clock,
    )

    val itemIds: Set<String> = drawables.keys.toSet()

    fun drawableFor(itemId: String): Int? = drawables[itemId]
}
