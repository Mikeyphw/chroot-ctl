#ifndef CHROOTCTL_ANDROID_GLOB_COMPAT_H
#define CHROOTCTL_ANDROID_GLOB_COMPAT_H

#include <glob.h>

#if defined(CHROOTCTL_ANDROID_GLOB_COMPAT)
#ifdef __cplusplus
extern "C" {
#endif
int glob(const char *, int, int (*)(const char *, int), glob_t *);
void globfree(glob_t *);
#ifdef __cplusplus
}
#endif
#endif

#endif
