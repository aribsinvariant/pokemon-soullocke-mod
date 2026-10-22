# Build on Windows with CPython 3.12/3.13, using the requirements beside this file.
from pathlib import Path

root = Path(SPECPATH).parents[1]
analysis = Analysis(
    [str(root / 'soullink/launcher/entry.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'soullink/bridge/bridge.lua'), 'soullink/bridge')],
    hiddenimports=['miniupnpc'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='SoulLink', debug=False, bootloader_ignore_signals=False, strip=False,
    upx=False, console=False, disable_windowed_traceback=False,
)
