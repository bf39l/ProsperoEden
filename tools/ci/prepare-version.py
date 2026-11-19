#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare release metadata: prepare-version.py VERSION (for example 1.000.001)."""
import json
from pathlib import Path
import re
import sys


def versions(value):
    match = re.fullmatch(r'v?([0-9]{1,2})\.([0-9]{1,3})\.([0-9]{1,3})', value)
    if not match or not 1 <= int(match[1]) <= 99:
        raise ValueError('Use MAJOR.MINOR.PATCH: major 1–99, minor/patch 0–999; no prerelease suffix.')
    major, minor, patch = map(int, match.groups())
    return f'{major:02}.{minor:03}.{patch:03}', f'v{major}.{minor:03}.{patch:03}'


def prepare(root, value):
    package, tag = versions(value)
    path = root / 'sce_sys/param.json'
    document = json.loads(path.read_text())
    document['contentVersion'] = package
    path.write_text(json.dumps(document, indent=2) + '\n')
    path = root / 'README.md'
    readme = path.read_text()
    readme, count = re.subn(r'The current release is \*\*v[0-9.]+\*\*',
                           f'The current release is **{tag}**', readme)
    if count != 1:
        raise ValueError('README current release marker changed; review it before preparing a release.')
    readme = re.sub(r'docs/CHANGELOG\.md#v[0-9]+', f'docs/CHANGELOG.md#{tag.replace(".", "")}', readme)
    path.write_text(readme)
    path = root / 'docs/CHANGELOG.md'
    changelog = path.read_text()
    if not re.search(r'^## ' + re.escape(tag) + r'$', changelog, re.M):
        heading = re.search(r'^## ', changelog, re.M)
        if not heading:
            raise ValueError('No existing release heading in docs/CHANGELOG.md.')
        section = f'## {tag}\n\nRelease prepared from main. Review and complete these notes before merging.\n\n'
        changelog = changelog[:heading.start()] + section + changelog[heading.start():]
        path.write_text(changelog)
    return tag


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        print(prepare(Path(__file__).resolve().parents[2], sys.argv[1]))
    except ValueError as error:
        sys.exit(str(error))
