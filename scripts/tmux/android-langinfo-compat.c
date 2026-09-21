#include "android-langinfo-compat.h"

#include <stdlib.h>

char *
chrootctl_android_nl_langinfo(nl_item item)
{
    static char ascii[] = "ASCII";
    static char utf8[] = "UTF-8";
    static char empty[] = "";

    if (item == CODESET)
        return MB_CUR_MAX == 1 ? ascii : utf8;
    return empty;
}
