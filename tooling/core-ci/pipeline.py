"""Fail-closed JNI build/distribution tools; stdlib only (Python 3.10+)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import urllib.request

CORES = {
    'mihomo': ('MetaCubeX/mihomo', 'github.com/metacubex/mihomo', 'mihomo-build', 'libclash.so', 'GcCore'),
    'xray-last': ('XTLS/Xray-core', 'github.com/xtls/xray-core', 'xray-last-build', 'libxraylast.so', 'GcXrayLastCore'),
}
ABIS = {'arm64-v8a': ('arm64', 'aarch64-linux-android21', 2, 183),
        'armeabi-v7a': ('arm', 'armv7a-linux-androideabi21', 1, 40),
        'x86': ('386', 'i686-linux-android21', 1, 3),
        'x86_64': ('amd64', 'x86_64-linux-android21', 2, 62)}
NEEDLE = 'nativeTun = &NativeTun{\n\t\t\ttunFd:   options.FileDescriptor,\n\t\t\ttunFile: os.NewFile(uintptr(options.FileDescriptor), "tun"),'
REPLACEMENT = 'ownedFd, err := unix.Dup(options.FileDescriptor)\n\t\tif err != nil { return nil, err }\n\t\tnativeTun = &NativeTun{\n\t\t\ttunFd:   ownedFd,\n\t\t\ttunFile: os.NewFile(uintptr(ownedFd), "tun"),'


def run(*args, cwd=None, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True).strip()


def api(path):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'ghostcloud-core-ci'}
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com/' + path, headers=headers), timeout=60) as response:
        return json.load(response)


def resolve(core, tag=None):
    repo = CORES[core][0]
    releases = api('repos/' + repo + '/releases?per_page=100')
    allowed = [r for r in releases if not r['draft'] and (core != 'mihomo' or not r['prerelease'])
               and re.fullmatch(r'v\d+\.\d+\.\d+', r['tag_name'])]
    if tag:
        allowed = [r for r in allowed if r['tag_name'] == tag]
    if not allowed:
        raise RuntimeError('No allowed published release: ' + str(tag))
    release = max(allowed, key=lambda r: tuple(map(int, r['tag_name'][1:].split('.'))))
    tag = release['tag_name']
    refs = run('git', 'ls-remote', 'https://github.com/' + repo + '.git', 'refs/tags/' + tag, 'refs/tags/' + tag + '^{}').splitlines()
    mapping = {line.split()[1]: line.split()[0] for line in refs}
    sha = mapping.get('refs/tags/' + tag + '^{}', mapping.get('refs/tags/' + tag))
    if not sha or not re.fullmatch('[a-f0-9]{40}', sha):
        raise RuntimeError('Tag did not resolve to an exact commit')
    return {'version': tag[1:], 'upstream': repo, 'tag': tag, 'commit': sha, 'prerelease': release['prerelease']}


def patch_tun(text):
    if text.count(NEEDLE) != 1 or 'unix.Dup(options.FileDescriptor)' in text:
        raise RuntimeError('Unsupported sing-tun FD ownership; manual review required')
    return text.replace(NEEDLE, REPLACEMENT)


def patch_gvisor_dispatchers(text):
    """Close dispatcher-owned stop eventfds after readers/processors exit.

    Attach(nil) stops and joins dispatchLoop, which invokes release exactly
    once. The data FD is owned by sing-tun and must NOT be closed here.
    """
    needles = (
        'func (d *readVDispatcher) release() {\n\td.buf.release()\n\td.mgr.close()\n}',
        'func (d *recvMMsgDispatcher) release() {\n\tfor _, iov := range d.bufs {\n\t\tiov.release()\n\t}\n\td.mgr.close()\n}',
    )
    if any(text.count(needle) != 1 for needle in needles) or 'unix.Close(d.EFD)' in text:
        raise RuntimeError('Unsupported gVisor stopfd ownership; manual review required')
    for needle in needles:
        text = text.replace(needle, needle.replace('release() {\n', 'release() {\n\tdefer unix.Close(d.EFD)\n', 1))
    return text


def validate_elf(path, abi, core, nm):
    data = path.read_bytes()
    _, _, cls, machine = ABIS[abi]
    if data[:6] != b'\x7fELF' + bytes([cls, 1]) or struct.unpack_from('<HH', data, 16) != (3, machine):
        raise RuntimeError('Wrong ELF class/endian/type/machine: ' + str(path))
    if cls == 2:
        phoff = struct.unpack_from('<Q', data, 32)[0]
        phsize, phnum = struct.unpack_from('<HH', data, 54)
        fmt = '<IIQQQQQQ'
    else:
        phoff = struct.unpack_from('<I', data, 28)[0]
        phsize, phnum = struct.unpack_from('<HH', data, 42)
        fmt = '<IIIIIIII'
    loads = 0
    for i in range(phnum):
        ph = struct.unpack_from(fmt, data, phoff + i * phsize)
        if ph[0] != 1:
            continue
        loads += 1
        offset, address, align = (ph[2], ph[3], ph[7]) if cls == 2 else (ph[1], ph[2], ph[7])
        if align < 16384 or align & (align - 1) or offset % 16384 != address % 16384:
            raise RuntimeError('PT_LOAD is not 16KiB page compatible')
    if not loads:
        raise RuntimeError('ELF has no load segments')
    symbols = {line.split()[-1] for line in run(str(nm), '-D', '--defined-only', str(path)).splitlines()}
    required = {'Java_expo_modules_xraycore_' + CORES[core][4] + '_' + name for name in ['gcInit', 'gcStart', 'gcStop', 'gcVersion']}
    if not required <= symbols:
        raise RuntimeError('Missing JNI symbols: ' + str(required - symbols))
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def build(core, metadata, wrappers, work, output, ndk, go):
    """All mutable source/module edits are isolated in a fresh working directory."""
    info = json.loads(metadata.read_text())
    if info['upstream'] != CORES[core][0] or not re.fullmatch(r'v\d+\.\d+\.\d+', info['tag']) or not re.fullmatch('[a-f0-9]{40}', info['commit']):
        raise RuntimeError('Invalid pinned source metadata')
    if info['version'] != info['tag'][1:] or (core == 'mihomo' and info['prerelease']):
        raise RuntimeError('Release channel mismatch')
    work.mkdir(parents=True, exist_ok=False)
    source = work / 'upstream'
    run('git', 'init', str(source))
    run('git', '-C', str(source), 'remote', 'add', 'origin', 'https://github.com/' + info['upstream'] + '.git')
    run('git', '-C', str(source), 'fetch', '--depth=1', 'origin', 'refs/tags/' + info['tag'])
    run('git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD')
    if run('git', '-C', str(source), 'rev-parse', 'HEAD') != info['commit'] or run('git', '-C', str(source), 'status', '--porcelain'):
        raise RuntimeError('Tag changed or checkout not clean')
    wrapper = work / 'wrapper'
    shutil.copytree(wrappers / CORES[core][2], wrapper, ignore=shutil.ignore_patterns('__pycache__'))
    # Start from the upstream graph, not stale indirect wrapper pins or local replacements.
    module = CORES[core][1]
    upstream_mod = (source / 'go.mod').read_text()
    version = re.search(r'^go (\S+)', upstream_mod, re.M).group(1)
    (wrapper / 'go.mod').write_text(f'module ghostcloud/{core}-jni\n\ngo {version}\n\nrequire {module} v0.0.0\n\nreplace {module} => {source.as_posix()}\n')
    # Dependency replace directives are not inherited by Go's main module.
    graph = json.loads(run(go, 'mod', 'edit', '-json', cwd=source))
    for replacement in graph.get('Replace') or []:
        old, new = replacement['Old'], replacement['New']
        left = old['Path'] + ('@' + old['Version'] if old.get('Version') else '')
        right = new['Path'] + ('@' + new['Version'] if new.get('Version') else '')
        if not new.get('Version'):
            target = (source / new['Path']).resolve()
            if not target.is_relative_to(source.resolve()):
                raise RuntimeError('Upstream replacement escapes checkout')
            right = target.as_posix()
        run(go, 'mod', 'edit', '-replace=' + left + '=' + right, cwd=wrapper)
    run(go, 'mod', 'tidy', cwd=wrapper)
    if core == 'mihomo':
        tun = json.loads(run(go, 'list', '-m', '-json', 'github.com/metacubex/sing-tun', cwd=wrapper))
        local = work / 'sing-tun'
        shutil.copytree(tun['Dir'], local)
        target = local / 'tun_linux.go'
        target.chmod(0o644)
        target.write_text(patch_tun(target.read_text()))
        run(go, 'mod', 'edit', '-replace=github.com/metacubex/sing-tun=' + local.as_posix(), cwd=wrapper)
        gvisor = json.loads(run(go, 'list', '-m', '-json', 'github.com/metacubex/gvisor', cwd=wrapper))
        local_gvisor = work / 'gvisor'
        shutil.copytree(gvisor['Dir'], local_gvisor)
        dispatchers = local_gvisor / 'pkg/tcpip/link/fdbased/packet_dispatchers.go'
        dispatchers.chmod(0o644)
        dispatchers.write_text(patch_gvisor_dispatchers(dispatchers.read_text()))
        run(go, 'mod', 'edit', '-replace=github.com/metacubex/gvisor=' + local_gvisor.as_posix(), cwd=wrapper)
        run(go, 'mod', 'tidy', cwd=wrapper)
    run(go, 'mod', 'verify', cwd=wrapper)
    host_env = dict(os.environ, CGO_ENABLED='0' if os.name == 'nt' else '1')
    # Xray JNI contains Android/POSIX FD calls; host tests import the same
    # upstream runtime without compiling Android JNI glue on the host.
    targets = ['main.go', 'main_test.go']
    print(run(go, 'test', '-v', '-count=1', '-timeout=180s', '-ldflags=-checklinkname=0', *targets, cwd=wrapper, env=host_env), flush=True)
    prebuilt = ndk / 'toolchains/llvm/prebuilt' / ('windows-x86_64' if os.name == 'nt' else 'linux-x86_64') / 'bin'
    suffix = '.exe' if os.name == 'nt' else ''
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    # Run-scoped immutable paths: existing published tag directories are NEVER overwritten.
    directory = f"cores/{core}-{info['tag']}-{info['commit'][:12]}-{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    for abi, (arch, triple, _, _) in ABIS.items():
        path = output / directory / abi / CORES[core][3]
        path.parent.mkdir(parents=True, exist_ok=False)
        env = dict(os.environ, GOOS='android', GOARCH=arch, CGO_ENABLED='1', CC=str(prebuilt / (triple + '-clang' + ('.cmd' if os.name == 'nt' else ''))))
        env.pop('CGO_CFLAGS', None)
        if arch == 'arm':
            env['GOARM'] = '7'
        flags = '-s -w -checklinkname=0 -extldflags=-Wl,-z,max-page-size=16384'
        if core == 'mihomo':
            flags += ' -X github.com/metacubex/mihomo/constant.Version=' + info['tag']
        # The Android smoke and app request the gVisor TUN stack. Without this
        # tag sing-tun compiles its ErrGVisorNotIncluded stub instead.
        tags = ['-tags=with_gvisor'] if core == 'mihomo' else []
        print(run(go, 'build', '-p=4', *tags, '-buildmode=c-shared', '-trimpath', '-buildvcs=false', '-ldflags=' + flags, '-o', str(path), '.', cwd=wrapper, env=env), flush=True)
        files[abi] = dict(path=path.relative_to(output).as_posix(), **validate_elf(path, abi, core, prebuilt / ('llvm-nm' + suffix)))
        path.with_suffix('.h').unlink(missing_ok=True)
        print(abi, files[abi], flush=True)
    info['files'] = files
    info['build'] = {'run_id': os.environ.get('GITHUB_RUN_ID'), 'go': run(go, 'version'), 'ndk': (ndk / 'source.properties').read_text()}
    (output / 'manifest.json').write_text(json.dumps({'cores': {core: info}}, indent=2) + '\n')
    (output / 'resolved-go.mod').write_text((wrapper / 'go.mod').read_text())
    (output / 'resolved-go.sum').write_text((wrapper / 'go.sum').read_text())


def checked_files(root, core, entry):
    if set(entry['files']) != set(ABIS):
        raise RuntimeError('Must contain all four ABIs')
    result = []
    for abi, meta in entry['files'].items():
        relative = Path(meta['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'cores' or not relative.parts[1].startswith(core + '-') or relative.parts[-2:] != (abi, CORES[core][3]):
            raise RuntimeError('Unsafe artifact path')
        path = root / relative
        data = path.read_bytes()
        if len(data) != meta['size'] or hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise RuntimeError('Artifact checksum mismatch: ' + str(path))
        result.append((relative, path))
    return result


def merge(repo, artifacts, selection):
    manifest = json.loads((repo / 'manifest.json').read_text())
    original = json.loads(json.dumps(manifest))
    planned = []
    for core in selection['cores']:
        entry = json.loads((artifacts / core / 'manifest.json').read_text())['cores'][core]
        pin = selection['cores'][core]
        if any(entry[k] != pin[k] for k in ['version', 'tag', 'commit', 'upstream', 'prerelease']):
            raise RuntimeError('Artifact provenance does not match selection')
        # A newer/different publication since selection makes this run stale.
        if manifest['cores'].get(core) != selection['baseline']['cores'].get(core):
            raise RuntimeError('Stale publication; rerun selection')
        for relative, source in checked_files(artifacts / core, core, entry):
            if (repo / relative).exists():
                raise RuntimeError('Immutable path already exists')
            planned.append((repo / relative, source))
        manifest['cores'][core] = entry
    for core, entry in original['cores'].items():
        if core not in selection['cores'] and manifest['cores'][core] != entry:
            raise RuntimeError('Other core changed')
    # Validate ALL inputs before touching any distribution file.
    for target, source in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (repo / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def gate(repo):
    env = api('repos/' + repo + '/environments/core-production')
    reviewers = [rule for rule in env.get('protection_rules', []) if rule['type'] == 'required_reviewers' and rule.get('reviewers')]
    if not reviewers or env.get('can_admins_bypass', True):
        raise RuntimeError('Publication blocked: required reviewers and no admin bypass must be configured')
    return env


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['select', 'build', 'merge', 'gate', 'readback'])
    p.add_argument('--core', choices=CORES)
    p.add_argument('--tag')
    p.add_argument('--repo', default='instant992/ghostcloudcore_new')
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--selection', type=Path, default=Path('selection.json'))
    p.add_argument('--metadata', type=Path)
    p.add_argument('--wrappers', type=Path)
    p.add_argument('--work', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--ndk', type=Path)
    p.add_argument('--go', default='go')
    p.add_argument('--pinned', action='store_true')
    args = p.parse_args()
    if args.command == 'gate':
        gate(args.repo)
    elif args.command == 'select':
        baseline = json.loads((args.root / 'manifest.json').read_text())
        cores = {}
        for core in CORES:
            info = resolve(core, baseline['cores'][core]['tag'] if args.pinned else None)
            if args.pinned or any(info[k] != baseline['cores'][core].get(k) for k in ['tag', 'commit']):
                cores[core] = info
                Path(core + '.json').write_text(json.dumps(info, indent=2) + '\n')
        args.selection.write_text(json.dumps({'cores': cores, 'baseline': baseline}, indent=2) + '\n')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write('matrix=' + json.dumps({'core': list(cores)}) + '\nchanged=' + str(bool(cores)).lower() + '\n')
    elif args.command == 'build':
        build(args.core, args.metadata.resolve(), args.wrappers.resolve(), args.work.resolve(), args.output.resolve(), args.ndk.resolve(), args.go)
    elif args.command == 'merge':
        merge(args.root, args.output, json.loads(args.selection.read_text()))
    else:
        commit = run('git', '-C', str(args.root), 'rev-parse', 'HEAD')
        expected = json.loads((args.root / 'manifest.json').read_text())
        prefix = f'https://raw.githubusercontent.com/{args.repo}/{commit}/'
        with urllib.request.urlopen(prefix + 'manifest.json', timeout=60) as r:
            if json.load(r) != expected:
                raise RuntimeError('Remote manifest mismatch')
        for core in json.loads(args.selection.read_text())['cores']:
            for meta in expected['cores'][core]['files'].values():
                with urllib.request.urlopen(prefix + meta['path'], timeout=180) as r:
                    data = r.read()
                if len(data) != meta['size'] or hashlib.sha256(data).hexdigest() != meta['sha256']:
                    raise RuntimeError('Remote artifact mismatch')
        print('REMOTE_MANIFEST_AND_ALL_ARTIFACTS_VERIFIED', commit)


if __name__ == '__main__':
    main()
