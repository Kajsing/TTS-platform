using System.Net.Http.Json;
using System.Text.Json;

namespace TtsPlatform.Reader.Client;

public sealed record RemotePairingInvitation(
    int ContractVersion,
    string Endpoint,
    string ServerSpkiPin,
    string TicketId,
    string TicketSecret,
    DateTimeOffset ExpiresAt);

public sealed record RemotePairingDevice(
    string Id,
    string DisplayName,
    DateTimeOffset CreatedAt,
    DateTimeOffset? LastUsedAt,
    DateTimeOffset? RevokedAt,
    int Generation);

public sealed record RemotePairingResult(
    int ContractVersion,
    RemotePairingDevice Device,
    string Credential);

public sealed class RemotePairingClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public static string FormatInvitation(RemotePairingInvitation invitation) =>
        JsonSerializer.Serialize(invitation, JsonOptions);

    public static RemotePairingInvitation ParseInvitation(string invitationJson)
    {
        if (string.IsNullOrWhiteSpace(invitationJson) || invitationJson.Length > 8192)
        {
            throw new ReaderClientConfigurationException("The pairing invitation is empty or too large.");
        }
        try
        {
            var invitation = JsonSerializer.Deserialize<RemotePairingInvitation>(invitationJson, JsonOptions)
                ?? throw new ReaderClientConfigurationException("The pairing invitation is invalid.");
            if (invitation.ContractVersion != 1 ||
                string.IsNullOrWhiteSpace(invitation.TicketId) ||
                string.IsNullOrWhiteSpace(invitation.TicketSecret) ||
                invitation.ExpiresAt <= DateTimeOffset.UtcNow)
            {
                throw new ReaderClientConfigurationException("The pairing invitation is invalid or expired.");
            }
            _ = ServiceBaseUrl.ParseRemote(invitation.Endpoint);
            _ = new PinnedServerCertificateValidator(invitation.ServerSpkiPin);
            return invitation;
        }
        catch (JsonException exception)
        {
            throw new ReaderClientConfigurationException("The pairing invitation is invalid.", exception);
        }
    }

    public async Task<RemotePairingResult> PairAsync(
        RemotePairingInvitation invitation,
        string deviceName,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(invitation);
        if (string.IsNullOrWhiteSpace(deviceName) || deviceName.Trim().Length > 80)
        {
            throw new ReaderClientConfigurationException(
                "Device name must contain 1 to 80 characters.");
        }
        var validator = new PinnedServerCertificateValidator(invitation.ServerSpkiPin);
        using var httpClient = new HttpClient(validator.CreateHttpClientHandler())
        {
            BaseAddress = ServiceBaseUrl.ParseRemote(invitation.Endpoint),
            Timeout = TimeSpan.FromSeconds(15),
        };
        HttpResponseMessage response;
        try
        {
            response = await httpClient.PostAsJsonAsync(
                "v1/remote/pair",
                new
                {
                    contract_version = invitation.ContractVersion,
                    ticket_id = invitation.TicketId,
                    ticket_secret = invitation.TicketSecret,
                    device_name = deviceName.Trim(),
                },
                JsonOptions,
                cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw new ReaderServiceUnavailableException(
                "The paired server identity or private-network connection could not be verified.",
                exception);
        }
        catch (TaskCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ReaderServiceUnavailableException(
                "Remote pairing timed out. Check the private-network connection and try again.",
                exception);
        }
        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                throw new ReaderApiException(
                    "remote_pairing_failed",
                    $"Remote pairing failed with HTTP {(int)response.StatusCode}.",
                    (int)response.StatusCode);
            }
            var result = await response.Content.ReadFromJsonAsync<RemotePairingResult>(
                JsonOptions,
                cancellationToken).ConfigureAwait(false);
            if (result is null || result.ContractVersion != 1 || string.IsNullOrWhiteSpace(result.Credential))
            {
                throw new ReaderServiceUnavailableException("The remote server returned an invalid pairing result.");
            }
            return result;
        }
    }
}
