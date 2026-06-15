#include "TtsPlatformSapiEngine.h"

#include <cmath>
#include <cstdint>
#include <new>
#include <vector>

namespace {

constexpr ULONG kSampleRateHz = 22050;
constexpr WORD kChannelCount = 1;
constexpr WORD kBitsPerSample = 16;
constexpr double kToneHz = 440.0;
constexpr double kToneSeconds = 0.35;
constexpr double kPi = 3.14159265358979323846;

std::atomic<ULONG> g_objectCount{0};
std::atomic<ULONG> g_lockCount{0};

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
    const SPVTEXTFRAG*,
    ISpTTSEngineSite* site) {
    if (!site) {
        return E_POINTER;
    }
    if (!IsSupportedFormat(formatId, waveFormatEx)) {
        return E_INVALIDARG;
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
