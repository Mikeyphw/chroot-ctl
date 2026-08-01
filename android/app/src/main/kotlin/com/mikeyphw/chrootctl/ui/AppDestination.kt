package com.mikeyphw.chrootctl.ui

import androidx.annotation.StringRes
import com.mikeyphw.chrootctl.R

enum class AppDestination(@StringRes val labelRes: Int, @StringRes val glyphRes: Int) {
    Home(R.string.nav_home, R.string.glyph_home),
    Chroots(R.string.nav_chroots, R.string.glyph_chroots),
    Activity(R.string.nav_activity, R.string.glyph_activity),
    Tools(R.string.nav_tools, R.string.glyph_tools),
}
