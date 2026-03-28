# Lokal offline TTS-platform med API og fremtidig Chrome extension — Design Document v2

## 1. Formål

Dette dokument beskriver en lokal, offline-first TTS-platform, designet til at kunne implementeres af en AI-kodningsagent eller et menneskeligt udviklingsteam med minimal tvetydighed. Dokumentet fungerer både som arkitektur-specifikation, implementeringsguide og systemkontrakt.

Målet er at bygge en robust lokal platform, der:

- konverterer tekst til tale uden cloud-afhængighed som standard
- eksponerer en stabil lokal API til desktop-brug og senere browserintegration
- understøtter flere TTS-backends og voices bag et ensartet interface
- prioriterer lav latency, forudsigelig drift, sikkerhed og udvidelighed
- er struktureret, så en AI-agent kan arbejde iterativt og sikkert i repoet

Dette dokument prioriterer implementerbarhed over inspiration. Hvor der er designvalg, beskrives både anbefalet løsning og begrundelse.

---

## 2. Overordnede designprincipper

Systemet skal bygges efter følgende principper:

1. **Offline-first**  
   Ingen netværkskald må være nødvendige for almindelig TTS-brug, når modeller først er installeret.

2. **Platform før model**  
   Systemet må ikke låses til én model eller én voicefamilie. Engine-abstraktionen er vigtigere end en enkelt backend.

3. **Streaming som first-class capability**  
   Systemet skal ikke kun kunne levere færdige lydfiler, men også starte afspilning hurtigt via streaming.

4. **Predictable structure**  
   Repo, konfiguration, filer og kontrakter skal være så faste og tydelige, at en AI-agent kan arbejde uden konstant menneskelig afklaring.

5. **Secure localhost by default**  
   Lokal API betragtes som et angrebsområde. Loopback-only, token-beskyttelse og strict origin-kontrol er baseline.

6. **Observability built-in**  
   Latency, fejl, voice-performance og streaming-adfærd skal kunne måles fra dag ét.

7. **Text pipeline matters**  
   TTS-kvalitet afgøres ikke kun af modellen, men i høj grad af tekstnormalisering, segmentering og prosodi-kontrol.

---

## 3. Scope

### 3.1 In scope

- Lokal HTTP API
- Valgfri WebSocket-streaming
- Flere voices og engines
- Voice registry med metadata og licensfelter
- Tekstforbehandling før synthesis
- WAV som minimumsoutput
- Lokal afspilning via fremtidig Chrome extension
- Cancellation og jobstyring
- Metrics, logging og teststrategi
- Repo-struktur egnet til agentisk udvikling

### 3.2 Out of scope for MVP

- Cloud-hosting som primær drift
- Distribueret multi-node execution
- Voice cloning som kernefunktion
- Fuldt SSML-parity med cloud-TTS-produkter
- Avanceret emotion control hvis backend ikke understøtter det
- Kompleks GUI

Disse ting kan senere bygges ovenpå platformen, men må ikke styre MVP-designvalg.

---

## 4. Målbillede

Systemet består af følgende hovedelementer:

1. **TTS Core**  
   Domænelag med tekstpipeline, engine-interface, voice registry, audio-encoder og jobstyring.

2. **Local TTS Service**  
   FastAPI-baseret service, som eksponerer HTTP og WebSocket endpoints på `127.0.0.1`.

3. **Model/Voice Store**  
   Lokal lagring af voicepakker og metadata.

4. **Chrome Extension Client (senere fase)**  
   MV3 extension med service worker og offscreen document til audio playback.

5. **CLI**  
   Et simpelt kommandolinjeinterface til test, debugging og automation.

---

## 5. Anbefalet default stack

### 5.1 Primær anbefaling

- **Sprog:** Python
- **API-framework:** FastAPI
- **ASGI-server:** Uvicorn
- **Default backend:** sherpa-onnx
- **Default output:** WAV PCM16
- **Streamingformat:** PCM16 audio-chunks over WebSocket
- **Konfiguration:** TOML + env overrides
- **Test:** pytest
- **Lint/format:** ruff

### 5.2 Designrationale

Denne kombination giver:

- stærkt ML/ONNX-økosystem
- lav integrationsfriktion
- enkel lokal distribution i MVP
- god støtte til både almindelig HTTP og WebSocket-streaming
- høj sandsynlighed for, at en AI-agent kan udvikle og vedligeholde systemet uden unødige specialtilfælde

### 5.3 Sekundære backends

Systemet skal designes sådan, at følgende typer backends senere kan tilføjes uden API-brud:

- StyleTTS2-lignende backend for højere kvalitet
- XTTS-lignende backend for private eksperimenter
- andre ONNX-kompatible TTS-modeller

Backends er udskiftelige implementeringer af det samme interne interface. Ingen backend-specifik logik må lække op i API-laget.

---

## 6. Arkitektur

### 6.1 Komponentoversigt

```text
[Client]
  |- CLI
  |- Future Chrome Extension
  |- Local scripts / tools
        |
        v
[Local TTS Service]
  |- Auth Guard
  |- Origin/CORS Guard
  |- REST API
  |- WebSocket Streaming API
  |- Job Manager
        |
        v
[TTS Core]
  |- Text Preprocessor
  |- Segmenter
  |- Prosody Planner
  |- Voice Registry
  |- Backend Adapter Interface
  |- Audio Encoder
  |- Metrics/Logging hooks
        |
        v
[Backends]
  |- sherpa-onnx backend
  |- future backends
        |
        v
[Models / Voices on disk]
```

### 6.2 Lagdeling

Systemet skal opdeles i tydelige lag:

- **API-lag**: HTTP/WebSocket, auth, request/response mapping
- **Application-lag**: jobs, orkestrering, flow-control
- **Domain-lag**: tekstpipeline, voicevalg, synthesis-kontrakter
- **Infrastructure-lag**: ONNX-runtime, filsystem, encoder, metrics-export

Dette reducerer risikoen for, at en AI-agent bygger alting sammen i ét stort script.

---

## 7. Tekstpipeline

Tekstpipeline er en central del af systemet og må ikke reduceres til en simpel `text -> synthesize()` operation.

### 7.1 Pipeline-trin

1. Input validation
2. Text normalization
3. Language hint resolution
4. Sentence segmentation
5. Chunk planning
6. Prosody planning
7. Backend synthesis
8. Audio post-processing
9. Output delivery

### 7.2 Input validation

Valider mindst:

- tom tekst
- maks længde
- ugyldigt voice-id
- ugyldigt outputformat
- ugyldige parameterkombinationer

### 7.3 Text normalization

Skal være en dedikeret komponent.

Ansvar:

- whitespace-normalisering
- basis-rensning af input
- håndtering af gentagne newline-tegn
- udvidelse af simple forkortelser
- læsbar repræsentation af tal, hvor relevant
- valgfri behandling af symbolske tegn

Denne del skal være plugin-venlig. Regler varierer mellem sprog, så normalization må ikke hardcodes direkte i API-endpoints.

### 7.4 Sentence segmentation

Segmentering skal være punctuation-aware og sprogvenlig.

Minimumskrav:

- split på sætninger
- respekter punktum, kolon, semikolon, spørgsmålstegn, udråbstegn
- undgå naiv splitting i forkortelser hvis muligt
- kunne falde tilbage til char-baseret chunking ved meget lange segmenter

### 7.5 Chunk planning

Chunking er kritisk for både latency og naturlig levering.

Der skal implementeres en chunk planner med følgende ansvar:

- holde hvert segment under et maksimum
- prioritere tidlig first-audio
- undgå unaturlige klip midt i ord eller udtryk
- understøtte streaming uden store pauser

Anbefalede initiale regler:

- `max_chars_per_chunk`: ca. 220-320 som startkonfiguration
- foretræk split ved sætning eller frase
- hvis en sætning er for lang, split ved komma eller naturlig pause
- overlap mellem tekstchunks er ikke standard, men kan tilføjes senere hvis en backend kræver det

Chunk planner skal returnere en plan, ikke bare en liste af strings. Planen skal kunne bære metadata som pausehint, prioritet og chunk-index.

Eksempel:

```json
{
  "chunks": [
    {
      "index": 0,
      "text": "Hello there.",
      "pause_after_ms": 150,
      "priority": "immediate"
    },
    {
      "index": 1,
      "text": "This is the next sentence.",
      "pause_after_ms": 80,
      "priority": "normal"
    }
  ]
}
```

### 7.6 Prosody planning

Prosody er et separat lag, også når backend kun understøtter en delmængde af kontrolparametre.

Minimumsmodel:

- rate
- volume
- pitch
- pause hints
- emphasis markers

Hvis backend ikke understøtter et felt direkte, skal det bevares i den interne model og ignoreres kontrolleret. API’et skal være future-proof.

Intern datastruktur:

```json
{
  "rate": 1.0,
  "volume": 1.0,
  "pitch": 0,
  "pause_strategy": "auto",
  "sentence_pause_ms": 120,
  "comma_pause_ms": 60,
  "emphasis": []
}
```

### 7.7 SSML og markup

MVP skal ikke kræve fuld SSML, men systemet skal designes sådan, at markup senere kan tilføjes uden at omskrive hele pipeline.

MVP-anbefaling:

- almindelig tekst som primær inputtype
- reserveret felt `input_format` med værdier som `plain_text`, `ssml_future`
- undgå at bake plain-text-antagelser for hårdt ind i domænelaget

---

## 8. Voice registry

Voice registry er systemets katalog over installerede voices og deres egenskaber.

### 8.1 Ansvar

- liste installerede voices
- slå voice-id op
- validere licensmetadata
- eksponere kvalitets- og kapabilitetsfelter
- give information til UI, CLI og API

### 8.2 Krav til metadata pr. voice

Hver voice skal have mindst:

- `id`
- `name`
- `engine`
- `language`
- `sample_rate_hz`
- `license`
- `source`
- `gender_style_hint` hvis relevant
- `quality_tier`
- `latency_tier`
- `tags`
- `capabilities`

Eksempel:

```json
{
  "id": "kokoro-en-heart",
  "name": "Kokoro EN Heart",
  "engine": "sherpa_onnx",
  "language": "en",
  "sample_rate_hz": 24000,
  "license": "Apache-2.0",
  "source": "local_models/kokoro/en-heart",
  "quality_tier": "high",
  "latency_tier": "medium",
  "tags": ["neural", "clear", "general"],
  "capabilities": {
    "supports_pitch": false,
    "supports_streaming": true,
    "supports_multi_speaker": false
  }
}
```

### 8.3 Voice scoring

Registry skal kunne bære simple subjektive eller operationelle scorefelter, fx:

- `quality_score`
- `speed_score`
- `stability_score`

Disse felter må gerne være manuelle i starten. De bliver nyttige til automatisk fallback og UI-præsentation.

---

## 9. Backend-interface

Alle engines skal implementere det samme interne interface.

### 9.1 Designmål

- ensartet kald fra application-laget
- mulighed for streaming og ikke-streaming
- backend-specifik fejl må oversættes til fælles fejltyper

### 9.2 Foreslået interface

```python
class TTSBackend(Protocol):
    def list_voices(self) -> list[VoiceDescriptor]:
        ...

    def warmup(self, voice_id: str | None = None) -> None:
        ...

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        ...

    def synthesize_stream(self, request: SynthesisRequest) -> Iterator[AudioChunk]:
        ...

    def cancel(self, job_id: str) -> bool:
        ...
```

### 9.3 Domæneobjekter

Der skal findes tydelige typer for:

- `SynthesisRequest`
- `SynthesisResult`
- `AudioChunk`
- `VoiceDescriptor`
- `JobState`

AI-agenten må ikke begynde at sende rå dicts rundt mellem alle lag. Der skal være klare modeller.

---

## 10. Audio output og encoding

### 10.1 MVP-format

MVP skal understøtte:

- WAV PCM16 mono

### 10.2 Senere format

Systemet skal være designet til senere støtte for:

- Ogg/Opus

### 10.3 Outputtyper

Systemet skal understøtte to leveringsformer:

1. **Complete file output**
2. **Streaming output**

Complete file output bruges til korte eller almindelige forespørgsler. Streaming bruges, når lav start-latency er vigtigere end at have hele filen klar.

### 10.4 AudioChunk-kontrakt

Streaming skal ske via binære PCM16-chunks, ikke ved at sende halve WAV-filer.

Minimumsfelter for intern chunk-repræsentation:

- `job_id`
- `chunk_index`
- `sample_rate_hz`
- `channels`
- `pcm_bytes`
- `duration_ms`
- `is_last`

---

## 11. API-design

### 11.1 Principper

- simpelt og deterministisk
- stabile response-formater
- ensartede fejlstrukturer
- både synkrone og streaming-orienterede flows

### 11.2 Endpoints

#### `GET /v1/health`

Returnerer service-status.

Eksempel:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_s": 123,
  "default_voice": "kokoro-en-heart"
}
```

#### `GET /v1/voices`

Returnerer voice registry.

#### `POST /v1/tts`

Syntetiserer og returnerer komplet audio.

Request:

```json
{
  "text": "Hello world",
  "voice": "kokoro-en-heart",
  "format": "wav",
  "prosody": {
    "rate": 1.0,
    "volume": 1.0,
    "pitch": 0
  },
  "options": {
    "normalize_text": true,
    "streaming_preferred": false
  }
}
```

Response:

- `200 OK`
- `Content-Type: audio/wav`

#### `POST /v1/tts/jobs`

Opretter et async job for længere syntese eller eksplicit jobstyring.

Response:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

#### `GET /v1/tts/jobs/{job_id}`

Returnerer jobstatus.

#### `DELETE /v1/tts/jobs/{job_id}`

Forsøger at annullere et aktivt job.

#### `WS /v1/tts/stream`

WebSocket-endpoint til streaming.

### 11.3 WebSocket-protokol

Ved forbindelse:

1. klient forbinder
2. klient sender `start`-event med request payload
3. server svarer med `started`
4. server sender binære audioframes og evt. metadata-events
5. server sender `done` eller `error`

Eksempel på kontrol-event:

```json
{
  "type": "started",
  "job_id": "uuid"
}
```

Eksempel på senere event:

```json
{
  "type": "mark",
  "chunk_index": 3,
  "text_offset": 148
}
```

### 11.4 Fejlformat

Alle JSON-fejl skal bruge samme struktur:

```json
{
  "error": {
    "type": "invalid_request",
    "message": "Unknown voice id",
    "param": "voice",
    "request_id": "uuid",
    "details": {}
  }
}
```

Standardtyper:

- `invalid_request`
- `unauthorized`
- `forbidden_origin`
- `not_found`
- `conflict`
- `rate_limited`
- `engine_error`
- `internal_error`

---

## 12. Jobstyring og cancellation

Systemet skal have en eksplicit job manager.

### 12.1 Hvorfor

Uden jobstyring bliver det svært at:

- annullere streams på en ren måde
- håndtere samtidige requests
- måle latency korrekt
- undgå resource leaks

### 12.2 Job states

Minimum:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

### 12.3 Krav

- hvert job skal have et unikt ID
- cancellation skal kunne propagere ned til backend
- jobs må ikke blive hængende i uendelig tid
- færdige jobs skal have cleanup-strategi

---

## 13. Streaming og playback-strategi

Streaming er ikke kun et serverproblem. Afspilningssiden skal tænkes med ind i designet.

### 13.1 Server-side streamingstrategi

Anbefalet startstrategi:

- generér audio pr. tekstchunk
- send PCM16 binære frames
- chunk audio i små enheder, fx ca. 20-100 ms lyd pr. frame
- send kontrol-events separat fra audio-data

### 13.2 Client-side playback buffer

Der skal designes efter en jitter buffer.

Minimumskrav til klientlogik:

- afspil ikke første audioframe øjeblikkeligt
- buffer et lille antal frames først
- fortsæt playback så længe buffer er over minimumsgrænse
- pause eller recover kontrolleret ved underrun

Anbefalet initial adfærd:

- prebuffer: ca. 150-300 ms
- low watermark: under denne grænse aktiveres recovery-logik
- high watermark: over denne grænse kan client være mere aggressiv med playback

Dette skal være konfigurerbart.

### 13.3 Recovery-strategi ved underrun

Hvis playback-buffere løber tør:

- markér underrun i metrics
- forsøg kort genbuffering
- undgå hårde klik og fejllyd
- afslut ikke stream med mindre forbindelsen faktisk er død

### 13.4 Servermetrics for streaming

Mål mindst:

- time to first chunk
- time to first audible chunk
- chunk generation rate
- chunk send rate
- underrun count set fra klientrapportering, når extension findes

---

## 14. Sikkerhed

### 14.1 Baseline

Systemet skal som standard:

- binde til `127.0.0.1`
- kræve token-auth
- bruge strict CORS/origin-regler
- have request-begrænsninger
- undgå følsom logging

### 14.2 Token-model

Ved første start skal systemet kunne generere et lokalt installation-token.

Krav:

- token gemmes i lokal config med stramme rettigheder
- token kræves for skrive- og synthese-endpoints
- token skal kunne roteres

### 14.3 Origin-kontrol

Hvis browserintegration bruges, skal systemet kunne godkende udvalgte origins, fx en specifik extension-origin.

Der må ikke bruges wildcard-CORS i produktionstilstand.

### 14.4 Limits

Implementér mindst:

- max chars per request
- max samtidige jobs
- max stream duration
- simpel rate limiting per klient

### 14.5 Native messaging som hardening-mode

HTTP localhost er primær integrationsvej i MVP, men designet skal ikke blokere en senere native messaging bridge til Chrome.

Dette skal behandles som en fremtidig sikkerhedsopgradering, ikke som et krav for MVP.

---

## 15. Konfiguration

Systemet skal have en central konfigurationsmodel.

### 15.1 Krav

- læsbar konfigurationsfil, helst TOML
- miljøvariabel-overrides
- tydelige defaults
- validering ved startup

### 15.2 Eksempelstruktur

```toml
[server]
host = "127.0.0.1"
port = 7777
log_level = "info"

[auth]
enabled = true
token_file = "./config/token.txt"

[tts]
default_voice = "kokoro-en-heart"
max_chars_per_request = 4000
warmup_on_start = true

[streaming]
enabled = true
audio_frame_ms = 40
prebuffer_ms = 200

[metrics]
enabled = true

[limits]
max_concurrent_jobs = 2
max_job_seconds = 300
```

### 15.3 Konfigurationsfilosofi

Konfiguration må ikke spredes ud over environment variables, hardcodede konstanter og tilfældige JSON-filer. Der skal være ét primært sted, som derefter kan overrides.

---

## 16. Observability

Observability er et krav, ikke en luksus.

### 16.1 Metrics

Der skal som minimum måles:

- request count
- success/failure count
- request latency
- synthesis latency
- time to first chunk
- total synthesis duration
- RTF per backend og voice
- active jobs
- cancellation count
- streaming underrun count når klientintegration findes

### 16.2 Logging

Logging skal være struktureret.

Log mindst:

- request_id
- job_id
- endpoint
- voice_id
- backend
- varighed
- outcome

Undgå som standard at logge rå inputtekst. Det må kun ske eksplicit i debug-mode.

### 16.3 Health og readiness

Der skal skelnes mellem:

- proces kører
- backend kan faktisk syntetisere
- default voice er loadet

Senere kan det udvides med readiness endpoints, men allerede i MVP bør health ikke være vildledende.

---

## 17. Repo-struktur

Repoet skal være let at navigere i for både mennesker og AI-agenter.

### 17.1 Anbefalet struktur

```text
tts-platform/
  AGENTS.md
  README.md
  ARCHITECTURE.md
  DECISIONS.md
  SECURITY.md
  TASKS.md
  TESTING.md
  pyproject.toml

  apps/
    tts_service/
      src/tts_service/
      tests/

    chrome_extension/
      manifest.json
      src/
      offscreen/

  packages/
    tts_core/
      src/tts_core/
      tests/

  models/
    MANIFEST.json
    voices/

  config/
    config.example.toml

  scripts/
    dev_run.py
    benchmark.py
```

### 17.2 Vigtige styrefiler

#### `AGENTS.md`
Skal definere:

- golden commands
- kodekonventioner
- testkrav
- sikkerhedsregler
- definition of done

#### `TASKS.md`
Skal være opdelt i små, implementerbare trin.

#### `DECISIONS.md`
Skal bruges til arkitekturbeslutninger, så agenten kan forstå hvorfor noget er valgt.

---

## 18. CLI

Der skal være en enkel CLI fra tidligt i projektet.

### 18.1 Hvorfor

CLI gør det nemmere at:

- smoke-teste systemet
- benchmarke
- reproducere fejl
- bruge systemet uden extension

### 18.2 Minimumskommandoer

```bash
tts health
tts list-voices
tts say "Hello world"
tts save "Hello world" --out out.wav
tts stream "Hello world"
```

### 18.3 Designregel

CLI skal bruge samme offentlige kontrakter som andre klienter så vidt muligt. Den må ikke være en sær intern genvej, der bypasser systemets regler.

---

## 19. Teststrategi

Teststrategien skal være opdelt i niveauer.

### 19.1 Unit tests

Test isoleret:

- normalization
- segmentering
- chunk planner
- prosody planner
- voice registry
- config-validering

### 19.2 Integration tests

Test:

- `/v1/health`
- `/v1/voices`
- `/v1/tts`
- job flow
- auth-regler
- origin-regler

### 19.3 Streaming tests

Test:

- WebSocket handshake
- start-event
- modtagelse af audioframes
- clean shutdown
- cancellation mid-stream

### 19.4 Audio regression tests

Fuld bit-identisk audio er ikke altid realistisk på tværs af platforme og runtimes. Derfor anbefales to niveauer:

1. **Strukturelle tests**
   - output findes
   - sample rate er korrekt
   - audio-længde er inden for interval

2. **Tolerance-baserede regression tests**
   - enkel waveform- eller feature-sammenligning
   - ikke naiv byte-compare som eneste kriterium

### 19.5 Performance tests

Mål mindst:

- cold start
- warm request latency
- time to first chunk
- total generation time
- RTF pr. voice

---

## 20. Installations- og onboarding-flow

Installation er en vigtig del af platformdesignet.

### 20.1 Mål

En udvikler eller AI-agent skal kunne komme fra tom checkout til fungerende lokal service med få deterministiske kommandoer.

### 20.2 Minimumsflow

1. installer dependencies
2. opret config fra eksempel
3. download eller registrer mindst én voice
4. kør warmup
5. start service
6. kør smoke test

### 20.3 Ønsket kommandooplevelse

```bash
uv sync
python scripts/dev_run.py
pytest -q
```

Senere kan der tilføjes mere poleret onboarding, fx:

```bash
tts init
tts install-voice kokoro-en-heart
tts run
```

---

## 21. Chrome extension integration

Dette er ikke MVP-krav, men platformen skal være forberedt til det.

### 21.1 Designmål

- extension må kunne sende tekst til lokal service
- audio må kunne afspilles stabilt i MV3-verdenen
- streaming må understøttes senere uden at ændre TTS-kernen

### 21.2 Forventet arkitektur

- content script: finder tekst eller selection
- service worker: koordinerer request/stream
- offscreen document: audio playback og bufferhåndtering

### 21.3 Vigtig designregel

Alt extension-specifikt skal leve i klientlaget. TTS service må ikke kende til browserdetaljer ud over auth/origin-regler.

---

## 22. Implementeringsplan

### Fase 1 — Fundament

- repo-skeleton
- AGENTS.md
- config-model
- voice registry
- backend interface
- sherpa-onnx backend stub

### Fase 2 — Basal syntese

- text normalization
- segmentering
- `/v1/health`
- `/v1/voices`
- `/v1/tts`
- WAV output

### Fase 3 — Jobs og sikkerhed

- job manager
- token auth
- origin-kontrol
- rate limiting
- cancellation

### Fase 4 — Streaming

- WebSocket endpoint
- PCM chunk delivery
- streaming metrics
- cancellation under stream

### Fase 5 — Drift og kvalitet

- benchmark-script
- observability
- audio regression tests
- CLI

### Fase 6 — Browserklient

- MV3 prototype
- offscreen playback
- jitter buffer
- extension auth flow

---

## 23. Krav til AI-kodningsagent

Dette projekt er udtrykkeligt designet til at kunne udføres iterativt af en AI-kodningsagent. Derfor gælder følgende krav til agentens arbejdsform:

1. Implementér i små trin.
2. Tilføj eller opdater tests ved adfærdsændringer.
3. Hold lagene adskilt.
4. Indfør ikke backend-specifik adfærd i API-laget.
5. Tilføj ikke nye filer eller abstraktioner uden tydelig begrundelse.
6. Dokumentér designbeslutninger i `DECISIONS.md`.
7. Rør ikke sikkerhedsregler uden at opdatere `SECURITY.md`.
8. Undgå “midlertidige” hardcodede løsninger, der sandsynligvis bliver permanente.

### 23.1 Definition of done for en task

En task er først færdig når:

- kode virker
- relevante tests findes og passerer
- eventuel dokumentation er opdateret
- public contract ikke er gjort mere tvetydig
- logging og fejlflow er rimeligt håndteret

---

## 24. Kendte risici

### 24.1 Første request er langsom
Mitigation: warmup ved startup.

### 24.2 Streaming hakker
Mitigation: bedre chunking, mindre frame-størrelser, jitter buffer.

### 24.3 Backends opfører sig forskelligt
Mitigation: stærkt fælles interface og backend-kontrakter.

### 24.4 Lokal service misbruges af browserindhold
Mitigation: loopback-only, token, strict origin.

### 24.5 For meget spontan kompleksitet i repoet
Mitigation: faste styrefiler, små tasks, klare domænemodeller.

---

## 25. Konklusion

Den anbefalede løsning er en lokal TTS-platform baseret på en engine-abstraktion med sherpa-onnx som default backend, eksponeret via FastAPI og udvidet med WebSocket-streaming. Den vigtigste forskel mellem denne v2 og en mere overfladisk teknisk skitse er, at tekstpipeline, buffering, jobstyring, sikkerhed, observability og AI-agent-arbejdsgang nu behandles som kernekomponenter frem for sidebemærkninger.

Hvis systemet implementeres efter denne specifikation, vil resultatet være en platform, som både er praktisk anvendelig, sikker nok til lokal drift, og struktureret nok til at en kodende AI kan arbejde videre på den uden at smadre arkitekturen i første forelskelse.

