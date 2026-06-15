#pragma once

#include <sapi.h>
#include <sphelper.h>
#include <windows.h>

#include <atomic>

// Minimal ATL-free SAPI 5 TTS engine skeleton.
//
// This is the native feasibility target after the dummy token spike. It is
// intentionally small: the engine returns generated PCM through the SAPI engine
// site. The localhost /v1/tts bridge belongs in the next slice after TextAloud
// can instantiate this COM class and call Speak.

extern const CLSID CLSID_TtsPlatformSapiEngine;

class TtsPlatformSapiEngine final : public ISpTTSEngine, public ISpObjectWithToken {
public:
    TtsPlatformSapiEngine();

    STDMETHODIMP QueryInterface(REFIID riid, void** object) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    STDMETHODIMP Speak(
        DWORD speakFlags,
        REFGUID formatId,
        const WAVEFORMATEX* waveFormatEx,
        const SPVTEXTFRAG* textFragment,
        ISpTTSEngineSite* site) override;

    STDMETHODIMP GetOutputFormat(
        const GUID* targetFormatId,
        const WAVEFORMATEX* targetWaveFormatEx,
        GUID* outputFormatId,
        WAVEFORMATEX** outputWaveFormatEx) override;

    STDMETHODIMP SetObjectToken(ISpObjectToken* token) override;
    STDMETHODIMP GetObjectToken(ISpObjectToken** token) override;

private:
    ~TtsPlatformSapiEngine() = default;

    std::atomic<ULONG> refCount_;
    ISpObjectToken* token_;
};

class TtsPlatformClassFactory final : public IClassFactory {
public:
    TtsPlatformClassFactory();

    STDMETHODIMP QueryInterface(REFIID riid, void** object) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** object) override;
    STDMETHODIMP LockServer(BOOL lock) override;

private:
    ~TtsPlatformClassFactory() = default;

    std::atomic<ULONG> refCount_;
};

void DllAddRef();
void DllRelease();

