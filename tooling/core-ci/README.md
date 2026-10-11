# Automatic upstream Android JNI builds

Canonical pipeline: `instant992/ghostcloudcore_new`, default branch `main`.
Client `release` owns source under `scripts/`; distribution `tooling/` contains
an explicitly committed copy so public runners need no private-client token.
Keep these copies synchronized when changing wrappers or tests.

- Every six hours: select newest numeric published Mihomo **stable** release and
  newest numeric Xray release **including prereleases**, resolve tag to full SHA.
- No change: no build. Push touching tooling: dry-run both currently published pins.
- Manual `dry_run=true` (default): builds current pins; never publishes.
- Clean, isolated upstream checkout, exact SHA assertion, isolated wrapper graph,
  `go mod verify`, host local proxy tests, four NDK 27.1 JNI ABIs, ELF ABI/DYN,
  defined JNI symbols and actual PT_LOAD 16KiB alignment assertions.
- Mihomo borrowed FD patch must match exactly one unmodified upstream block;
  changed ownership code fails closed for human review. Never edit module cache.
- x86_64 Android ART smoke includes malformed-start FD checks, real SOCKS bytes,
  restart cycles and root-created real TUN borrowed-FD ownership.
- All selected cores must finish all tests before publication can request approval.
- Immutable run-scoped directories; sha256/size verified again before merge;
  non-target cores preserved; target manifest changed since selection rejects stale
  runs. Push is fast-forward only; commit-pinned remote manifest and every binary
  downloaded and verified after push. No GitHub Releases/assets are replaced.

## Manual approval is mandatory

`core-production` is configured in the **distribution repository**, with
`instant992` (user ID `59600183`) as required reviewer, admin bypass disabled,
and only the `main` branch allowed. Configuration was verified by authenticated
API readback. Publication still fails closed if protection becomes unavailable.
To recreate it with an authenticated `gh` (no token in this file):

```sh
gh api --method PUT repos/instant992/ghostcloudcore_new/environments/core-production \
  --input environment.json
```

`environment.json` (non-secret):
```json
{
  "wait_timer": 0,
  "prevent_self_review": false,
  "reviewers": [{"type": "User", "id": 59600183}],
  "can_admins_bypass": false,
  "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}
}
```
Then POST `.../environments/core-production/deployment-branch-policies` with
`{"name":"main","type":"branch"}`. Read back the exact environment and policy;
do not enable unprotected publishing. Self-review is allowed so the sole owner
can manually approve scheduled/owner-dispatched runs; admin bypass is not.
Pipeline verifies required reviewers and no admin bypass before and after approval.
An unavailable/forbidden API also blocks, never degrades to ungated publication.

## Reproduce / operate

```sh
python3 -m unittest discover -s scripts/core-ci -p 'test_*.py' -v
# from a separate scratch directory, with dist manifest path:
python3 /path/to/client/scripts/core-ci/pipeline.py select --pinned --root /path/to/dist
python3 /path/to/client/scripts/mihomo-build/build_all.py \
  --metadata mihomo.json --ndk "$ANDROID_HOME/ndk/27.1.12297006" \
  --work /new/scratch/mihomo --output /new/scratch/artifacts/mihomo
# same entry point/parameters for xray-last-build

gh workflow run upstream-jni.yml -R instant992/ghostcloudcore_new \
  --ref main -f dry_run=true -f publish=false
```
Builds use host functional tests (Xray tests import the upstream runtime without
Android JNI glue). Go starts at 1.26.7 and auto-selects newer toolchains required
by the resolved modules. Windows cross-building and Linux CI use the same pipeline. Android smoke needs SDK platform/build-tools 35 and rooted x86_64 emulator.
No APK/UI build or production subscription credentials are involved.
