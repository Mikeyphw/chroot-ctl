package com.mikeyphw.chrootctl.ui

import androidx.annotation.StringRes
import com.mikeyphw.chrootctl.R

enum class AppDestination(
    @param:StringRes val labelRes: Int,
    @param:StringRes val glyphRes: Int,
    @param:StringRes val subtitleRes: Int,
) {
    Home(R.string.nav_home, R.string.glyph_home, R.string.destination_home_subtitle),
    Chroots(R.string.nav_chroots, R.string.glyph_chroots, R.string.destination_chroots_subtitle),
    Install(R.string.nav_install, R.string.glyph_install, R.string.destination_install_subtitle),
    Activity(R.string.nav_activity, R.string.glyph_activity, R.string.destination_activity_subtitle),
    Tools(R.string.nav_tools, R.string.glyph_tools, R.string.destination_tools_subtitle),
}
