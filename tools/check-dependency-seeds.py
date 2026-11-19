#!/usr/bin/env python3
"""Verify seed files and setup run on cold, cached and repaired dependency checkouts."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('dependency_fetcher', root / 'tools/deps.py')
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)
manifest = {i['name']: i for i in deps.MANIFEST['items']}
assert manifest['boilerplate']['seeds'] == manifest['ps5-vulkan-tools']['seeds']

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    upstream = base / 'upstream'
    upstream.mkdir()
    git('init', '-q', str(upstream))
    (upstream / 'README').write_text('test dependency\n')
    git('-C', str(upstream), 'add', 'README')
    git('-C', str(upstream), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    revision = git('-C', str(upstream), 'rev-parse', 'HEAD')
    archive = base / 'zlib-test.tar.gz'
    contents = b'verified test archive\n'
    archive.write_bytes(contents)
    deps.ROOT = base / 'checkout'
    deps.CACHE = base / 'cache'
    deps.ROOT.mkdir()
    for name in ('boilerplate', 'ps5-vulkan-tools'):
        item = copy.deepcopy(manifest[name])
        item.update(name=name, path=name, url=upstream.as_uri(), commit=revision)
        item['seeds'][0].update(url=archive.as_uri(), sha256=hashlib.sha256(contents).hexdigest())
        item['setup_creates'] = 'setup-done'
        seed_path = item['seeds'][0]['file']
        item['setup'] = [sys.executable, '-c',
            f'from pathlib import Path; assert Path({seed_path!r}).read_bytes() == {contents!r}; Path("setup-done").touch()']
        target = deps.ROOT / name
        deps.fetch_git(item)
        assert (target / seed_path).read_bytes() == contents
        assert (target / 'setup-done').exists()
        # A bundle contains tracked source, not the seed or the setup result.
        shutil.rmtree(target)
        item['url'] = 'file:///nonexistent-upstream'
        deps.fetch_git(item)
        assert (target / seed_path).read_bytes() == contents
        assert (target / 'setup-done').exists()
        # Both a corrupt seed and a corrupt download cache are repaired.
        (target / seed_path).write_bytes(b'bad seed')
        (deps.CACHE / archive.name).write_bytes(b'bad cache')
        deps.fetch_git(item)
        assert (target / seed_path).read_bytes() == contents
        print(f'PASS: {name}: cold fetch, offline bundle restore, setup, corrupt seed/cache repair')
