# Reader MP3 export

Reader exports WAV directly and can encode the same persistent export job as an
MP3 when a compatible local FFmpeg command is available. The desktop obtains
the ready formats from `/v1/reader/capabilities`; it does not show MP3 merely
because MP3 appears in configuration.

## Installation and configuration

FFmpeg is an optional system dependency and is not included in this repository,
the Windows portable bundle, or the Reader executable. Reader discovers
`ffmpeg` on `PATH` by default. An explicit executable may instead be configured
with an absolute path:

```toml
[reader.exports]
enabled = true
output_directory = "./data/exports"
max_concurrent_exports = 1
formats = ["wav", "mp3"]
ffmpeg_path = "C:/Tools/ffmpeg/bin/ffmpeg.exe"
mp3_bitrate_kbps = 96
```

The service performs a five-second `ffmpeg -version` identity probe. A missing,
invalid, or unresponsive command removes MP3 from the advertised formats while
leaving WAV export operational. Bitrate accepts 32 through 320 kbps; Reader's
default is 96 kbps mono.

Completed files remain in the configured service export directory. For a
single-article job, select the completed row in **Audio exports** and choose
**Save selected as...** to stream a copy to any user-selected folder. The
desktop also writes this copy to a temporary sibling file before publishing it,
so a failed download does not leave a file that looks complete.

## Execution and data handling

- The service synthesizes the article into a private temporary WAV, then runs
  FFmpeg with a fixed argument array and `shell=False`.
- User text is never accepted as an executable path or command fragment. Only
  the article title is supplied as an MP3 metadata value in its own argument.
- Source text, title, token, FFmpeg path, and output paths are not written to
  application logs.
- Cancellation terminates the encoder process and deletes incomplete WAV/MP3
  temporary files.
- The MP3 is first written beside the destination as a temporary file and is
  published with the same no-overwrite/atomic completion rules as WAV.
- The MP3 contains title and a generic Reader generator comment, but no article
  body text or source path.

## Distribution and licensing boundary

The project invokes a user-installed FFmpeg executable as a separate process;
it does not distribute FFmpeg binaries or libraries. Anyone who later chooses
to bundle or redistribute FFmpeg must review the exact build configuration and
comply with the applicable FFmpeg and included-codec licenses. FFmpeg's own
[legal and license guidance](https://ffmpeg.org/legal.html) is the authoritative
starting point. Bundling remains a separate product and licensing decision and
is not enabled by this feature.
