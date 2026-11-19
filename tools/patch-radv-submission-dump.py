#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Port Oliv3rmoon/Belladonna 318deb146daa's FF GPU stall report to the pinned driver.
No engine/driver revision changes. The report runs only after the existing ten-second stall.
"""
from pathlib import Path
import hashlib, re, subprocess, sys
root = Path(__file__).resolve().parents[1]
patch = root / 'tools/radv-submission-dump.diff'
fingerprint = hashlib.sha256(Path(__file__).read_bytes() + patch.read_bytes()).hexdigest()
if sys.argv[1:2] == ['--digest']:
    print(fingerprint); raise SystemExit(0)
if sys.argv[1:2] == ['--check']:
    stamp = Path(sys.argv[2])
    raise SystemExit(0 if stamp.is_file() and stamp.read_text().strip() == fingerprint else 1)
source = Path(sys.argv[1]) if len(sys.argv) > 1 else root.parent / 'mihawk-vulkan-review/.deps/work/radv-src'
# WSI preparation regenerates some driver files from the pinned checkout. Others
# retain adaptations. Validate all file patches first, then apply only missing files.
# A reverse dry run uses --force so patch cannot silently switch direction.
missing = []
for chunk in re.split(r'(?=^diff --git )', patch.read_text(), flags=re.M)[1:]:
    command = ['patch', '--batch', '--fuzz=0', '-p1']
    if subprocess.run(command + ['--dry-run', '--reverse', '--force'], input=chunk, text=True,
                      cwd=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        continue
    subprocess.run(command + ['--dry-run', '--forward'], input=chunk, text=True, cwd=source, check=True)
    missing.append(chunk)
for chunk in missing:
    subprocess.run(command + ['--forward'], input=chunk, text=True, cwd=source, check=True)
if not missing:
    print('RADV stall diagnostics: already applied'); raise SystemExit(0)
provenance = root.parent / 'mihawk-vulkan-review/.deps/native/radv-release/PROVENANCE.txt'
if provenance.exists(): provenance.replace(provenance.with_suffix('.base.txt'))
