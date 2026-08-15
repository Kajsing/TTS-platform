using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum ConnectionState
{
    NotChecked,
    Checking,
    Ready,
    ServiceUnavailable,
    TokenMissing,
    TokenInvalid,
    BackendDegraded,
    ReaderDisabled,
    ReaderDegraded,
    UnsupportedContract,
    RateLimited,
    Error,
}

public enum SuggestedAction
{
    None,
    StartService,
    ChooseTokenFile,
    CheckVoiceModels,
    EnableReader,
    Retry,
}

public sealed record OnboardingResult(
    ConnectionState State,
    string Message,
    SuggestedAction Action,
    HealthResponse? Health = null,
    ReaderCapabilities? Capabilities = null,
    VoicePage? Voices = null)
{
    public bool IsReady => State == ConnectionState.Ready;
}

public sealed class OnboardingCoordinator(IReaderServiceClient client)
{
    public async Task<OnboardingResult> CheckAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var health = await client.GetHealthAsync(cancellationToken).ConfigureAwait(false);
            if (!health.Reader.Enabled)
            {
                return new OnboardingResult(
                    ConnectionState.ReaderDisabled,
                    "Reader storage is disabled in the local service configuration.",
                    SuggestedAction.EnableReader,
                    health);
            }

            var capabilities = await client.GetCapabilitiesAsync(cancellationToken).ConfigureAwait(false);
            if (capabilities.ContractVersion != 1)
            {
                return new OnboardingResult(
                    ConnectionState.UnsupportedContract,
                    $"This app supports Reader contract version 1, but the service reports {capabilities.ContractVersion}.",
                    SuggestedAction.Retry,
                    health,
                    capabilities);
            }

            if (!capabilities.Enabled)
            {
                return new OnboardingResult(
                    ConnectionState.ReaderDisabled,
                    "Reader storage is disabled in the local service configuration.",
                    SuggestedAction.EnableReader,
                    health,
                    capabilities);
            }

            if (!capabilities.Database.Ready)
            {
                return new OnboardingResult(
                    ConnectionState.ReaderDegraded,
                    "Reader storage is unavailable. Review the service log, then retry.",
                    SuggestedAction.Retry,
                    health,
                    capabilities);
            }

            var voices = await client.GetVoicesAsync(cancellationToken).ConfigureAwait(false);
            var backendReady = health.Checks.TryGetValue("backend_ready", out var ready) && ready;
            var defaultVoiceReady = health.Checks.TryGetValue("default_voice_loaded", out var loaded) && loaded;
            if (!backendReady || !defaultVoiceReady || voices.Voices.Count == 0)
            {
                return new OnboardingResult(
                    ConnectionState.BackendDegraded,
                    "Reader storage is ready, but speech is not. Check the configured voice models.",
                    SuggestedAction.CheckVoiceModels,
                    health,
                    capabilities,
                    voices);
            }

            return new OnboardingResult(
                ConnectionState.Ready,
                $"Connected. {voices.Voices.Count} voice(s) available.",
                SuggestedAction.None,
                health,
                capabilities,
                voices);
        }
        catch (ReaderTokenUnavailableException exception)
        {
            return new OnboardingResult(
                ConnectionState.TokenMissing,
                exception.Message,
                SuggestedAction.ChooseTokenFile);
        }
        catch (ReaderServiceUnavailableException exception)
        {
            return new OnboardingResult(
                ConnectionState.ServiceUnavailable,
                exception.Message,
                SuggestedAction.StartService);
        }
        catch (ReaderApiException exception) when (exception.StatusCode is 401 or 403)
        {
            return new OnboardingResult(
                ConnectionState.TokenInvalid,
                "The token was rejected. Choose the current service token file and retry.",
                SuggestedAction.ChooseTokenFile);
        }
        catch (ReaderApiException exception) when (
            exception.StatusCode == 429 ||
            string.Equals(exception.ErrorType, "rate_limited", StringComparison.Ordinal))
        {
            return new OnboardingResult(
                ConnectionState.RateLimited,
                "The local service is busy. Wait about a minute and retry.",
                SuggestedAction.Retry);
        }
        catch (ReaderApiException exception)
        {
            return new OnboardingResult(
                ConnectionState.Error,
                $"Reader check failed: {exception.Message}",
                SuggestedAction.Retry);
        }
    }
}
