# Third-party notices

This file records direct runtime dependencies added by TTS Platform Reader.
Transitive package notices remain available in their respective distributions.

## Optional Reader MCP adapter (2026-09-05 dependency review)

- Direct optional dependency: `mcp==2.1.1`, official Python MCP SDK.
- Source: <https://github.com/modelcontextprotocol/python-sdk/tree/v2.1.1>
- SDK documentation: <https://py.sdk.modelcontextprotocol.io/>
- Package: <https://pypi.org/project/mcp/2.1.1/>
- License: MIT; Copyright (c) 2024 Anthropic, PBC. The upstream MIT text,
  including its notice and warranty disclaimer, is shipped in the package's
  `mcp-2.1.1.dist-info/licenses/LICENSE` and must be retained on redistribution.

Installed distribution metadata and shipped license texts were reviewed for
the optional Windows environment. Important additional runtime dependencies:

| Packages (validated version) | License / notice |
|---|---|
| mcp-types 2.1.1 | MIT |
| httpx2 / httpcore2 2.12.0 | BSD-3-Clause |
| jsonschema 4.26.0, jsonschema-specifications 2025.9.1, referencing 0.37.0, rpds-py 2026.6.3, attrs 26.1.0 | MIT |
| pydantic 2.13.5 / pydantic-core 2.46.5, annotated-types 0.8.0 | MIT |
| pyjwt 2.13.0, truststore 0.10.4, anyio 4.15.1 | MIT |
| opentelemetry-api 1.44.0 | Apache-2.0 |
| pywin32 312 | Metadata declares PSF; retain its component-specific licenses, including Mark Hammond's BSD-style Pythonwin notice |
| sse-starlette 3.4.11, starlette 1.6.0, uvicorn 0.52.4, click 8.5.0, idna 3.19 | BSD-3-Clause |
| typing-extensions 4.16.0 | PSF-2.0 |
| typing-inspection 0.4.4, h11 0.16.0 | MIT |

The SDK also depends on existing project components such as python-multipart
(Apache-2.0) and PyJWT's cryptography extra (Apache-2.0 OR BSD-3-Clause;
cryptography notice below). Package/component license texts remain in their
distributions. No project license change or required hosted/paid dependency
was introduced. MCP runs in a separate optional environment and does not
replace the voice runtime's HTTP stack. No telemetry exporter is configured.
Dependency versions other than the SDK are a validated snapshot, not a lockfile;
review notices and repeat tests when updating them.

## cryptography 46.x

- Purpose: ECDSA P-256 server identity generation and validation for the optional
  private-network Reader gateway.
- Source: <https://github.com/pyca/cryptography>
- Package: <https://pypi.org/project/cryptography/>
- License expression: Apache-2.0 OR BSD-3-Clause.

The applicable license texts are distributed with the upstream package. The
dependency is independently maintained and is not modified by this project.

## regex 2026.7.19

- Purpose: hard-timeout Unicode regular expressions for untrusted Reader speech rules.
- Source: <https://github.com/mrabarnett/mrab-regex>
- Package: <https://pypi.org/project/regex/2026.7.19/>
- License expression: Apache-2.0 AND CNRI-Python.

The applicable license texts are distributed with the upstream package. The
dependency is independently maintained and is not modified by this project.

## python-multipart 0.0.32

- Purpose: bounded streaming `multipart/form-data` parsing for Reader imports.
- Source: <https://github.com/Kludex/python-multipart>
- Package: <https://pypi.org/project/python-multipart/0.0.32/>
- License: Apache-2.0.

The Apache License 2.0 text is available from the upstream source and package.
The dependency is independently maintained and is not modified by this project.

## NAudio 2.3.0

- Purpose: shared-mode Windows audio output for Reader PCM playback.
- Source: <https://github.com/naudio/NAudio>
- Package: <https://www.nuget.org/packages/NAudio/2.3.0>
- License: MIT.

Copyright (c) 2020 Mark Heath

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
