# Chrome prototype consolidation

Reader Workstation Milestone 9 evaluated the former
`Kajsing/Chrome-TTS-plugin` repository at commit
`6e56ceb95d6e675e0d9d6139c97578f9be47372c` (2025-09-20). The repository is
MIT licensed.

## Evaluated code and tests

- `extension/src/content/dom-utils.ts` and its tests serialize DOM ranges using
  child-node paths and offsets.
- `extension/src/content/sentence-extractor.ts` and its tests use
  `Intl.Segmenter` with a regex fallback and retain sentence ranges.
- `extension/src/content/highlight.ts` restores a serialized range but applies
  its CSS class to the range's common ancestor element.
- The old manifest requested broad host access and exposed packaged assets to
  all pages.

## Decision

No code was transplanted. The old tests demonstrate the basic range concept,
but the implementation highlights an entire common ancestor, does not implement
its specified DOM-mutation recovery, and uses node-index paths that become
stale when a page changes. The current extension already has stricter
localhost-only host permissions, bounded and filtered structured extraction,
long-page continuation, and playback progress from the canonical service.

Importing the old range layer would add a second source-position system beside
the Reader service without improving the current Milestone 9 acceptance path.
A future synchronized on-page highlighting milestone may revisit the MIT code
as reference, but should design against live DOM mutation and the current
service source-span contract rather than copy it unchanged.

The canonical implementation now lives in `apps/chrome_extension/` in this
repository. After the Milestone 9 integration and validation passed, commit
`2c547fe` updated the former repository README and its GitHub description to
mark it superseded and point to the supported client. The old repository stays
unarchived as a reversible historical reference.
