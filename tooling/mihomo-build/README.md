# mihomo Android JNI wrapper

The wrapper and runtime smoke tests are built by the portable, parameterized
`build_all.py` entry point. Source pin, output/work directories and NDK are
explicit parameters. See `../core-ci/README.md` for CI, provenance checks,
functional tests, publication protection and reproduction commands.

The pipeline never changes a published binary in-place. The client downloads
verified JNI libraries from `instant992/ghostcloudcore_new`, not upstream
command-line executable archives. Publication requires manual environment review.
