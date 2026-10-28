# PyInstaller spec — build on Windows:  pyinstaller jarvis_desktop.spec
# Produces dist\JarvisDesktop\JarvisDesktop.exe (one-folder build; starts faster than one-file).
block_cipher = None

a = Analysis(
    ["run_jarvis_desktop.py"],
    pathex=["."],
    datas=[("allowlist.example.json", ".")],
    hiddenimports=["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "keyring.backends.Windows"],
    excludes=["tkinter"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JarvisDesktop", console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="JarvisDesktop")
