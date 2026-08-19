using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace TtsPlatform.Reader.Client;

public sealed record RemoteFirewallStatus(
    bool Supported,
    bool Exists,
    bool Matches,
    string? RuleName = null,
    string? Message = null);

public sealed record RemoteServerProfile(
    int Version,
    string ProfileId,
    bool Enabled,
    string BindHost,
    int Port,
    string? ServerName,
    string Endpoint,
    string ServerSpkiPin,
    string FirewallMode,
    string FirewallRemoteAddress,
    string? FirewallInterfaceAlias,
    string FirewallProfile,
    string FirewallRuleName,
    string GatewayProgram,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

public sealed record RemoteAccessStatus(
    bool Configured,
    bool Enabled,
    bool Running,
    string? StartupError,
    RemoteServerProfile? Profile,
    int DeviceCount,
    string Transport,
    bool WireguardManagedByReader,
    RemoteFirewallStatus Firewall);

public sealed record RemoteSetupRequest(
    string BindHost,
    int Port,
    string? ServerName,
    string FirewallMode,
    string FirewallRemoteAddress,
    string? FirewallInterfaceAlias,
    string FirewallProfile,
    bool Start);

public sealed record RemoteDevicePage(IReadOnlyList<RemotePairingDevice> Devices);

public sealed class RemoteAccessAdminClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };
    private readonly HttpClient _httpClient;
    private readonly ITokenProvider _tokenProvider;

    public RemoteAccessAdminClient(
        HttpClient httpClient,
        string localServiceBaseUrl,
        ITokenProvider tokenProvider)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress = ServiceBaseUrl.Parse(localServiceBaseUrl);
        _tokenProvider = tokenProvider;
    }

    public Task<RemoteAccessStatus> GetStatusAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RemoteAccessStatus>(HttpMethod.Get, "v1/reader/remote/status", null, cancellationToken);

    public Task<RemoteAccessStatus> SetupAsync(
        RemoteSetupRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<RemoteAccessStatus>(HttpMethod.Post, "v1/reader/remote/setup", request, cancellationToken);

    public Task<RemotePairingInvitation> CreateInvitationAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<RemotePairingInvitation>(
            HttpMethod.Post,
            "v1/reader/remote/invitations",
            new { },
            cancellationToken);

    public Task<RemoteDevicePage> GetDevicesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RemoteDevicePage>(HttpMethod.Get, "v1/reader/remote/devices", null, cancellationToken);

    public Task<RemoteAccessStatus> DisableAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RemoteAccessStatus>(
            HttpMethod.Post,
            "v1/reader/remote/disable",
            new { },
            cancellationToken);

    public async Task RevokeDeviceAsync(
        string deviceId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(deviceId);
        _ = await SendAsync<JsonElement>(
            HttpMethod.Delete,
            $"v1/reader/remote/devices/{Uri.EscapeDataString(deviceId)}",
            null,
            cancellationToken).ConfigureAwait(false);
    }

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string relativeUrl,
        object? body,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativeUrl);
        var token = (await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false))?.Trim();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ReaderTokenUnavailableException(
                "Choose the local service token file before managing remote access.");
        }
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: JsonOptions);
        }
        HttpResponseMessage response;
        try
        {
            response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException exception)
        {
            throw new ReaderServiceUnavailableException(
                "The local Reader service could not be reached.",
                exception);
        }
        catch (TaskCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new ReaderServiceUnavailableException(
                "The local Reader service did not respond in time.",
                exception);
        }
        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                var message = await ReadErrorAsync(response, cancellationToken).ConfigureAwait(false);
                throw new ReaderApiException(
                    "reader_remote_admin_failed",
                    message,
                    (int)response.StatusCode);
            }
            return await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
                .ConfigureAwait(false)
                ?? throw new ReaderServiceUnavailableException(
                    "The local Reader service returned an empty remote-access response.");
        }
    }

    private static async Task<string> ReadErrorAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            using var payload = await JsonDocument.ParseAsync(
                await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false),
                cancellationToken: cancellationToken).ConfigureAwait(false);
            return payload.RootElement.GetProperty("error").GetProperty("message").GetString()
                ?? "Remote access operation failed.";
        }
        catch (Exception exception) when (
            exception is JsonException or KeyNotFoundException or InvalidOperationException)
        {
            return $"Remote access operation returned HTTP {(int)response.StatusCode}.";
        }
    }
}
