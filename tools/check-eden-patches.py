#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression for overlapping patches, repeated preparation and interrupted/changed trees."""
from pathlib import Path
import contextlib
import difflib
import importlib.util
import io
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('eden_patches', root / 'tools/apply-eden-patches.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def patch(path, old, new, target='file.txt'):
    path.write_text(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                              fromfile='a/' + target if old else '/dev/null',
                                              tofile='b/' + target)))

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    source = tmp / 'source'
    source.mkdir()
    archive = tmp / 'eden.tar.gz'
    original = tmp / 'file.txt'
    original.write_text('alpha\nbase\n')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(original, arcname='eden/file.txt')
    patches = [tmp / f'{i:02}.diff' for i in range(3)]
    patch(patches[0], 'alpha\nbase\n', 'alpha\none\n')
    patch(patches[1], 'alpha\none\n', 'alpha\ntwo\n')
    patch(patches[2], '', 'new file\n', 'new.h')
    module.apply(source, archive, patches)
    assert (source / 'file.txt').read_text() == 'alpha\ntwo\n'
    assert (source / 'new.h').read_text() == 'new file\n'
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        module.apply(source, archive, patches)
    assert 'unchanged verified stack' in output.getvalue()
    (source / 'file.txt').write_text('interrupted preparation\n')
    module.apply(source, archive, patches)
    assert (source / 'file.txt').read_text() == 'alpha\ntwo\n'
    patch(patches[1], 'alpha\none\n', 'alpha\nthree\n')
    module.apply(source, archive, patches)
    assert (source / 'file.txt').read_text() == 'alpha\nthree\n'
    module.apply(source, archive, patches[:1])
    assert (source / 'file.txt').read_text() == 'alpha\none\n'
    assert not (source / 'new.h').exists()
print('Eden patch stack PASS: overlapping changes, new files, repeat no-op, damaged tree, edited/removed patches')
