#include <jni.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/if.h>
#include <linux/if_tun.h>
#include <string.h>

JNIEXPORT jint JNICALL Java_expo_modules_xraycore_Smoke_openTun(JNIEnv *env, jclass cls) {
    int fd = open("/dev/tun", O_RDWR | O_CLOEXEC);
    if (fd < 0) fd = open("/dev/net/tun", O_RDWR | O_CLOEXEC);
    if (fd < 0) return -1;
    struct ifreq req;
    memset(&req, 0, sizeof(req));
    strcpy(req.ifr_name, "gcsmoke");
    req.ifr_flags = IFF_TUN | IFF_NO_PI;
    if (ioctl(fd, TUNSETIFF, &req) < 0) { close(fd); return -1; }
    return fd;
}
JNIEXPORT jboolean JNICALL Java_expo_modules_xraycore_Smoke_fdOpen(JNIEnv *env, jclass cls, jint fd) {
    return fcntl(fd, F_GETFD) >= 0;
}
JNIEXPORT void JNICALL Java_expo_modules_xraycore_Smoke_closeFd(JNIEnv *env, jclass cls, jint fd) { close(fd); }
