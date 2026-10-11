#!/usr/bin/env bash
set -euo pipefail
: "${CORE:?selected core required}"
library=$(python3 -c 'import json,os; c=os.environ["CORE"]; print("artifacts/"+c+"/"+json.load(open("artifacts/"+c+"/manifest.json"))["cores"][c]["files"]["x86_64"]["path"])')
version=$(python3 -c 'import json,os; print(json.load(open("selection/"+os.environ["CORE"]+".json"))["version"])')
test -f "$library"
ANDROID_NDK_HOME="$ANDROID_HOME/ndk/27.1.12297006" bash tooling/core-ci/android-smoke.sh "$CORE" "$library" "$version"
