# Local Chrome Extension Install

This extension is a local handoff build for the TTS Platform localhost reader.
It is not Chrome Web Store signed.

## Load Unpacked

1. Start first-run setup with `scripts\windows\run_service.ps1 -SetupOnly`.
2. Open `chrome://extensions`.
3. Enable Developer Mode.
4. Choose `Load unpacked`.
5. Select the extracted `apps\chrome_extension` directory.
6. Open the extension popup and copy the extension origin.
7. Add that origin to the local service `security.allowed_origins` allow-list:

   ```powershell
   .\.venv\Scripts\tts.exe extension-allow-origin <copied-origin>
   ```

   If the editable checkout is already active in your shell, use:

   ```powershell
   tts extension-allow-origin <copied-origin>
   ```

8. Restart the local service.
9. Save the token from `config\token.txt` in the popup.
10. Refresh service status and confirm the setup checklist is all `[ok]`.

## Packaged Zip

`scripts\package_extension.py` creates `dist\chrome_extension\tts-platform-prototype.zip`
with `manifest.json` at the archive root. For local testing, extract that zip
and load the extracted directory with `Load unpacked`.

## First Playback Check

1. Open a normal article page.
2. Select a short sentence and choose `Speak Selection`.
3. Choose `Speak Page` for a longer page.
4. Confirm the popup shows reader progress and page-capture metadata.
5. Stop playback and confirm a new playback request can start cleanly.
