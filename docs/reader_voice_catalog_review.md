# Voice catalog research — pending integration

Read-only upstream review on 2026-09-06. **No package download, license acceptance,
model installation or catalog edit was performed.** This is a resume note, not
completed T2 catalog acceptance. Verify licensing/layout before offering an entry.

## Existing reusable Kokoro catalog

`models/catalog.kokoro.json` already defines `kokoro-en-v1_0-af-heart`, including
the supported asset paths, speaker ID 3 and US English lexicon. Do not invent a
new backend or downgrade to v0.19. The default `models/catalog.json` currently
has only Lessac Medium; the local bridge intentionally reads that fixed catalog.

The primary [sherpa-onnx release API](https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/tts-models)
reported these exact archive metadata values:

- `kokoro-multi-lang-v1_0.tar.bz2`: 349,418,188 bytes;
  SHA-256 `c133d26353d776da730870dac7da07dbfc9a5e3bc80cc5e8e83ab6e823be7046`.
  Matches the existing separate Kokoro catalog.
- `kokoro-int8-multi-lang-v1_0.tar.bz2`: 131,839,838 bytes;
  SHA-256 `75654a84864be26f345f020f4070c2c019e96dd1b7f9bf6e2ffd59efac6aa5a3`.

Primary metadata/layout sources:

- [sherpa-onnx Kokoro documentation](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html)
  describes v1.0's speaker IDs 0–52 and supported English/Chinese paths.
- [upstream export workflow](https://github.com/k2-fsa/sherpa-onnx/blob/master/.github/workflows/export-kokoro.yaml)
  shows the archive root, `model.onnx` versus `model.int8.onnx`, shared
  `voices.bin`, `tokens.txt`, lexicons, dictionaries and espeak data.
- [original model card](https://huggingface.co/hexgrad/Kokoro-82M) is the model
  provenance/license source; do not infer voice terms from the sherpa code license.

Review bundle component licenses as well as model terms. Preserve the existing
user-installed FP32/INT8 heart voices; do not overwrite their manifest entries
or download the same package just to pass a test. Adding more registered speakers
to already installed shared assets needs explicit validation and must not be
disguised as replacing a package.

## Potential Danish Piper entry

The same release API reports `vits-piper-da_DK-talesyntese-medium.tar.bz2`:
67,185,257 bytes; SHA-256
`f2e2cbcdb2b21e76f93635b35105d07b37997ace434d7289d04b689a97c19bd0`.

The [voice-specific model card](https://huggingface.co/rhasspy/piper-voices/blob/main/da/da_DK/talesyntese/medium/MODEL_CARD)
states Danish, one speaker, medium quality and 22,050 Hz. It labels its **dataset**
CC0 and notes fine-tuning from the US Lessac voice. Do not silently relabel the
whole archive/model as CC0 or infer its terms from a repository-level MIT label.
Confirm the applicable voice/model terms and archive layout before integrating.
The general sherpa vits page does not document this specific archive's file list.

No claim about audible quality or native model readiness has been made from
these metadata reads. Installation checks and a permitted preview are separate.
