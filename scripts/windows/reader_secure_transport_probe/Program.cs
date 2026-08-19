using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Net.Security;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using TtsPlatform.Reader.Client;

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Length == 2 && string.Equals(args[0], "generate", StringComparison.Ordinal))
            {
                GenerateCertificate(args[1]);
                return 0;
            }

            if (args.Length == 4 && string.Equals(args[0], "probe", StringComparison.Ordinal))
            {
                await ProbeAsync(args[1], args[2], args[3]).ConfigureAwait(false);
                return 0;
            }

            if (args.Length == 3 && string.Equals(args[0], "pair", StringComparison.Ordinal))
            {
                await PairAsync(args[1], args[2]).ConfigureAwait(false);
                return 0;
            }

            Console.Error.WriteLine(
                "Usage: ReaderSecureTransportProbe generate <output-directory> | " +
                "probe <https-base-url> <sha256-spki-pin> <token-file> | " +
                "pair <invitation-file> <device-name>");
            return 2;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"Secure transport probe failed: {exception.GetType().Name}: {exception.Message}");
            return 1;
        }
    }

    private static async Task PairAsync(string invitationFile, string deviceName)
    {
        var invitation = RemotePairingClient.ParseInvitation(
            File.ReadAllText(Path.GetFullPath(invitationFile), Encoding.UTF8));
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        var result = await new RemotePairingClient().PairAsync(
            invitation,
            deviceName,
            timeout.Token).ConfigureAwait(false);
        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                status = "ok",
                credential = result.Credential,
                device = new
                {
                    id = result.Device.Id,
                    display_name = result.Device.DisplayName,
                },
            },
            JsonOptions));
    }

    private static void GenerateCertificate(string outputDirectory)
    {
        var output = Path.GetFullPath(outputDirectory);
        Directory.CreateDirectory(output);
        var certificatePath = Path.Combine(output, "reader-spike-cert.pem");
        var privateKeyPath = Path.Combine(output, "reader-spike-key.pem");

        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var request = new CertificateRequest(
            "CN=TTS Platform Reader U7 Transport Spike",
            key,
            HashAlgorithmName.SHA256);
        request.CertificateExtensions.Add(
            new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(
            new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature, true));
        var usages = new OidCollection
        {
            new Oid("1.3.6.1.5.5.7.3.1", "TLS Web Server Authentication"),
        };
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(usages, true));
        request.CertificateExtensions.Add(
            new X509SubjectKeyIdentifierExtension(request.PublicKey, false));
        var names = new SubjectAlternativeNameBuilder();
        names.AddDnsName("localhost");
        names.AddIpAddress(IPAddress.Loopback);
        request.CertificateExtensions.Add(names.Build());

        var notBefore = DateTimeOffset.UtcNow.AddMinutes(-5);
        var notAfter = DateTimeOffset.UtcNow.AddDays(7);
        using var certificate = request.CreateSelfSigned(notBefore, notAfter);
        File.WriteAllText(certificatePath, certificate.ExportCertificatePem(), Encoding.ASCII);
        File.WriteAllText(privateKeyPath, key.ExportPkcs8PrivateKeyPem(), Encoding.ASCII);

        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                certificate_path = certificatePath,
                private_key_path = privateKeyPath,
                spki_pin = CertificatePin.Compute(certificate),
                not_after = notAfter,
                algorithm = "ECDSA P-256 / SHA-256",
                subject_alternative_names = new[] { "localhost", "127.0.0.1" },
            },
            JsonOptions));
    }

    private static async Task ProbeAsync(string baseUrl, string pin, string tokenFile)
    {
        var baseUri = new Uri(baseUrl, UriKind.Absolute);
        if (!string.Equals(baseUri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(baseUri.Host, "localhost", StringComparison.OrdinalIgnoreCase) ||
            baseUri.AbsolutePath != "/" ||
            !string.IsNullOrEmpty(baseUri.Query) ||
            !string.IsNullOrEmpty(baseUri.Fragment) ||
            !string.IsNullOrEmpty(baseUri.UserInfo))
        {
            throw new InvalidOperationException(
                "The U7 probe accepts only an HTTPS localhost origin without credentials or a path.");
        }

        var token = File.ReadAllText(Path.GetFullPath(tokenFile), Encoding.UTF8).Trim();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("The probe token file is empty.");
        }

        var validator = new PinnedCertificateValidator(pin);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        var tlsProtocol = await ProbeTlsAsync(baseUri, validator, timeout.Token)
            .ConfigureAwait(false);

        using var handler = new HttpClientHandler
        {
            CheckCertificateRevocationList = false,
            ServerCertificateCustomValidationCallback = validator.Validate,
        };
        using var http = new HttpClient(handler)
        {
            BaseAddress = baseUri,
            Timeout = TimeSpan.FromSeconds(20),
        };
        http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        http.DefaultRequestHeaders.CacheControl = new CacheControlHeaderValue { NoStore = true };

        using var capabilitiesResponse = await http.GetAsync(
            "v1/reader/capabilities",
            timeout.Token).ConfigureAwait(false);
        capabilitiesResponse.EnsureSuccessStatusCode();
        using var capabilities = JsonDocument.Parse(
            await capabilitiesResponse.Content.ReadAsStringAsync(timeout.Token)
                .ConfigureAwait(false));
        if (!capabilities.RootElement.GetProperty("enabled").GetBoolean())
        {
            throw new InvalidOperationException("Reader capabilities reported disabled.");
        }

        using var createResponse = await http.PostAsJsonAsync(
            "v1/reader/documents",
            new
            {
                title = "U7 secure transport spike",
                source_type = "plain_text",
                text = "Encrypted Reader transport is active.",
                allow_duplicate = true,
            },
            timeout.Token).ConfigureAwait(false);
        createResponse.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(
            await createResponse.Content.ReadAsStringAsync(timeout.Token).ConfigureAwait(false));
        var documentId = document.RootElement.GetProperty("id").GetString()
            ?? throw new InvalidOperationException("The Reader document response omitted its ID.");
        var contentRevision = document.RootElement.GetProperty("content_revision").GetInt32();

        var stream = await ProbeReaderWebSocketAsync(
            baseUri,
            validator,
            token,
            documentId,
            contentRevision,
            timeout.Token).ConfigureAwait(false);
        if (validator.SuccessfulValidations < 3)
        {
            throw new InvalidOperationException(
                "The certificate pin was not observed on TLS, HTTPS, and WSS connections.");
        }

        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                status = "ok",
                tls_protocol = tlsProtocol,
                certificate_pin_validated = true,
                certificate_pin_validation_count = validator.SuccessfulValidations,
                https_reader_capabilities = true,
                https_reader_document_created = true,
                wss_reader_started = stream.Started,
                wss_reader_marks = stream.Marks,
                wss_reader_audio_bytes = stream.AudioBytes,
                wss_reader_completed = stream.Completed,
            },
            JsonOptions));
    }

    private static async Task<string> ProbeTlsAsync(
        Uri baseUri,
        PinnedCertificateValidator validator,
        CancellationToken cancellationToken)
    {
        using var tcp = new TcpClient();
        await tcp.ConnectAsync(baseUri.Host, baseUri.Port, cancellationToken)
            .ConfigureAwait(false);
        using var tls = new SslStream(tcp.GetStream(), false, validator.Validate);
        await tls.AuthenticateAsClientAsync(
            new SslClientAuthenticationOptions
            {
                TargetHost = baseUri.Host,
                EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
                CertificateRevocationCheckMode = X509RevocationMode.NoCheck,
            },
            cancellationToken).ConfigureAwait(false);
        if (tls.SslProtocol is not (SslProtocols.Tls12 or SslProtocols.Tls13))
        {
            throw new AuthenticationException("The server did not negotiate TLS 1.2 or TLS 1.3.");
        }
        return tls.SslProtocol.ToString();
    }

    private static async Task<StreamProbeResult> ProbeReaderWebSocketAsync(
        Uri baseUri,
        PinnedCertificateValidator validator,
        string token,
        string documentId,
        int contentRevision,
        CancellationToken cancellationToken)
    {
        using var socket = new ClientWebSocket();
        socket.Options.RemoteCertificateValidationCallback = validator.Validate;
        socket.Options.SetRequestHeader("Authorization", $"Bearer {token}");
        socket.Options.SetRequestHeader("Cache-Control", "no-store");
        var streamUri = new UriBuilder(baseUri)
        {
            Scheme = "wss",
            Path = "/v1/reader/stream",
        }.Uri;
        await socket.ConnectAsync(streamUri, cancellationToken).ConfigureAwait(false);
        var start = JsonSerializer.SerializeToUtf8Bytes(new
        {
            type = "start",
            payload = new
            {
                document_id = documentId,
                cursor = new
                {
                    block_ordinal = 0,
                    character_offset = 0,
                    content_revision = contentRevision,
                },
            },
        });
        await socket.SendAsync(start, WebSocketMessageType.Text, true, cancellationToken)
            .ConfigureAwait(false);

        var started = false;
        var completed = false;
        var marks = 0;
        long audioBytes = 0;
        var pendingMark = false;
        string? streamId = null;
        for (var messageIndex = 0; messageIndex < 512 && !completed; messageIndex++)
        {
            var message = await ReceiveMessageAsync(socket, cancellationToken).ConfigureAwait(false);
            if (message.Type == WebSocketMessageType.Binary)
            {
                if (!pendingMark)
                {
                    throw new InvalidOperationException("Reader WSS returned audio without a mark.");
                }
                audioBytes += message.Payload.Length;
                pendingMark = false;
                continue;
            }

            using var payload = JsonDocument.Parse(message.Payload);
            var type = payload.RootElement.GetProperty("type").GetString();
            switch (type)
            {
                case "started":
                    started = true;
                    streamId = payload.RootElement.GetProperty("stream_id").GetString();
                    break;
                case "mark":
                    if (pendingMark)
                    {
                        throw new InvalidOperationException(
                            "Reader WSS returned two marks without intervening audio.");
                    }
                    pendingMark = true;
                    marks++;
                    break;
                case "done":
                    if (pendingMark)
                    {
                        throw new InvalidOperationException(
                            "Reader WSS completed while a mark was still waiting for audio.");
                    }
                    completed = true;
                    break;
                case "error":
                    throw new InvalidOperationException("Reader WSS returned a typed error.");
            }
        }

        if (!started || !completed || marks == 0 || audioBytes == 0 || streamId is null)
        {
            throw new InvalidOperationException(
                "Reader WSS did not complete the expected started/mark/audio/done sequence.");
        }
        var release = JsonSerializer.SerializeToUtf8Bytes(new { type = "release", stream_id = streamId });
        await socket.SendAsync(release, WebSocketMessageType.Text, true, cancellationToken)
            .ConfigureAwait(false);
        return new StreamProbeResult(started, marks, audioBytes, completed);
    }

    private static async Task<WebSocketMessage> ReceiveMessageAsync(
        ClientWebSocket socket,
        CancellationToken cancellationToken)
    {
        var buffer = new byte[16 * 1024];
        using var payload = new MemoryStream();
        WebSocketReceiveResult result;
        do
        {
            result = await socket.ReceiveAsync(
                new ArraySegment<byte>(buffer),
                cancellationToken).ConfigureAwait(false);
            if (result.MessageType == WebSocketMessageType.Close)
            {
                throw new WebSocketException("Reader WSS closed before completing the probe.");
            }
            if (payload.Length + result.Count > 2 * 1024 * 1024)
            {
                throw new InvalidOperationException("Reader WSS message exceeded the probe limit.");
            }
            payload.Write(buffer, 0, result.Count);
        }
        while (!result.EndOfMessage);
        return new WebSocketMessage(result.MessageType, payload.ToArray());
    }

    private sealed record StreamProbeResult(bool Started, int Marks, long AudioBytes, bool Completed);

    private sealed record WebSocketMessage(WebSocketMessageType Type, byte[] Payload);
}

internal static class CertificatePin
{
    public static string Compute(X509Certificate2 certificate)
    {
        byte[] subjectPublicKeyInfo;
        using (var ecdsa = certificate.GetECDsaPublicKey())
        {
            if (ecdsa is not null)
            {
                subjectPublicKeyInfo = ecdsa.ExportSubjectPublicKeyInfo();
                return Format(subjectPublicKeyInfo);
            }
        }
        using (var rsa = certificate.GetRSAPublicKey())
        {
            if (rsa is null)
            {
                throw new CryptographicException("The certificate uses an unsupported public key.");
            }
            subjectPublicKeyInfo = rsa.ExportSubjectPublicKeyInfo();
        }
        return Format(subjectPublicKeyInfo);
    }

    private static string Format(byte[] subjectPublicKeyInfo) =>
        "sha256/" + Convert.ToBase64String(SHA256.HashData(subjectPublicKeyInfo));
}

internal sealed class PinnedCertificateValidator(string expectedPin)
{
    private readonly byte[] _expectedPin = Encoding.ASCII.GetBytes(expectedPin);
    private int _successfulValidations;

    public int SuccessfulValidations => Volatile.Read(ref _successfulValidations);

    public bool Validate(
        object sender,
        X509Certificate? certificate,
        X509Chain? chain,
        SslPolicyErrors errors)
    {
        _ = sender;
        _ = chain;
        if (certificate is null ||
            (errors & ~SslPolicyErrors.RemoteCertificateChainErrors) != SslPolicyErrors.None)
        {
            return false;
        }

        using var candidate = new X509Certificate2(certificate);
        var now = DateTime.UtcNow;
        if (now < candidate.NotBefore.ToUniversalTime() || now > candidate.NotAfter.ToUniversalTime())
        {
            return false;
        }
        var serverUsage = candidate.Extensions
            .OfType<X509EnhancedKeyUsageExtension>()
            .SelectMany(extension => extension.EnhancedKeyUsages.Cast<Oid>())
            .Any(usage => string.Equals(usage.Value, "1.3.6.1.5.5.7.3.1", StringComparison.Ordinal));
        if (!serverUsage)
        {
            return false;
        }

        var actualPin = Encoding.ASCII.GetBytes(CertificatePin.Compute(candidate));
        var matches = actualPin.Length == _expectedPin.Length &&
            CryptographicOperations.FixedTimeEquals(actualPin, _expectedPin);
        if (matches)
        {
            Interlocked.Increment(ref _successfulValidations);
        }
        return matches;
    }
}
