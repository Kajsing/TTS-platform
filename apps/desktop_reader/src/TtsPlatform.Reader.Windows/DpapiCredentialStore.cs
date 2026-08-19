using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Windows;

public sealed class DpapiCredentialStore(string? directory = null)
{
    private const uint CryptProtectUiForbidden = 0x1;
    private readonly string _directory = directory ?? DesktopPaths.RemoteCredentialsDirectory;

    public void Save(string credentialId, string credential)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(credential);
        WriteProtectedAtomically(CredentialPath(credentialId), credential);
    }

    public string? Load(string credentialId)
    {
        var path = CredentialPath(credentialId);
        if (!File.Exists(path))
        {
            return null;
        }
        try
        {
            return Encoding.UTF8.GetString(Unprotect(File.ReadAllBytes(path))).Trim();
        }
        catch (Win32Exception exception)
        {
            throw new ReaderTokenUnavailableException(
                $"Windows could not unlock the remote credential: {exception.Message}");
        }
    }

    public void Delete(string credentialId)
    {
        var path = CredentialPath(credentialId);
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        var pendingPath = PendingCredentialPath(credentialId);
        if (File.Exists(pendingPath))
        {
            File.Delete(pendingPath);
        }
    }

    public void SavePending(string credentialId, string credential)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(credential);
        WriteProtectedAtomically(PendingCredentialPath(credentialId), credential);
    }

    public void PromotePending(string credentialId)
    {
        var pendingPath = PendingCredentialPath(credentialId);
        if (!File.Exists(pendingPath))
        {
            throw new ReaderTokenUnavailableException(
                "The pending remote credential could not be found.");
        }
        File.Move(pendingPath, CredentialPath(credentialId), true);
    }

    public void DeletePending(string credentialId)
    {
        var pendingPath = PendingCredentialPath(credentialId);
        if (File.Exists(pendingPath))
        {
            File.Delete(pendingPath);
        }
    }

    private string CredentialPath(string credentialId)
    {
        if (!Guid.TryParse(credentialId, out var parsed))
        {
            throw new ReaderClientConfigurationException(
                "The remote credential identifier is invalid.");
        }
        return Path.Combine(_directory, $"{parsed:D}.bin");
    }

    private string PendingCredentialPath(string credentialId) =>
        CredentialPath(credentialId) + ".pending";

    private void WriteProtectedAtomically(string path, string credential)
    {
        Directory.CreateDirectory(_directory);
        byte[] encrypted;
        try
        {
            encrypted = Protect(Encoding.UTF8.GetBytes(credential.Trim()));
        }
        catch (Win32Exception exception)
        {
            throw new ReaderTokenUnavailableException(
                $"Windows could not protect the remote credential: {exception.Message}");
        }
        var temporaryPath = path + $".{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllBytes(temporaryPath, encrypted);
            File.Move(temporaryPath, path, true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    private static byte[] Protect(byte[] plaintext) => Transform(plaintext, protect: true);

    private static byte[] Unprotect(byte[] ciphertext) => Transform(ciphertext, protect: false);

    private static byte[] Transform(byte[] input, bool protect)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Remote credentials require Windows DPAPI.");
        }
        var inputPointer = Marshal.AllocHGlobal(input.Length);
        try
        {
            Marshal.Copy(input, 0, inputPointer, input.Length);
            var inputBlob = new DataBlob(input.Length, inputPointer);
            DataBlob outputBlob;
            var succeeded = protect
                ? CryptProtectData(
                    ref inputBlob,
                    "TTS Platform Reader remote device credential",
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CryptProtectUiForbidden,
                    out outputBlob)
                : CryptUnprotectData(
                    ref inputBlob,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CryptProtectUiForbidden,
                    out outputBlob);
            if (!succeeded)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            try
            {
                var output = new byte[outputBlob.Size];
                Marshal.Copy(outputBlob.Data, output, 0, output.Length);
                return output;
            }
            finally
            {
                _ = LocalFree(outputBlob.Data);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(inputPointer);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct DataBlob(int size, IntPtr data)
    {
        public int Size = size;
        public IntPtr Data = data;
    }

    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(
        ref DataBlob dataIn,
        string description,
        IntPtr optionalEntropy,
        IntPtr reserved,
        IntPtr promptStruct,
        uint flags,
        out DataBlob dataOut);

    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(
        ref DataBlob dataIn,
        IntPtr description,
        IntPtr optionalEntropy,
        IntPtr reserved,
        IntPtr promptStruct,
        uint flags,
        out DataBlob dataOut);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);
}

public sealed class ProtectedCredentialTokenProvider(
    DpapiCredentialStore credentialStore,
    string credentialId) : ITokenProvider
{
    public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult(credentialStore.Load(credentialId));
    }
}
