#include "TtsPlatformSapiEngine.h"

#include <windows.h>

extern "C" bool DllCanUnloadNowInternal();

BOOL APIENTRY DllMain(HMODULE, DWORD, LPVOID) {
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** object) {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (clsid != CLSID_TtsPlatformSapiEngine) {
        return CLASS_E_CLASSNOTAVAILABLE;
    }

    auto* factory = new (std::nothrow) TtsPlatformClassFactory();
    if (!factory) {
        return E_OUTOFMEMORY;
    }
    const HRESULT result = factory->QueryInterface(riid, object);
    factory->Release();
    return result;
}

STDAPI DllCanUnloadNow() {
    return DllCanUnloadNowInternal() ? S_OK : S_FALSE;
}

STDAPI DllRegisterServer() {
    return E_NOTIMPL;
}

STDAPI DllUnregisterServer() {
    return E_NOTIMPL;
}

