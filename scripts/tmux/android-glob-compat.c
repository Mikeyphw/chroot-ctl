#include "android-glob-compat.h"

#if defined(CHROOTCTL_ANDROID_GLOB_COMPAT)

#include <dirent.h>
#include <errno.h>
#include <fnmatch.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

struct path_list {
    char **items;
    size_t count;
    size_t capacity;
};

static void
path_list_free(struct path_list *list)
{
    size_t i;

    for (i = 0; i < list->count; i++)
        free(list->items[i]);
    free(list->items);
    list->items = NULL;
    list->count = 0;
    list->capacity = 0;
}

static int
path_list_add(struct path_list *list, const char *path)
{
    char **next;
    char *copy;
    size_t capacity;

    if (list->count == list->capacity) {
        capacity = list->capacity == 0 ? 8 : list->capacity * 2;
        next = realloc(list->items, capacity * sizeof(*next));
        if (next == NULL)
            return GLOB_NOSPACE;
        list->items = next;
        list->capacity = capacity;
    }
    copy = strdup(path);
    if (copy == NULL)
        return GLOB_NOSPACE;
    list->items[list->count++] = copy;
    return 0;
}

static int
component_has_magic(const char *component)
{
    int escaped = 0;
    const unsigned char *p = (const unsigned char *)component;

    for (; *p != '\0'; p++) {
        if (escaped) {
            escaped = 0;
            continue;
        }
        if (*p == '\\') {
            escaped = 1;
            continue;
        }
        if (*p == '*' || *p == '?' || *p == '[')
            return 1;
    }
    return 0;
}

static char *
unescape_component(const char *component)
{
    char *out, *q;
    const char *p;

    out = malloc(strlen(component) + 1);
    if (out == NULL)
        return NULL;
    q = out;
    for (p = component; *p != '\0'; p++) {
        if (*p == '\\' && p[1] != '\0')
            p++;
        *q++ = *p;
    }
    *q = '\0';
    return out;
}

static char *
join_path(const char *base, const char *name)
{
    size_t base_len = strlen(base), name_len = strlen(name);
    int root = strcmp(base, "/") == 0;
    char *out = malloc(base_len + (root ? 0 : 1) + name_len + 1);

    if (out == NULL)
        return NULL;
    if (root)
        snprintf(out, base_len + name_len + 1, "/%s", name);
    else
        snprintf(out, base_len + name_len + 2, "%s/%s", base, name);
    return out;
}

static int
glob_walk(const char *base, char **parts, size_t index, size_t count,
    int (*errfunc)(const char *, int), struct path_list *out)
{
    const char *component = parts[index];
    struct stat st;
    char *candidate, *literal;
    DIR *dir;
    struct dirent *entry;
    int result = 0;

    if (!component_has_magic(component)) {
        literal = unescape_component(component);
        if (literal == NULL)
            return GLOB_NOSPACE;
        candidate = join_path(base, literal);
        free(literal);
        if (candidate == NULL)
            return GLOB_NOSPACE;
        if (index + 1 == count) {
            if (lstat(candidate, &st) == 0)
                result = path_list_add(out, candidate);
        } else if (stat(candidate, &st) == 0 && S_ISDIR(st.st_mode)) {
            result = glob_walk(candidate, parts, index + 1, count,
                errfunc, out);
        }
        free(candidate);
        return result;
    }

    dir = opendir(base);
    if (dir == NULL) {
        if (errfunc != NULL && errfunc(base, errno) != 0)
            return GLOB_ABORTED;
        return 0;
    }
    errno = 0;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (fnmatch(component, entry->d_name, FNM_PERIOD) != 0)
            continue;
        candidate = join_path(base, entry->d_name);
        if (candidate == NULL) {
            result = GLOB_NOSPACE;
            break;
        }
        if (index + 1 == count) {
            result = path_list_add(out, candidate);
        } else if (stat(candidate, &st) == 0 && S_ISDIR(st.st_mode)) {
            result = glob_walk(candidate, parts, index + 1, count,
                errfunc, out);
        }
        free(candidate);
        if (result != 0)
            break;
    }
    if (result == 0 && errno != 0 && errfunc != NULL && errfunc(base, errno) != 0)
        result = GLOB_ABORTED;
    closedir(dir);
    return result;
}

static int
path_compare(const void *left, const void *right)
{
    const char *const *a = left;
    const char *const *b = right;
    return strcmp(*a, *b);
}

int
glob(const char *pattern, int flags, int (*errfunc)(const char *, int), glob_t *result)
{
    struct path_list matches = {0};
    char *copy, *save = NULL, *token;
    char **parts = NULL, **next;
    size_t count = 0, capacity = 0, i;
    const char *base;
    int rc = 0;

    if (pattern == NULL || result == NULL)
        return GLOB_ABORTED;
    if (flags != 0)
        return GLOB_ABORTED;

    result->gl_pathc = 0;
    result->gl_pathv = NULL;

    copy = strdup(pattern);
    if (copy == NULL)
        return GLOB_NOSPACE;
    token = strtok_r(copy, "/", &save);
    while (token != NULL) {
        if (count == capacity) {
            capacity = capacity == 0 ? 8 : capacity * 2;
            next = realloc(parts, capacity * sizeof(*next));
            if (next == NULL) {
                rc = GLOB_NOSPACE;
                goto out;
            }
            parts = next;
        }
        parts[count++] = token;
        token = strtok_r(NULL, "/", &save);
    }

    base = pattern[0] == '/' ? "/" : ".";
    if (count == 0) {
        if (strcmp(pattern, "/") == 0)
            rc = path_list_add(&matches, "/");
    } else {
        rc = glob_walk(base, parts, 0, count, errfunc, &matches);
    }
    if (rc != 0)
        goto out;
    if (matches.count == 0) {
        rc = GLOB_NOMATCH;
        goto out;
    }

    qsort(matches.items, matches.count, sizeof(*matches.items), path_compare);
    result->gl_pathv = calloc(matches.count + 1, sizeof(*result->gl_pathv));
    if (result->gl_pathv == NULL) {
        rc = GLOB_NOSPACE;
        goto out;
    }
    for (i = 0; i < matches.count; i++) {
        result->gl_pathv[i] = matches.items[i];
        matches.items[i] = NULL;
    }
    result->gl_pathc = matches.count;

out:
    free(parts);
    free(copy);
    path_list_free(&matches);
    if (rc != 0)
        globfree(result);
    return rc;
}

void
globfree(glob_t *result)
{
    size_t i;

    if (result == NULL || result->gl_pathv == NULL)
        return;
    for (i = 0; i < result->gl_pathc; i++)
        free(result->gl_pathv[i]);
    free(result->gl_pathv);
    result->gl_pathv = NULL;
    result->gl_pathc = 0;
}

#endif
