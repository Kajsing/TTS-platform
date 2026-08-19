using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace TtsPlatform.Reader.Client;

public sealed record RemoteRotationResult(
    string RotationId,
    string PendingCredential,
    int ExpiresInSeconds);

public sealed class RemoteCredentialRotationClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public async Task<RemoteRotationResult> BeginAsync(
        string endpoint,
        string serverSpkiPin,
        string currentCredential,
        CancellationToken cancellationToken = default)
    {
        var result = await SendAsync<RemoteRotationResult>(
            endpoint,
            serverSpkiPin,
            currentCredential,
            "v1/remote/device/rotation",
            new { },
            cancellationToken).ConfigureAwait(false);
        if (!Guid.TryParse(result.RotationId, out _) ||
            string.IsNullOrWhiteSpace(result.PendingCredential) ||
            result.ExpiresInSeconds is < 1 or > 600)
        {
            throw new ReaderServiceUnavailableException(
                "The remote Reader returned an invalid credential rotation.");
        }
        return result;
    }

    public async Task ConfirmAsync(
        string endpoint,
        string serverSpkiPin,
        string currentCredential,
        string rotationId,
        string pendingCredential,
        CancellationToken cancellationToken = default)
    {
        if (!Guid.TryParse(rotationId, out _) || string.IsNullOrWhiteSpace(pendingCredential))
        {
            throw new ReaderClientConfigurationException(
                "The pending remote credential rotation is invalid.");
        }
        _ = await SendAsync<JsonElement>(
            endpoint,
            serverSpkiPin,
            currentCredential,
            "v1/remote/device/rotation/confirm",
            new { rotation_id = rotationId, pending_credential = pendingCredential },
            cancellationToken).ConfigureAwait(false);
    }

    private static async Task<T> SendAsync<T>(
        string endpoint,
        string serverSpkiPin,
        string currentCredential,
        string relativeUrl,
        object body,
        CancellationToken cancellationToken)
    {
        var validator = new PinnedServerCertificateValidator(serverSpkiPin);
        using var client = new HttpClient(validator.CreateHttpClientHandler())
        {
            BaseAddress = ServiceBaseUrl.ParseRemote(endpoint),
            Timeout = TimeSpan.FromSeconds(15),
        };
        using var request = new HttpRequestMessage(HttpMethod.Post, relativeUrl)
        {
            Content = JsonContent.Create(body, options: JsonOptions),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue(
            "Bearer",
            currentCredential);
        HttpResponseMessage response;
        try
        {
            response = await client.SendAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw new ReaderServiceUnavailableException(
                "The remote Reader connection or server identity could not be verified.",
                exception);
        }
        catch (TaskCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ReaderServiceUnavailableException(
                "The remote Reader credential rotation timed out.",
                exception);
        }
        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                throw new ReaderApiException(
                    "remote_rotation_failed",
                    $"Credential rotation returned HTTP {(int)response.StatusCode}.",
                    (int)response.StatusCode);
            }
            return await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
                .ConfigureAwait(false)
                ?? throw new ReaderServiceUnavailableException(
                    "The remote Reader returned an empty rotation response.");
        }
    }
}
