using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class PinnedServerCertificateValidatorTests
{
    [Fact]
    public void Validator_requires_exact_pin_name_usage_and_a_known_chain_error()
    {
        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var request = new CertificateRequest("CN=10.8.0.1", key, HashAlgorithmName.SHA256);
        var usages = new OidCollection { new("1.3.6.1.5.5.7.3.1") };
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(usages, false));
        var names = new SubjectAlternativeNameBuilder();
        names.AddIpAddress(System.Net.IPAddress.Parse("10.8.0.1"));
        request.CertificateExtensions.Add(names.Build());
        using var certificate = request.CreateSelfSigned(
            DateTimeOffset.UtcNow.AddMinutes(-1),
            DateTimeOffset.UtcNow.AddDays(30));
        var pin = "sha256/" + Convert.ToBase64String(
            SHA256.HashData(key.ExportSubjectPublicKeyInfo()));
        var validator = new PinnedServerCertificateValidator(pin);
        var wrongPin = new PinnedServerCertificateValidator(
            "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");

        Assert.True(validator.Validate(null, certificate, null, SslPolicyErrors.None));
        Assert.False(wrongPin.Validate(null, certificate, null, SslPolicyErrors.None));
        Assert.False(validator.Validate(
            null,
            certificate,
            null,
            SslPolicyErrors.RemoteCertificateNameMismatch));
        Assert.False(validator.Validate(
            null,
            certificate,
            null,
            SslPolicyErrors.RemoteCertificateChainErrors));
    }
}
