# Kokoro v1.0 US voice bundles — package review

Reviewed 2026-09-06. These are optional, unmodified upstream downloads, not
models shipped inside the Reader executable. Installing them does not change
the project's license. This page distinguishes model licensing from bundled
components; it is not a blanket Apache license for the whole archive or a
redistribution clearance.

## What gets installed

The menu offers 20 US English speakers from the existing sherpa-onnx Kokoro
v1.0 workflow. FP32 and INT8 use the same speaker map; INT8 is a smaller
quantized model, not an assurance of identical pronunciation or better latency.
Use Preview after an explicit idle-service restart to compare them.

| Package | Exact download bytes | SHA-256 |
| --- | ---: | --- |
| `kokoro-multi-lang-v1_0.tar.bz2` (FP32) | 349418188 | `c133d26353d776da730870dac7da07dbfc9a5e3bc80cc5e8e83ab6e823be7046` |
| `kokoro-int8-multi-lang-v1_0.tar.bz2` | 131839838 | `75654a84864be26f345f020f4070c2c019e96dd1b7f9bf6e2ffd59efac6aa5a3` |

Sizes/hashes are pinned from the [publisher's release metadata](https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/tts-models).
The installer verifies the archive's actual SHA-256 before extraction. See the
[publisher's layout and speaker map](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html#kokoro-multi-lang-v1-0-chinese-english-53-speakers)
and [export workflow](https://github.com/k2-fsa/sherpa-onnx/blob/master/.github/workflows/export-kokoro.yaml).

These catalog bundles have new package IDs and separate directories. Each is a
full download even if an older single-voice Kokoro installation exists. The 20
voices share files within their bundle, not with older installations. This
deliberately avoids overwriting or silently adopting existing assets. No automatic
cleanup or migration of old voices occurs. Disk use after extraction is larger
than the download. The UI's size is download size, not total disk/RAM use.

## License and attribution sources to review

- **Kokoro weights and voice tensors:** the author's [model card](https://huggingface.co/hexgrad/Kokoro-82M)
  declares Apache-2.0 and explains training provenance; read the
  [Apache-2.0 terms](https://www.apache.org/licenses/LICENSE-2.0).
  Retain its training-data attributions, including Koniwa (CC BY 3.0) and SIWIS
  (CC BY 4.0), as listed on that model card. The model's license is not inferred
  from sherpa-onnx's code license.
- **English pronunciation lexicons:** the [v1.0 conversion script](https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/kokoro/v1.0/run.sh)
  obtains Misaki English gold/silver dictionaries. Review [Misaki's Apache-2.0 license](https://github.com/hexgrad/misaki/blob/main/LICENSE)
  and preserve the upstream notices and source references.
- **eSpeak NG data:** the archive includes `espeak-ng-data`, used for fallback
  phonemization. Review [eSpeak NG's GPL license](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING)
  and [component/source licensing information](https://github.com/espeak-ng/espeak-ng).
  These data are not relicensed Apache-2.0 by being bundled with Kokoro.
- **Additional multilingual files:** the publisher also includes Chinese lexicon,
  FST and dictionary files. This US-only catalog does not configure those files,
  but extraction retains the original archive and notices. The export workflow
  links their source repositories. See also [cppjieba's license](https://github.com/yanyiwu/cppjieba/blob/master/LICENSE).
  Do not assume a repository's top-level code license covers every contributed
  dictionary; review the actual bundled/source notices before redistribution.
- **Conversion runtime:** [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE)
  uses Apache-2.0. Reader's existing runtime notices remain in
  [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

Accepting the menu checkbox is your explicit decision to install the selected
package after reviewing its terms. It does not authorize Reader to accept terms
for a different package, change a running engine, or redistribute model files.
If publishing a bundle containing models or modified components, separately
review attribution, source-availability and other applicable requirements.

## Supported voices and limits

The 20 registered IDs follow the publisher's mapping 0–19:
`af_alloy`, `af_aoede`, `af_bella`, `af_heart`, `af_jessica`, `af_kore`,
`af_nicole`, `af_nova`, `af_river`, `af_sarah`, `af_sky`, `am_adam`,
`am_echo`, `am_eric`, `am_fenrir`, `am_liam`, `am_michael`, `am_onyx`,
`am_puck`, `am_santa`. They use the US English lexicon at 24 kHz.

The archive contains other speaker IDs, but this first catalog does not register
unsupported language paths or claim Danish support from Kokoro. The proposed
Danish Piper entry is deferred: its card describes the dataset as CC0 and
fine-tuning from Lessac, which is insufficient here to label the complete model
and archive as CC0. Existing manually installed voices are not removed.
