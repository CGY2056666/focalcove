package com.focuscompass.app

internal enum class MainDestination(val route: String) {
    HOME("home"),
    DEN("den"),
    HISTORY("history"),
    SETTINGS("settings"),
}

internal const val HISTORY_DETAIL_ROUTE_PATTERN = "history-detail/{sessionId}"

internal fun historyDetailRoute(sessionId: String): String {
    require(sessionId.isNotBlank() && sessionId.none { it == '/' || it == '{' || it == '}' }) {
        "sessionId must be a non-empty route segment"
    }
    return "history-detail/$sessionId"
}

internal fun selectedMainDestination(route: String?): MainDestination? =
    MainDestination.entries.firstOrNull { it.route == route }

internal fun shouldShowBottomNavigation(
    route: String?,
    authenticated: Boolean,
): Boolean = authenticated && selectedMainDestination(route) != null
