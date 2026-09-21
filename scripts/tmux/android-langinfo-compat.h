#ifndef CHROOTCTL_ANDROID_LANGINFO_COMPAT_H
#define CHROOTCTL_ANDROID_LANGINFO_COMPAT_H

#if defined(CHROOTCTL_ANDROID_LANGINFO_COMPAT)
#include <langinfo.h>
char *chrootctl_android_nl_langinfo(nl_item item);
#define nl_langinfo chrootctl_android_nl_langinfo
#endif

#endif
