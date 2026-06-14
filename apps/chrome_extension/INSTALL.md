# Local Chrome Extension Install

This extension is a local handoff build for the TTS Platform localhost reader.
It is not Chrome Web Store signed.

## Load Unpacked

1. Prepare the local service:

   - From the extracted Windows bundle, run:

     ```powershell
     .\scripts\windows\install_local.ps1
     ```

     This creates `.venv`, installs the local package, and runs first-run
     `tts setup-local`. Use
     `.\scripts\windows\install_local.ps1 -InstallRealRuntime` when this
     machine should also install the optional `.[real]` runtime dependencies in
     the same `.venv`.

   - From an already installed development checkout, run:

     ```powershell
     tts setup-local
     ```

     You can also use `scripts\windows\run_service.ps1 -SetupOnly` when you
     want the source launcher to create `config\config.toml` and
     `config\token.txt` without starting the foreground service.

2. Start the local service with `scripts\windows\run_service.ps1`.
3. Open `chrome://extensions`.
4. Enable Developer Mode.
5. Choose `Load unpacked`.
6. Select the extracted `apps\chrome_extension` directory.
7. Open the extension popup and copy the `Allow-List Command`.
8. Run the command to update `security.allowed_origins`:

   ```powershell
   tts extension-allow-origin <copied-origin>
   ```

   If you are using the extracted Windows bundle and `tts` is not on `PATH`,
   run the same command through the bundled virtual environment:

   ```powershell
   .\.venv\Scripts\tts.exe extension-allow-origin <copied-origin>
   ```

9. Restart the local service.
10. Save the token from `config\token.txt` in the popup.
11. Refresh service status and confirm the setup checklist is all `[ok]`.

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
