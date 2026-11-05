#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--help") == 0) {
        if (getuid() != 65534 || access("/var/run/docker.sock", F_OK) == 0) return 77;
        int fd = open("/binpack-must-be-readonly", O_CREAT | O_WRONLY, 0600);
        if (fd >= 0) { close(fd); return 78; }
        puts("--port <PORT> [default: 18765]\n--data-dir <DIR> [default: /data]\n--config <PATH>");
        return 0;
    }
    printf("fixture-ready");
    for (int i = 1; i < argc; ++i) printf(" %s", argv[i]);
    puts("");
    return 0;
}
