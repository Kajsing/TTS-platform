#include "TtsPlatformSapiEngine.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cwctype>
#include <cstring>
#include <fstream>
#include <new>
#include <sstream>
#include <string>
#include <vector>
#include <winhttp.h>

namespace {

constexpr ULONG kSampleRateHz = 22050;
constexpr WORD kChannelCount = 1;
constexpr WORD kBitsPerSample = 16;
constexpr double kToneHz = 440.0;
constexpr double kToneSeconds = 0.35;
constexpr double kPi = 3.14159265358979323846;
constexpr wchar_t kServiceHost[] = L"127.0.0.1";
constexpr INTERNET_PORT kServicePort = 7777;
constexpr wchar_t kServicePath[] = L"/v1/tts";
constexpr DWORD kHttpTimeoutMs = 60000;
constexpr size_t kMaxServiceTextChars = 600;
constexpr DWORD kInterChunkPauseMs = 120;

std::atomic<ULONG> g_objectCount{0};
std::atomic<ULONG> g_lockCount{0};

struct PcmAudio {
    std::vector<std::uint8_t> bytes;
    DWORD sampleRateHz = 0;
    WORD channels = 0;
    WORD bitsPerSample = 0;
};

WAVEFORMATEX* AllocateWaveFormat() {
    auto* format = static_cast<WAVEFORMATEX*>(::CoTaskMemAlloc(sizeof(WAVEFORMATEX)));
    if (!format) {
        return nullptr;
    }
    format->wFormatTag = WAVE_FORMAT_PCM;
    format->nChannels = kChannelCount;
    format->nSamplesPerSec = kSampleRateHz;
    format->wBitsPerSample = kBitsPerSample;
    format->nBlockAlign = static_cast<WORD>((format->nChannels * format->wBitsPerSample) / 8);
    format->nAvgBytesPerSec = format->nSamplesPerSec * format->nBlockAlign;
    format->cbSize = 0;
    return format;
}

std::vector<int16_t> MakeTonePcm() {
    const auto sampleCount = static_cast<size_t>(kSampleRateHz * kToneSeconds);
    std::vector<int16_t> pcm(sampleCount);
    for (size_t index = 0; index < pcm.size(); ++index) {
        const double t = static_cast<double>(index) / static_cast<double>(kSampleRateHz);
        const double sample = std::sin(2.0 * kPi * kToneHz * t) * 0.20;
        pcm[index] = static_cast<int16_t>(sample * 32767.0);
    }
    return pcm;
}

bool IsSupportedFormat(REFGUID formatId, const WAVEFORMATEX* waveFormatEx) {
    if (formatId != SPDFID_WaveFormatEx || !waveFormatEx) {
        return false;
    }
    return waveFormatEx->wFormatTag == WAVE_FORMAT_PCM &&
        waveFormatEx->nChannels == kChannelCount &&
        waveFormatEx->nSamplesPerSec == kSampleRateHz &&
        waveFormatEx->wBitsPerSample == kBitsPerSample;
}

std::wstring GetModulePath() {
    HMODULE module = nullptr;
    const auto flags = GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT;
    if (!::GetModuleHandleExW(
            flags,
            reinterpret_cast<LPCWSTR>(&GetModulePath),
            &module)) {
        return L"";
    }

    std::wstring buffer(MAX_PATH, L'\0');
    DWORD size = 0;
    while (true) {
        size = ::GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (size == 0) {
            return L"";
        }
        if (size < buffer.size() - 1) {
            buffer.resize(size);
            return buffer;
        }
        buffer.resize(buffer.size() * 2);
    }
}

std::wstring ParentPath(const std::wstring& path) {
    const size_t slash = path.find_last_of(L"\\/");
    if (slash == std::wstring::npos) {
        return L"";
    }
    return path.substr(0, slash);
}

bool FileExists(const std::wstring& path) {
    const DWORD attributes = ::GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES &&
        (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

void LogBridgeEvent(const std::string& message) {
    std::wstring repoRoot;
    std::wstring current = ParentPath(GetModulePath());
    for (int depth = 0; depth < 8 && !current.empty(); ++depth) {
        const std::wstring tokenPath = current + L"\\config\\token.txt";
        if (FileExists(tokenPath)) {
            repoRoot = current;
            break;
        }
        current = ParentPath(current);
    }
    if (repoRoot.empty()) {
        ::OutputDebugStringA(("TTS Platform SAPI Bridge: " + message + "\n").c_str());
        return;
    }

    const std::wstring logDir = repoRoot + L"\\logs";
    ::CreateDirectoryW(logDir.c_str(), nullptr);
    const std::wstring logPath = logDir + L"\\sapi-bridge.log";
    std::ofstream logFile(logPath, std::ios::app | std::ios::binary);
    if (!logFile) {
        return;
    }

    SYSTEMTIME now{};
    ::GetLocalTime(&now);
    logFile
        << now.wYear << "-"
        << (now.wMonth < 10 ? "0" : "") << now.wMonth << "-"
        << (now.wDay < 10 ? "0" : "") << now.wDay << " "
        << (now.wHour < 10 ? "0" : "") << now.wHour << ":"
        << (now.wMinute < 10 ? "0" : "") << now.wMinute << ":"
        << (now.wSecond < 10 ? "0" : "") << now.wSecond << " "
        << message << "\n";
}

std::wstring FindRepoRoot() {
    std::wstring current = ParentPath(GetModulePath());
    for (int depth = 0; depth < 8 && !current.empty(); ++depth) {
        const std::wstring tokenPath = current + L"\\config\\token.txt";
        if (FileExists(tokenPath)) {
            return current;
        }
        current = ParentPath(current);
    }
    return L"";
}

std::string ReadToken() {
    const std::wstring repoRoot = FindRepoRoot();
    if (repoRoot.empty()) {
        LogBridgeEvent("token lookup failed: repo root not found from DLL path");
        return "";
    }
    std::ifstream tokenFile(repoRoot + L"\\config\\token.txt", std::ios::binary);
    if (!tokenFile) {
        LogBridgeEvent("token lookup failed: config/token.txt could not be opened");
        return "";
    }
    std::string token(
        (std::istreambuf_iterator<char>(tokenFile)),
        std::istreambuf_iterator<char>());
    while (!token.empty() && (token.back() == '\r' || token.back() == '\n' || token.back() == ' ')) {
        token.pop_back();
    }
    return token;
}

std::string WideToUtf8(const std::wstring& value) {
    if (value.empty()) {
        return "";
    }
    const int size = ::WideCharToMultiByte(
        CP_UTF8,
        0,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (size <= 0) {
        return "";
    }
    std::string output(static_cast<size_t>(size), '\0');
    ::WideCharToMultiByte(
        CP_UTF8,
        0,
        value.data(),
        static_cast<int>(value.size()),
        output.data(),
        size,
        nullptr,
        nullptr);
    return output;
}

std::string JsonEscape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size() + 16);
    for (const unsigned char ch : value) {
        switch (ch) {
        case '"':
            escaped += "\\\"";
            break;
        case '\\':
            escaped += "\\\\";
            break;
        case '\b':
            escaped += "\\b";
            break;
        case '\f':
            escaped += "\\f";
            break;
        case '\n':
            escaped += "\\n";
            break;
        case '\r':
            escaped += "\\r";
            break;
        case '\t':
            escaped += "\\t";
            break;
        default:
            if (ch < 0x20) {
                char buffer[7] = {};
                std::snprintf(buffer, sizeof(buffer), "\\u%04x", ch);
                escaped += buffer;
            } else {
                escaped.push_back(static_cast<char>(ch));
            }
        }
    }
    return escaped;
}

std::wstring CollectText(const SPVTEXTFRAG* fragment) {
    std::wstring text;
    for (const SPVTEXTFRAG* current = fragment; current; current = current->pNext) {
        if (current->pTextStart && current->ulTextLen > 0) {
            text.append(current->pTextStart, current->ulTextLen);
            text.push_back(L' ');
        }
    }
    while (!text.empty() && iswspace(text.back())) {
        text.pop_back();
    }
    return text;
}

DWORD ReadLe32(const std::vector<std::uint8_t>& data, size_t offset) {
    return static_cast<DWORD>(data[offset]) |
        (static_cast<DWORD>(data[offset + 1]) << 8) |
        (static_cast<DWORD>(data[offset + 2]) << 16) |
        (static_cast<DWORD>(data[offset + 3]) << 24);
}

WORD ReadLe16(const std::vector<std::uint8_t>& data, size_t offset) {
    return static_cast<WORD>(
        static_cast<WORD>(data[offset]) |
        (static_cast<WORD>(data[offset + 1]) << 8));
}

bool DecodeWavPcm16(const std::vector<std::uint8_t>& wav, PcmAudio* audio) {
    if (!audio || wav.size() < 44 ||
        std::memcmp(wav.data(), "RIFF", 4) != 0 ||
        std::memcmp(wav.data() + 8, "WAVE", 4) != 0) {
        return false;
    }

    bool sawFormat = false;
    bool sawData = false;
    size_t offset = 12;
    while (offset + 8 <= wav.size()) {
        const char* chunkId = reinterpret_cast<const char*>(wav.data() + offset);
        const DWORD chunkSize = ReadLe32(wav, offset + 4);
        const size_t payloadOffset = offset + 8;
        if (payloadOffset + chunkSize > wav.size()) {
            return false;
        }

        if (std::memcmp(chunkId, "fmt ", 4) == 0) {
            if (chunkSize < 16) {
                return false;
            }
            const WORD formatTag = ReadLe16(wav, payloadOffset);
            audio->channels = ReadLe16(wav, payloadOffset + 2);
            audio->sampleRateHz = ReadLe32(wav, payloadOffset + 4);
            audio->bitsPerSample = ReadLe16(wav, payloadOffset + 14);
            if (formatTag != WAVE_FORMAT_PCM || audio->bitsPerSample != 16) {
                return false;
            }
            sawFormat = true;
        } else if (std::memcmp(chunkId, "data", 4) == 0) {
            audio->bytes.assign(
                wav.begin() + static_cast<std::ptrdiff_t>(payloadOffset),
                wav.begin() + static_cast<std::ptrdiff_t>(payloadOffset + chunkSize));
            sawData = true;
        }

        offset = payloadOffset + chunkSize + (chunkSize % 2);
    }
    return sawFormat && sawData && !audio->bytes.empty();
}

std::string SafeLogSnippet(const std::vector<std::uint8_t>& bytes) {
    constexpr size_t kMaxSnippetBytes = 300;
    std::string snippet;
    const size_t count = std::min(bytes.size(), kMaxSnippetBytes);
    snippet.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        const char ch = static_cast<char>(bytes[index]);
        if (ch >= 0x20 && ch <= 0x7e) {
            snippet.push_back(ch);
        } else {
            snippet.push_back(' ');
        }
    }
    return snippet;
}

bool PostTtsRequest(const std::string& requestBody, std::vector<std::uint8_t>* responseBody) {
    if (!responseBody) {
        return false;
    }
    responseBody->clear();

    HINTERNET session = ::WinHttpOpen(
        L"TTS Platform SAPI Bridge/0.1",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS,
        0);
    if (!session) {
        LogBridgeEvent("WinHttpOpen failed");
        return false;
    }
    ::WinHttpSetTimeouts(
        session,
        kHttpTimeoutMs,
        kHttpTimeoutMs,
        kHttpTimeoutMs,
        kHttpTimeoutMs);

    HINTERNET connect = ::WinHttpConnect(session, kServiceHost, kServicePort, 0);
    if (!connect) {
        LogBridgeEvent("WinHttpConnect failed: service not reachable at 127.0.0.1:7777");
        ::WinHttpCloseHandle(session);
        return false;
    }

    HINTERNET request = ::WinHttpOpenRequest(
        connect,
        L"POST",
        kServicePath,
        nullptr,
        WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES,
        0);
    if (!request) {
        LogBridgeEvent("WinHttpOpenRequest failed");
        ::WinHttpCloseHandle(connect);
        ::WinHttpCloseHandle(session);
        return false;
    }

    std::wstring headers = L"Content-Type: application/json\r\nAccept: audio/wav\r\n";
    const std::string token = ReadToken();
    if (!token.empty()) {
        headers += L"Authorization: Bearer ";
        headers += std::wstring(token.begin(), token.end());
        headers += L"\r\n";
    } else {
        LogBridgeEvent("sending /v1/tts request without bearer token");
    }

    const BOOL sent = ::WinHttpSendRequest(
        request,
        headers.c_str(),
        static_cast<DWORD>(headers.size()),
        const_cast<char*>(requestBody.data()),
        static_cast<DWORD>(requestBody.size()),
        static_cast<DWORD>(requestBody.size()),
        0);
    if (!sent || !::WinHttpReceiveResponse(request, nullptr)) {
        LogBridgeEvent("WinHTTP send/receive failed");
        ::WinHttpCloseHandle(request);
        ::WinHttpCloseHandle(connect);
        ::WinHttpCloseHandle(session);
        return false;
    }

    DWORD statusCode = 0;
    DWORD statusSize = sizeof(statusCode);
    const BOOL hasStatusCode = ::WinHttpQueryHeaders(
        request,
        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX,
        &statusCode,
        &statusSize,
        WINHTTP_NO_HEADER_INDEX);

    while (true) {
        DWORD available = 0;
        if (!::WinHttpQueryDataAvailable(request, &available)) {
            LogBridgeEvent("WinHttpQueryDataAvailable failed");
            responseBody->clear();
            break;
        }
        if (available == 0) {
            break;
        }
        const size_t oldSize = responseBody->size();
        responseBody->resize(oldSize + available);
        DWORD read = 0;
        if (!::WinHttpReadData(
                request,
                responseBody->data() + oldSize,
                available,
                &read)) {
            LogBridgeEvent("WinHttpReadData failed");
            responseBody->clear();
            break;
        }
        responseBody->resize(oldSize + read);
    }

    ::WinHttpCloseHandle(request);
    ::WinHttpCloseHandle(connect);
    ::WinHttpCloseHandle(session);
    if (!hasStatusCode || statusCode != 200) {
        std::ostringstream message;
        message << "/v1/tts returned HTTP " << statusCode;
        if (!responseBody->empty()) {
            message << " body: " << SafeLogSnippet(*responseBody);
        }
        LogBridgeEvent(message.str());
        responseBody->clear();
        return false;
    }
    if (responseBody->empty()) {
        LogBridgeEvent("/v1/tts returned an empty response body");
    }
    return !responseBody->empty();
}

std::vector<std::wstring> SplitTextForService(const std::wstring& text) {
    std::vector<std::wstring> chunks;
    size_t offset = 0;
    while (offset < text.size()) {
        while (offset < text.size() && iswspace(text[offset])) {
            ++offset;
        }
        if (offset >= text.size()) {
            break;
        }

        const size_t remaining = text.size() - offset;
        if (remaining <= kMaxServiceTextChars) {
            chunks.push_back(text.substr(offset));
            break;
        }

        size_t end = offset + kMaxServiceTextChars;
        size_t split = text.find_last_of(L".!?;,\r\n\t ", end);
        if (split == std::wstring::npos || split <= offset + (kMaxServiceTextChars / 2)) {
            split = end;
        }
        chunks.push_back(text.substr(offset, split - offset));
        offset = split;
    }
    return chunks;
}

bool SynthesizeChunkFromService(
    const std::wstring& textChunk,
    const WAVEFORMATEX* expectedFormat,
    PcmAudio* audio) {
    if (textChunk.empty() || !audio || !expectedFormat) {
        LogBridgeEvent("service synthesis skipped: empty text or missing expected format");
        return false;
    }
    const std::string utf8Text = WideToUtf8(textChunk);
    if (utf8Text.empty()) {
        LogBridgeEvent("service synthesis skipped: UTF-8 conversion produced no text");
        return false;
    }
    const std::string requestBody =
        "{\"text\":\"" + JsonEscape(utf8Text) + "\",\"format\":\"wav\"}";

    std::vector<std::uint8_t> wav;
    if (!PostTtsRequest(requestBody, &wav) || !DecodeWavPcm16(wav, audio)) {
        LogBridgeEvent("service synthesis failed: request failed or response was not PCM16 WAV");
        return false;
    }
    const bool formatMatches = audio->sampleRateHz == expectedFormat->nSamplesPerSec &&
        audio->channels == expectedFormat->nChannels &&
        audio->bitsPerSample == expectedFormat->wBitsPerSample;
    if (!formatMatches) {
        std::ostringstream message;
        message << "service WAV format mismatch: got "
                << audio->sampleRateHz << " Hz, "
                << audio->channels << " channel(s), "
                << audio->bitsPerSample << " bit; expected "
                << expectedFormat->nSamplesPerSec << " Hz, "
                << expectedFormat->nChannels << " channel(s), "
                << expectedFormat->wBitsPerSample << " bit";
        LogBridgeEvent(message.str());
    }
    return formatMatches;
}

bool IsAbortRequested(ISpTTSEngineSite* site) {
    return site && (site->GetActions() & SPVES_ABORT) != 0;
}

HRESULT WritePcmBytes(ISpTTSEngineSite* site, const std::vector<std::uint8_t>& bytes) {
    if (!site || bytes.empty()) {
        return E_INVALIDARG;
    }
    ULONG bytesWritten = 0;
    return site->Write(
        bytes.data(),
        static_cast<ULONG>(bytes.size()),
        &bytesWritten);
}

std::vector<std::uint8_t> MakeSilenceBytes(const PcmAudio& audio) {
    if (audio.sampleRateHz == 0 || audio.channels == 0 || audio.bitsPerSample != 16) {
        return {};
    }
    const size_t bytesPerSample = audio.bitsPerSample / 8;
    const size_t frameCount = (audio.sampleRateHz * kInterChunkPauseMs) / 1000;
    return std::vector<std::uint8_t>(frameCount * audio.channels * bytesPerSample, 0);
}

HRESULT TryWriteServiceAudio(
    const std::wstring& text,
    const WAVEFORMATEX* expectedFormat,
    ISpTTSEngineSite* site,
    bool* wroteAudio) {
    if (!wroteAudio) {
        return E_POINTER;
    }
    *wroteAudio = false;
    const std::vector<std::wstring> chunks = SplitTextForService(text);
    if (chunks.empty()) {
        LogBridgeEvent("service synthesis skipped: no text chunks");
        return S_FALSE;
    }
    {
        std::ostringstream message;
        message << "service synthesis request: chars=" << text.size()
                << ", chunks=" << chunks.size();
        LogBridgeEvent(message.str());
    }

    for (size_t index = 0; index < chunks.size(); ++index) {
        if (IsAbortRequested(site)) {
            LogBridgeEvent("service synthesis aborted before next chunk");
            return S_OK;
        }

        PcmAudio chunkAudio;
        if (!SynthesizeChunkFromService(chunks[index], expectedFormat, &chunkAudio)) {
            std::ostringstream message;
            message << "service synthesis failed for chunk " << (index + 1)
                    << " of " << chunks.size()
                    << ", chars=" << chunks[index].size();
            LogBridgeEvent(message.str());
            return *wroteAudio ? S_OK : S_FALSE;
        }

        const HRESULT writeResult = WritePcmBytes(site, chunkAudio.bytes);
        if (FAILED(writeResult)) {
            LogBridgeEvent("SAPI site Write failed for service audio chunk");
            return writeResult;
        }
        *wroteAudio = true;

        if (index + 1 < chunks.size()) {
            const std::vector<std::uint8_t> silence = MakeSilenceBytes(chunkAudio);
            if (!silence.empty()) {
                const HRESULT silenceResult = WritePcmBytes(site, silence);
                if (FAILED(silenceResult)) {
                    LogBridgeEvent("SAPI site Write failed for inter-chunk silence");
                    return silenceResult;
                }
            }
        }
    }
    return *wroteAudio ? S_OK : S_FALSE;
}

}  // namespace

// {7F241B98-6F49-4A18-9A40-98764D039A1B}
const CLSID CLSID_TtsPlatformSapiEngine = {
    0x7f241b98,
    0x6f49,
    0x4a18,
    {0x9a, 0x40, 0x98, 0x76, 0x4d, 0x03, 0x9a, 0x1b},
};

TtsPlatformSapiEngine::TtsPlatformSapiEngine() : refCount_(1), token_(nullptr) {
    DllAddRef();
}

STDMETHODIMP TtsPlatformSapiEngine::QueryInterface(REFIID riid, void** object) {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (riid == IID_IUnknown || riid == __uuidof(ISpTTSEngine)) {
        *object = static_cast<ISpTTSEngine*>(this);
    } else if (riid == __uuidof(ISpObjectWithToken)) {
        *object = static_cast<ISpObjectWithToken*>(this);
    } else {
        return E_NOINTERFACE;
    }
    AddRef();
    return S_OK;
}

STDMETHODIMP_(ULONG) TtsPlatformSapiEngine::AddRef() {
    return ++refCount_;
}

STDMETHODIMP_(ULONG) TtsPlatformSapiEngine::Release() {
    const ULONG count = --refCount_;
    if (count == 0) {
        if (token_) {
            token_->Release();
            token_ = nullptr;
        }
        DllRelease();
        delete this;
    }
    return count;
}

STDMETHODIMP TtsPlatformSapiEngine::Speak(
    DWORD,
    REFGUID formatId,
    const WAVEFORMATEX* waveFormatEx,
    const SPVTEXTFRAG* textFragment,
    ISpTTSEngineSite* site) {
    if (!site) {
        return E_POINTER;
    }
    if (!IsSupportedFormat(formatId, waveFormatEx)) {
        return E_INVALIDARG;
    }

    bool wroteServiceAudio = false;
    const HRESULT serviceResult = TryWriteServiceAudio(
        CollectText(textFragment),
        waveFormatEx,
        site,
        &wroteServiceAudio);
    if (FAILED(serviceResult) || wroteServiceAudio) {
        return serviceResult;
    }

    const std::vector<int16_t> pcm = MakeTonePcm();
    ULONG bytesWritten = 0;
    return site->Write(
        pcm.data(),
        static_cast<ULONG>(pcm.size() * sizeof(int16_t)),
        &bytesWritten);
}

STDMETHODIMP TtsPlatformSapiEngine::GetOutputFormat(
    const GUID*,
    const WAVEFORMATEX*,
    GUID* outputFormatId,
    WAVEFORMATEX** outputWaveFormatEx) {
    if (!outputFormatId || !outputWaveFormatEx) {
        return E_POINTER;
    }
    *outputFormatId = SPDFID_WaveFormatEx;
    *outputWaveFormatEx = AllocateWaveFormat();
    if (!*outputWaveFormatEx) {
        return E_OUTOFMEMORY;
    }
    return S_OK;
}

STDMETHODIMP TtsPlatformSapiEngine::SetObjectToken(ISpObjectToken* token) {
    if (token_) {
        token_->Release();
        token_ = nullptr;
    }
    token_ = token;
    if (token_) {
        token_->AddRef();
    }
    return S_OK;
}

STDMETHODIMP TtsPlatformSapiEngine::GetObjectToken(ISpObjectToken** token) {
    if (!token) {
        return E_POINTER;
    }
    *token = token_;
    if (*token) {
        (*token)->AddRef();
    }
    return S_OK;
}

TtsPlatformClassFactory::TtsPlatformClassFactory() : refCount_(1) {
    DllAddRef();
}

STDMETHODIMP TtsPlatformClassFactory::QueryInterface(REFIID riid, void** object) {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (riid == IID_IUnknown || riid == IID_IClassFactory) {
        *object = static_cast<IClassFactory*>(this);
    } else {
        return E_NOINTERFACE;
    }
    AddRef();
    return S_OK;
}

STDMETHODIMP_(ULONG) TtsPlatformClassFactory::AddRef() {
    return ++refCount_;
}

STDMETHODIMP_(ULONG) TtsPlatformClassFactory::Release() {
    const ULONG count = --refCount_;
    if (count == 0) {
        DllRelease();
        delete this;
    }
    return count;
}

STDMETHODIMP TtsPlatformClassFactory::CreateInstance(
    IUnknown* outer,
    REFIID riid,
    void** object) {
    if (outer) {
        return CLASS_E_NOAGGREGATION;
    }
    auto* engine = new (std::nothrow) TtsPlatformSapiEngine();
    if (!engine) {
        return E_OUTOFMEMORY;
    }
    const HRESULT result = engine->QueryInterface(riid, object);
    engine->Release();
    return result;
}

STDMETHODIMP TtsPlatformClassFactory::LockServer(BOOL lock) {
    if (lock) {
        DllAddRef();
        ++g_lockCount;
    } else {
        DllRelease();
        --g_lockCount;
    }
    return S_OK;
}

void DllAddRef() {
    ++g_objectCount;
}

void DllRelease() {
    --g_objectCount;
}

extern "C" bool DllCanUnloadNowInternal() {
    return g_objectCount.load() == 0 && g_lockCount.load() == 0;
}
