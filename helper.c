/* wallpaper-helper: exec wrapper that exists solely to hold the Full Disk
 * Access grant launchd jobs need to reach state in iCloud Drive
 * (~/Library/Mobile Documents is TCC-protected; background launchd
 * processes cannot receive a consent prompt, so a granted binary must sit
 * between launchd and the scripts).
 *
 * Grant once: System Settings -> Privacy & Security -> Full Disk Access ->
 * add ~/.local/bin/wallpaper-helper.
 */
#include <stdio.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s command [args...]\n", argv[0]);
        return 64;
    }
    execvp(argv[1], &argv[1]);
    perror("execvp");
    return 71;
}
