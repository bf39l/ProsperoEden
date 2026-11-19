#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply the complete ordered Eden patch stack, rebuilding touched files when it changes."""
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def safe_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or '..' in path.parts or str(path) != name:
        raise ValueError(f'Unsafe patch path: {name}')
    return name


def apply(source, archive, patches):
    source = source.resolve()
    receipt = source / '.eden-patches-applied.json'
    with (source / '.eden-patches.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stack = {p.name: digest(p) for p in patches}
        try:
            previous = json.loads(receipt.read_text())
        except (OSError, ValueError):
            previous = {}
        files = {safe_path(line[6:].split('\t')[0]) for p in patches for line in p.read_text().splitlines()
                 if line.startswith('+++ b/')}
        created = set()
        for patch in patches:
            lines = patch.read_text().splitlines()
            for before, after in zip(lines, lines[1:]):
                if before.startswith('--- /dev/null') and after.startswith('+++ b/'):
                    created.add(safe_path(after[6:].split('\t')[0]))
        old_created = {safe_path(name) for name in previous.get('created', [])}
        old_files = previous.get('files', {})
        if (previous.get('patches') == stack and set(old_files) == files and
                all((source / name).is_file() and not (source / name).is_symlink() and
                    digest(source / name) == value for name, value in old_files.items())):
            print('Eden patches: unchanged verified stack', flush=True)
            return
        # Reset the UNION, not one patch's files at a time: later patches may build
        # on earlier hunks in the same file. CPM downloads and other source stay put.
        restore = files | {safe_path(name) for name in old_files}
        with tarfile.open(archive) as tar:
            members = {m.name.split('/', 1)[1]: m for m in tar.getmembers() if '/' in m.name}
            for name in sorted(restore):
                member = members.get(name)
                path = source / name
                if path.is_symlink():
                    raise ValueError(f'Refusing to replace symlink: {path}')
                if member is None and name in created | old_created:
                    path.unlink(missing_ok=True)
                    continue
                if member is None or not member.isfile():
                    raise ValueError(f'{name} is not a regular file in {archive}')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(tar.extractfile(member).read())
        for patch in patches:
            print(f'Eden patch: {patch.name}', flush=True)
            subprocess.run(['patch', '-d', str(source), '-p1', '-N', '--batch', '-s', '-i', str(patch.resolve())], check=True)
        result = {'patches': stack, 'created': sorted(created), 'files': {name: digest(source / name) for name in sorted(files)}}
        temporary = receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        temporary.replace(receipt)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: apply-eden-patches.py SOURCE PINNED_ARCHIVE')
    root = Path(__file__).resolve().parents[1]
    archive = Path(sys.argv[2])
    expected = json.loads((root / 'UPSTREAM.json').read_text())['archives'][archive.name]
    if digest(archive) != expected:
        sys.exit('Eden source archive does not match UPSTREAM.json')
    apply(Path(sys.argv[1]), archive, sorted((root / 'tools/eden-patches').glob('*.diff')))
