# Windows desktop app

**Status:** agent, local tools, voice logic and credentials are tested; GitHub Actions builds the
PySide6 window offscreen on Windows and produces `JarvisDesktop.exe` (download from Releases).
Not yet used interactively on a real desktop. Unzip it, put your `allowlist.json` in
`%APPDATA%\JarvisDesktop\`, and run `JarvisDesktop.exe`.

## Install & run (Python 3.11+)
```powershell
cd jarvis-ultimate\desktop
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q
mkdir $env:APPDATA\JarvisDesktop -Force
copy allowlist.example.json $env:APPDATA\JarvisDesktop\allowlist.json
notepad $env:APPDATA\JarvisDesktop\allowlist.json
python -m jarvis_desktop check-allowlist $env:APPDATA\JarvisDesktop\allowlist.json
python -m jarvis_desktop          # GUI
```
GUI: sign in → *This computer* tab → *Pair this computer…* → enter the code from the phone/web
Devices screen → approve the computer there → *Start agent*.

Headless (e.g. as a scheduled task at logon):
```powershell
python -m jarvis_desktop pair --backend https://your-backend --code ABCD-EFGH --name "Stark-PC"
python -m jarvis_desktop agent
```

## The allowlist (`%APPDATA%\JarvisDesktop\allowlist.json`)
- `applications`: name → exact `.exe` path. Only these can be opened; no arguments are ever passed.
- `folders`: name → folder. Documents can be read and files listed/organised only inside these
  (symlinks and `..` cannot escape).
- `notes_folder`: where notes are created (never overwrites).
- `enabled_actions`: remove any action you don't want at all.

There is intentionally no action to run commands, delete files, install software or use admin
rights. Organising files also requires the `files.organize` permission (off by default) and a
confirmation in the app.

## Voice
- Speech output: `pyttsx3` (Windows SAPI, offline). For Hindi voices install the Hindi speech pack
  (Settings → Time & language → Speech).
- Speech input: push-to-talk with `SpeechRecognition` + `PyAudio` (Google Web Speech; sends audio
  to Google). If either package is missing the UI says so and text still works.

## Build the .exe
```powershell
pip install pyinstaller
pyinstaller jarvis_desktop.spec
dist\JarvisDesktop\JarvisDesktop.exe
```
