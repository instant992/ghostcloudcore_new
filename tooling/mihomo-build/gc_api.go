//go:build android && cgo
package main
/*
#include <jni.h>
#include <stdlib.h>
static jstring newString(JNIEnv *e, const char *s) { return (*e)->NewStringUTF(e,s); }
static const char *getString(JNIEnv *e, jstring s) { return s ? (*e)->GetStringUTFChars(e,s,0) : NULL; }
static void releaseString(JNIEnv *e, jstring s,const char *v) { if(s && v) (*e)->ReleaseStringUTFChars(e,s,v); }
*/
import "C"
import (
 "unsafe"
 "fmt"
 M "github.com/metacubex/mihomo/constant"
)
func result(e *C.JNIEnv, err error) C.jstring { s := ""; if err != nil { s=err.Error() }; return stringResult(e,s) }
func stringResult(e *C.JNIEnv,s string) C.jstring { c:=C.CString(s); defer C.free(unsafe.Pointer(c)); return C.newString(e,c) }
//export Java_expo_modules_xraycore_GcCore_gcInit
func Java_expo_modules_xraycore_GcCore_gcInit(e *C.JNIEnv,c C.jclass,s C.jstring) C.jstring { v:=C.getString(e,s); defer C.releaseString(e,s,v); return result(e,initCore(C.GoString(v))) }
//export Java_expo_modules_xraycore_GcCore_gcStart
func Java_expo_modules_xraycore_GcCore_gcStart(e *C.JNIEnv,c C.jclass,s C.jstring,fd C.jint) C.jstring { v:=C.getString(e,s); defer C.releaseString(e,s,v); return result(e,startCore(C.GoString(v),int(fd))) }
//export Java_expo_modules_xraycore_GcCore_gcStop
func Java_expo_modules_xraycore_GcCore_gcStop(e *C.JNIEnv,c C.jclass) { stopCore() }
//export Java_expo_modules_xraycore_GcCore_gcVersion
func Java_expo_modules_xraycore_GcCore_gcVersion(e *C.JNIEnv,c C.jclass) C.jstring { return stringResult(e,fmt.Sprintf("mihomo %s",M.Version)) }
