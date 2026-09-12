# Audiobook production - parked epic

Status: **PARKED / NOT STARTED**. Recorded at the user's request on 2026-09-13.

This is a plan for later, not an active milestone or authorization to implement
it now. Resume only when the user is satisfied with current Reader work and
explicitly chooses to activate this track. Do not automatically start it when
another milestone finishes. It does not replace the existing reliability work,
deferred append-performance measurement, or parked U8/SAPI work.

Background discussion: https://chatgpt.com/share/6aa5cb51-aac0-83eb-b759-1ff1a1a9f516
That conversation is design input, not verified evidence of current model
capabilities, licensing, hardware requirements, or repository behavior.

## Confirmed direction

- Produce a finished audiobook offline, potentially with a narrator, character
  voices, expressive delivery, and later ambience, sound effects and music.
- Real-time dramatized playback is not a requirement. Generation can take time;
  quality, reproducibility and recovery matter more than immediate output.
- Preserve the working everyday Reader. Normal Play must not depend on an LLM,
  manuscript conversion, new voice engine, or audio-production job.
- Begin with one short chapter as a pilot, but design for persistent characters,
  chapters and revisions across a whole book, including books split into several
  Reader articles. A production project references an ordered set of snapshots;
  it does not require merging articles or raising Reader display limits.
- Default to faithful, unabridged spoken text. Rewriting, abridging or removing
  narration because a sound effect represents it requires a separate decision.
- Keep models and assets replaceable. Qwen and the sound/music models mentioned
  in the discussion are candidates, not selected dependencies.

## Ownership and boundaries

Proposed data flow:

`Reader snapshots -> ManuscriptBundle -> AudioScenePlan -> render jobs -> mix/export`

- Reader owns canonical text and chapter structure. Production starts from an
  immutable, authorized snapshot with source IDs, revisions and hashes.
- The manuscript describes textual structure and evidence: narration, dialogue,
  thoughts, quoted material, characters, scenes and explicit delivery cues.
- The director chooses casting, performance, pacing and optional sound design.
- Generators create reusable audio assets; the mixer assembles their actual
  durations into the final timeline and exports the result.
- Source text, manuscript units, semantic utterances, backend chunks and audio
  events are distinct concepts. Do not overload the current playback chunk type.
- Storage/API and worker-process details remain to be designed during activation.
  Do not add an alternative writer to Reader's database, bypass folder/privacy
  controls, or expose owner credentials to manuscript or asset-search agents.
- Work on snapshots without a long-lived reading lease. If the source changes,
  label the production as based on an older revision and require explicit refresh;
  never silently mix revisions or overwrite the user's article.

## Proposed milestones and acceptance gates

All implementation checkboxes intentionally remain open.

### AB0 - scope and source contract

- [ ] Select a short, authorized pilot and confirm output expectations, narrator
  and cast size, quality target, and a user-approved token/time/resource budget.
- [ ] Verify current source-access and chapter contracts. Specify any missing
  scoped snapshot/export capability before implementing it; no direct database
  access by agents. Distinguish chapter markers from MCP delivery receipts.
- [ ] Define source identity, revision, text normalization and offset units.
  Make Unicode code-point versus WPF UTF-16 conversion explicit and tested.

Done when: the pilot snapshot is reproducible, source fidelity is measurable,
access boundaries are clear, and the next slice has bounded acceptance criteria.

### AB1 - manuscript contract and deterministic validator

- [ ] Add a repo-owned versioned schema, guide and offline checker, provisionally
  `contracts/manuscript/v1.schema.json`, `docs/manuscript_agent_guide.md` and
  `scripts/check_manuscript_bundle.py`.
- [ ] Represent source references, stable cast IDs, scenes, ordered units,
  evidence-backed cues, unresolved issues and review decisions. Keep voice IDs,
  synthesis prompts, asset selection and music decisions out of this format.
- [ ] Derive spoken text from source spans, or verify any stored text against
  them exactly. Preserve punctuation and explicit whitespace rules. Separate
  dialogue fragments around narrator tags; link them with an utterance group
  instead of inventing ellipses or moving narration.
- [ ] Validate complete ordered coverage, missing/duplicate text, illegal span
  overlap, invalid references and stale revisions. Metadata annotations may
  overlap as evidence but must not duplicate spoken-text ownership.
- [ ] Cover interrupted dialogue, nested quotes, letters, thoughts, unknown
  speakers, three-way dialogue, first-person narration, headings, Unicode and
  scene transitions with small synthetic fixtures and deliberate corruptions.

Done when: valid fixtures reconstruct the agreed source text exactly and
corrupted fixtures fail for explicit reasons, without any model or service run.

### AB2 - manuscript skill and bounded review workflow

- [ ] Create the local `reader-manuscript` skill over the repo contract, following
  the skill-creation workflow when this milestone is activated.
- [ ] Process chapter/scene-sized work with a compact cast ledger and necessary
  context. Pronouns are contextual references, not permanent character aliases.
- [ ] Keep unknown attribution legitimate. Store evidence and unresolved issues;
  do not present arbitrary confidence numbers as calibrated probabilities.
- [ ] Run the deterministic checker first. Use a bounded independent fidelity
  reviewer and targeted speaker/continuity review where ambiguity warrants it.
  Reviewers return findings, not unsolicited rewrites. Music/SFX agents do not
  belong to the manuscript pass.
- [ ] Persist user corrections, reviewed decisions and versioned results. Reuse
  unchanged chapters and re-review only affected content and dependencies.

Done when: the pilot produces a validated, inspectable manuscript; intentional
errors are caught; unresolved speakers are visible; and a second unchanged run
reuses the result rather than re-reading the entire source with every agent.

### AB3 - voice feasibility and casting pilot

- [ ] Verify candidate models' actual capabilities, licenses, Windows/runtime
  support and resource needs against maintained primary sources and local tests.
  Test expressive control separately from voice identity and long-form stability.
- [ ] Keep experimental dependencies isolated from the working voice environment.
  No paid/cloud dependency, model download or permanent voice change is implied
  by this parked plan. Respect consent for any reference-voice recordings.
- [ ] Audition a narrator and a small cast. Measure startup, generation time,
  peak memory, pronunciation, chunk continuity and voice consistency. Compare a
  plain baseline; model size alone does not establish fitness or speed.
- [ ] Define backend capabilities with explicit rejection or visible fallback
  for unsupported controls. Keep provider-specific fields inside adapters.

Done when: the user accepts a short audition and measured feasibility supports
the proposed production approach. If not, revise the model/quality scope first.

### AB4 - resumable speech production

- [ ] Define a versioned audio plan referencing manuscript units, stable voice
  profiles, utterance grouping, delivery instructions and explicit pauses.
- [ ] Add bounded queued jobs, durable checkpoints, cancel/resume/retry and a
  cache keyed by all audio-affecting inputs: text, voice/model versions, settings,
  pronunciation rules and generation seed where supported. Retain generated
  takes; deterministic cache identity does not guarantee deterministic models.
- [ ] Regenerate one changed utterance without rebuilding unaffected audio.
  Reuse assets after timing changes, but invalidate dependent mix/timeline output.
- [ ] Assemble in source order using measured audio durations. Group generation
  by voice only if benchmarking demonstrates a benefit without hurting prosody.
- [ ] Give everyday playback priority, avoid GPU/memory contention and expose
  progress, waiting reasons, failures, disk use and bounded resource controls.
  Do not promise accurate completion estimates before sufficient measurements.

Done when: an interrupted pilot resumes safely, repeated delivery adds no duplicate
audio, a single-line correction reuses unaffected work, and normal Reader use
remains independent of the production pipeline.

### AB5 - first finished audiobook chapter

- [ ] Provide production review and export: narrator/character speech first,
  chapter navigation, take replacement, saved mix settings and a reusable master.
- [ ] Start with WAV master and MP3 delivery; decide chapter files versus a joined
  book explicitly. Chaptered M4B is a later option, not a dependency for the pilot.
- [ ] Check completeness, order, audible transitions, excessive silence,
  truncation, clipping and consistent loudness. Fully decode the final export
  and listen through the short pilot; byte hashes alone do not prove good audio.
- [ ] Keep source-to-output provenance, version and error summaries without
  putting private prose, voice samples or credentials in ordinary logs.

Done when: the user accepts the complete pilot as a usable audiobook chapter,
with no missing/repeated speech and a demonstrated edit-and-rerender workflow.
Only then expand to full-book production and measure scaling/cost on it.

### AB6 - optional ambience and discrete sound effects

- [ ] Introduce a separate sound-design plan and bounded asset-search/generation
  workflow. Record provenance, license, attribution obligations and reuse rights.
- [ ] Anchor cues to speech events or scene boundaries, not guessed timestamps
  before speech is rendered. Support ambience continuity, fades, levels and
  speech-priority ducking without changing the spoken source.
- [ ] Keep sound design optional, previewable and individually replaceable.
  Compare speech-only and sound-designed versions of the same pilot.

Done when: the user accepts the added sound, speech remains intelligible, and
asset rights and repeatable mixing are documented.

### AB7 - optional music and full-book polish

- [ ] Add restrained music only after the earlier pilot is accepted. Reuse or
  generate licensed themes, manage scene transitions and avoid regenerating
  every cue for every run. Keep a music-free export option.
- [ ] Validate character/voice continuity, pronunciation, chapter order, output
  metadata, recovery, storage/cache retention and user-visible production cost
  across a complete book. Define safe cleanup of intermediate versus final audio.

Done when: a complete audiobook passes technical validation and user listening
acceptance, within an agreed production budget. Live generation remains out of
scope, even when offline production is complete.

## Reactivation checklist

1. User explicitly chooses this epic after current Reader work is satisfactory.
2. Recheck the repository and current backlog; do not infer status from old notes.
3. Agree pilot, fidelity policy, budget and initial output with the user.
4. Activate only the next bounded milestone, beginning with AB0/AB1.
5. Revisit architecture/security/licensing or paid-dependency changes with the
   user before adopting them. Stop at explicit acceptance gates, not at vague
   claims that the pipeline is finished.

Planning validation: documentation-only; no models installed, agents launched,
skills created, goals scheduled, source content changed, or services restarted.
