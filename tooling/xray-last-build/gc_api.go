// GhostCloud JNI wrapper for unmodified official XTLS/Xray-core v26.10.10.
// Экспортирует уникальные JNI-символы GcXrayLastCore (не конфликтует с gomobile
// libXray встроенного ядра и с GcSbCore sing-box).
package main

/*
#include <jni.h>
#include <stdlib.h>

static jstring xlNewString(JNIEnv *env, const char *s) {
    return (jstring)(*env)->NewStringUTF(env, s ? s : "");
}

static const char *xlGetString(JNIEnv *env, jstring s) {
    if (!s) return NULL;
    return (const char *)(*env)->GetStringUTFChars(env, s, NULL);
}

static void xlReleaseString(JNIEnv *env, jstring s, const char *c) {
    if (s && c) (*env)->ReleaseStringUTFChars(env, s, c);
}
*/
import "C"
import (
	"encoding/json"
	"golang.org/x/sys/unix"
	"os"
	"strconv"
	"strings"
	"sync"
	"unsafe"

	"github.com/xtls/xray-core/core"
	_ "github.com/xtls/xray-core/main/distro/all"
)

var (
	mu       sync.Mutex
	instance *core.Instance
	ownedFd  = -1
)

func xlError(env *C.JNIEnv, msg string) C.jstring {
	c := C.CString(msg)
	defer C.free(unsafe.Pointer(c))
	return C.xlNewString(env, c)
}

// gcInit(homeDir) — домашний каталог ядра (кэши, логи).
//
//export Java_expo_modules_xraycore_GcXrayLastCore_gcInit
func Java_expo_modules_xraycore_GcXrayLastCore_gcInit(env *C.JNIEnv, clazz C.jclass, homeDir C.jstring) C.jstring {
	cHome := C.xlGetString(env, homeDir)
	defer C.xlReleaseString(env, homeDir, cHome)
	home := C.GoString(cHome)
	if home == "" {
		return xlError(env, "home-dir is empty")
	}
	if err := os.MkdirAll(home, 0o755); err != nil {
		return xlError(env, err.Error())
	}
	mu.Lock()
	defer mu.Unlock()
	if err := os.Chdir(home); err != nil {
		return xlError(env, err.Error())
	}
	return xlError(env, "")
}

// gcStart(configJson, tunFd) — запускает Official Xray с TUN-дескриптором приложения.
// Конфиг — стандартный Xray JSON; секция "env" применяется самим LoadConfig
// (xray.location.asset и пр.), TUN-fd прокидываем через env-ключ xray.tun.fd.
// Возвращает "" при успехе, иначе текст ошибки.
//
//export Java_expo_modules_xraycore_GcXrayLastCore_gcStart
func Java_expo_modules_xraycore_GcXrayLastCore_gcStart(env *C.JNIEnv, clazz C.jclass, configJson C.jstring, fd C.jint) C.jstring {
	cCfg := C.xlGetString(env, configJson)
	defer C.xlReleaseString(env, configJson, cCfg)

	mu.Lock()
	defer mu.Unlock()
	if instance != nil {
		return xlError(env, "already running")
	}

	// Borrow Java's descriptor; retain our own duplicate until stop completes.
	if fd >= 0 {
		dup, err := unix.Dup(int(fd))
		if err != nil {
			return xlError(env, "dup tun: "+err.Error())
		}
		ownedFd = dup
		os.Setenv("xray.tun.fd", strconv.Itoa(dup))
	}
	success := false
	defer func() {
		if !success && ownedFd >= 0 {
			unix.Close(ownedFd)
			ownedFd = -1
		}
	}()

	// Config env is applied by LoadConfig; override any stale/caller-supplied FD.
	configText := C.GoString(cCfg)
	var raw map[string]json.RawMessage
	if err := json.Unmarshal([]byte(configText), &raw); err != nil {
		return xlError(env, "load config: "+err.Error())
	}
    if raw == nil { return xlError(env, "config must be a JSON object") }
	var configEnv map[string]string
	if value, ok := raw["env"]; ok {
		if err := json.Unmarshal(value, &configEnv); err != nil {
			return xlError(env, "config env: "+err.Error())
		}
	}
	if configEnv == nil {
		configEnv = make(map[string]string)
	}
	if ownedFd >= 0 {
		configEnv["xray.tun.fd"] = strconv.Itoa(ownedFd)
	} else {
		delete(configEnv, "xray.tun.fd")
		os.Unsetenv("xray.tun.fd")
	}
	raw["env"], _ = json.Marshal(configEnv)
	configBytes, _ := json.Marshal(raw)
	config, err := core.LoadConfig("json", strings.NewReader(string(configBytes)))
	if err != nil {
		return xlError(env, "load config: "+err.Error())
	}
	server, err := core.New(config)
	if err != nil {
		return xlError(env, "new instance: "+err.Error())
	}
	if err = server.Start(); err != nil {
		_ = server.Close()
		return xlError(env, "start: "+err.Error())
	}
	instance = server
	success = true
	return xlError(env, "")
}

// gcStop() — останавливает ядро.
//
//export Java_expo_modules_xraycore_GcXrayLastCore_gcStop
func Java_expo_modules_xraycore_GcXrayLastCore_gcStop(env *C.JNIEnv, clazz C.jclass) {
	mu.Lock()
	defer mu.Unlock()
	if instance != nil {
		instance.Close()
		instance = nil
	}
	if ownedFd >= 0 {
		unix.Close(ownedFd)
		ownedFd = -1
	}
}

// gcVersion() — версия ядра.
//
//export Java_expo_modules_xraycore_GcXrayLastCore_gcVersion
func Java_expo_modules_xraycore_GcXrayLastCore_gcVersion(env *C.JNIEnv, clazz C.jclass) C.jstring {
	return xlError(env, "Xray "+core.Version())
}
