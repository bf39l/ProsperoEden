#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check release version mapping and metadata updates without modifying this checkout."""
import importlib.util
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_version', root / 'tools/ci/prepare-version.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for value, expected in {
    '1.000.000': ('01.000.000', 'v1.000.000'),
    'v1.2.3': ('01.002.003', 'v1.002.003'),
    '01.000.001': ('01.000.001', 'v1.000.001'),
    '26.011.018': ('26.011.018', 'v26.011.018'),
    '99.999.999': ('99.999.999', 'v99.999.999'),
}.items():
    assert module.versions(value) == expected
for value in ('0.0.0', '100.0.0', '1.1000.0', '1.0.-1', '1.0', '1.0.0-beta', '1.0.0\n', '$(echo 1).0.0'):
    try:
        module.versions(value)
    except ValueError:
        pass
    else:
        raise AssertionError(value)
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp)
    (fixture / 'sce_sys').mkdir()
    (fixture / 'docs').mkdir()
    (fixture / 'sce_sys/param.json').write_text(json.dumps({'contentVersion': '26.011.018', 'titleId': 'PPSA99018'}))
    (fixture / 'README.md').write_text('The current release is **v26.011.018**. [Notes](docs/CHANGELOG.md#v26011018).\n')
    (fixture / 'docs/CHANGELOG.md').write_text('# Changelog\n\n## v26.011.018\n\nOlder notes.\n')
    assert module.prepare(fixture, '1.000.000') == 'v1.000.000'
    param = json.loads((fixture / 'sce_sys/param.json').read_text())
    assert param == {'contentVersion': '01.000.000', 'titleId': 'PPSA99018'}
    assert '**v1.000.000**' in (fixture / 'README.md').read_text()
    assert 'docs/CHANGELOG.md#v1000000' in (fixture / 'README.md').read_text()
    assert (fixture / 'docs/CHANGELOG.md').read_text().count('## v1.000.000\n') == 1
    assert 'Older notes.' in (fixture / 'docs/CHANGELOG.md').read_text()
    first = {p.name: p.read_bytes() for p in fixture.rglob('*') if p.is_file()}
    module.prepare(fixture, 'v1.000.000')
    assert first == {p.name: p.read_bytes() for p in fixture.rglob('*') if p.is_file()}
# Exercise the actual ZIP/notes generator in an isolated checkout, never the real dist/.
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp)
    (fixture / 'tools/ci').mkdir(parents=True)
    (fixture / 'docs').mkdir()
    shutil.copyfile(root / 'tools/ci/make-dist.py', fixture / 'tools/ci/make-dist.py')
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/CHANGELOG.md'):
        shutil.copyfile(root / name, fixture / name)
    app = fixture / 'app'
    (app / 'sce_sys').mkdir(parents=True)
    package = json.loads((root / 'sce_sys/param.json').read_text())
    package['contentVersion'] = '01.000.000'
    (app / 'sce_sys/param.json').write_text(json.dumps(package))
    (app / 'eboot.bin').write_bytes(b'packaging test fixture')
    subprocess.run([sys.executable, str(fixture / 'tools/ci/make-dist.py'), str(app)],
                   check=True, capture_output=True, text=True)
    archive = fixture / 'dist/ProsperoEden-v1.000.000.zip'
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zipped:
        installed = json.loads(zipped.read('PPSA99018/sce_sys/param.json'))
        assert installed['contentVersion'] == '01.000.000'
        assert installed['localizedParameters']['en-US']['titleName'] == 'ProsperoEden'
    assert (fixture / 'dist/SHA256SUMS').read_text().endswith('  ProsperoEden-v1.000.000.zip\n')
    assert 'First release under' in (fixture / 'dist/release-notes.md').read_text()
param = json.loads((root / 'sce_sys/param.json').read_text())
assert param['localizedParameters']['en-US']['titleName'] == 'ProsperoEden'
print('Release versions PASS: PS5 padding, canonical tag, invalid inputs, metadata, preserved history and repeat preparation')
