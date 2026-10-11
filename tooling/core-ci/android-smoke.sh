#!/usr/bin/env bash
set -euo pipefail
core="$1"
library="$2"
version="$3"
wrapper="${WRAPPER_ROOT:-tooling}/${core}-build"
sdk="${ANDROID_HOME:?}"
ndk="${ANDROID_NDK_HOME:?}"
build="$RUNNER_TEMP/smoke-$core"
mkdir -p "$build/classes"
# Smoke version follows the exact selected upstream tag, not the former hardcoded pin.
python3 - "$wrapper/Smoke.java" "$build/Smoke.java" "$version" <<'PY'
import pathlib,re,sys
source=pathlib.Path(sys.argv[1]).read_text()
source,count=re.subn(r'core.gcVersion\(\).contains\("[0-9.]+"\)', 'core.gcVersion().contains("'+sys.argv[3]+'")',source)
assert count==1
pathlib.Path(sys.argv[2]).write_text(source)
PY
javac -source 8 -target 8 -classpath "$sdk/platforms/android-35/android.jar" -d "$build/classes" "$build/Smoke.java"
mapfile -t classes < <(find "$build/classes" -name '*.class')
"$sdk/build-tools/35.0.0/d8" --lib "$sdk/platforms/android-35/android.jar" --output "$build" "${classes[@]}"
"$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android21-clang" -shared -fPIC "$wrapper/smoke_tun.c" -o "$build/libsmoketun.so"
adb root
adb wait-for-device
adb shell mkdir -p /data/local/tmp/gc-ci/home
adb push "$build/classes.dex" /data/local/tmp/gc-ci/classes.dex
adb push "$library" /data/local/tmp/gc-ci/core.so
adb push "$build/libsmoketun.so" /data/local/tmp/gc-ci/libsmoketun.so
# Capture evidence before emulator-runner tears the device down on failure.
# Diagnostics are best effort and must never replace the original smoke status.
logcat_pid=""
collect_diagnostics() {
  local status=$?
  trap - EXIT
  set +e
  printf 'GC_SMOKE_EXIT core=%s status=%s utc=%s\n' "$core" "$status" "$(date -u +%FT%TZ)" | tee "$build/status.log"
  if [[ -n "$logcat_pid" ]]; then kill "$logcat_pid"; wait "$logcat_pid"; fi
  timeout 15 adb logcat -b all -d -v threadtime > "$build/logcat-final.log" 2>&1
  timeout 15 adb shell dmesg > "$build/dmesg-after.log" 2>&1
  timeout 15 adb shell 'cat /proc/meminfo; ps -A; dumpsys meminfo; ls -l /data/system/packages.xml; od -An -tx1 -N16 /data/system/packages.xml' > "$build/device-after.log" 2>&1
  if (( status != 0 )); then
    for evidence in status.log dmesg-after.log logcat-final.log device-after.log; do
      printf '\nGC_SMOKE_DIAGNOSTIC %s\n' "$evidence"
      cat "$build/$evidence"
    done
  fi
  exit "$status"
}
trap collect_diagnostics EXIT
adb logcat -c
adb logcat -b all -v threadtime > "$build/logcat-stream.log" 2>&1 &
logcat_pid=$!
timeout 15 adb shell 'cat /proc/meminfo; ls -l /data/system/packages.xml; od -An -tx1 -N16 /data/system/packages.xml' > "$build/device-before.log" 2>&1 || true
timeout 15 adb shell dmesg > "$build/dmesg-before.log" 2>&1 || true
printf 'GC_SMOKE_BEGIN core=%s timeout_seconds=180 utc=%s\n' "$core" "$(date -u +%FT%TZ)" | tee "$build/status.log"
adb shell 'CLASSPATH=/data/local/tmp/gc-ci/classes.dex timeout 180 app_process /system/bin expo.modules.xraycore.Smoke /data/local/tmp/gc-ci/core.so /data/local/tmp/gc-ci/home /data/local/tmp/gc-ci/libsmoketun.so' 2>&1 | tee "$build/smoke.log"
if [[ "$core" == mihomo ]]; then
  grep -q MIHOMO_JNI_PROXY_SMOKE_PASS "$build/smoke.log"
  grep -q REAL_TUN_BORROW_RESTART_PASS "$build/smoke.log"
else
  grep -q SMOKE_PASS "$build/smoke.log"
  grep -q TUN_PASS "$build/smoke.log"
fi
