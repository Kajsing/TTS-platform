using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace TtsPlatform.Reader.Client;

public sealed class PinnedServerCertificateValidator
{
    private const string ServerAuthenticationOid = "1.3.6.1.5.5.7.3.1";
    private readonly byte[] _expectedPin;

    public PinnedServerCertificateValidator(string serverSpkiPin)
    {
        if (string.IsNullOrWhiteSpace(serverSpkiPin) ||
            !serverSpkiPin.StartsWith("sha256/", StringComparison.Ordinal))
        {
            throw new ReaderClientConfigurationException("The remote server pin is invalid.");
        }
        try
        {
            _expectedPin = Convert.FromBase64String(serverSpkiPin[7..]);
        }
        catch (FormatException exception)
        {
            throw new ReaderClientConfigurationException("The remote server pin is invalid.", exception);
        }
        if (_expectedPin.Length != SHA256.HashSizeInBytes)
        {
            throw new ReaderClientConfigurationException("The remote server pin is invalid.");
        }
    }

    public bool Validate(
        object? _,
        X509Certificate? certificate,
        X509Chain? chain,
        SslPolicyErrors policyErrors)
    {
        if (certificate is null ||
            policyErrors.HasFlag(SslPolicyErrors.RemoteCertificateNotAvailable) ||
            policyErrors.HasFlag(SslPolicyErrors.RemoteCertificateNameMismatch))
        {
            return false;
        }
        using var certificate2 = new X509Certificate2(certificate);
        var now = DateTimeOffset.UtcNow;
        if (now < certificate2.NotBefore.ToUniversalTime() || now > certificate2.NotAfter.ToUniversalTime())
        {
            return false;
        }
        if (!HasServerAuthenticationUsage(certificate2))
        {
            return false;
        }
        if (policyErrors.HasFlag(SslPolicyErrors.RemoteCertificateChainErrors) && chain is null)
        {
            return false;
        }
        if (chain is not null && chain.ChainStatus.Any(status =>
            status.Status is not X509ChainStatusFlags.NoError and
                not X509ChainStatusFlags.UntrustedRoot and
                not X509ChainStatusFlags.PartialChain))
        {
            return false;
        }
        try
        {
            using var ecdsa = certificate2.GetECDsaPublicKey();
            if (ecdsa is null || ecdsa.KeySize != 256)
            {
                return false;
            }
            var actualPin = SHA256.HashData(ecdsa.ExportSubjectPublicKeyInfo());
            return CryptographicOperations.FixedTimeEquals(actualPin, _expectedPin);
        }
        catch (CryptographicException)
        {
            return false;
        }
    }

    public HttpClientHandler CreateHttpClientHandler() => new()
    {
        ServerCertificateCustomValidationCallback = Validate,
        AllowAutoRedirect = false,
        UseCookies = false,
    };

    private static bool HasServerAuthenticationUsage(X509Certificate2 certificate)
    {
        var extension = certificate.Extensions
            .OfType<X509EnhancedKeyUsageExtension>()
            .FirstOrDefault();
        return extension is not null && extension.EnhancedKeyUsages
            .Cast<Oid>()
            .Any(usage => string.Equals(
                usage.Value,
                ServerAuthenticationOid,
                StringComparison.Ordinal));
    }
}
