#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the adapted Nightshade codec regression with the actual Eden codecs/workers."""
from pathlib import Path
import subprocess
import sys
import tempfile
engine=Path(sys.argv[1]); root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    exe=Path(td)/'texture-transcode'
    includes=[engine/'src',engine/'externals/stb']
    includes+=sorted((engine/'.cache/cpm/boost').glob('*/libs/*/include'))
    sources=[root/'tools/check-texture-transcode.cpp',engine/'src/video_core/textures/astc.cpp',
             engine/'src/video_core/textures/bcn.cpp',engine/'externals/stb/stb_dxt.cpp']
    subprocess.run(['c++','-std=c++23','-O1','-g','-pthread','-fsanitize=address,undefined',
                    *['-I'+str(p) for p in includes],*[str(p) for p in sources],'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
