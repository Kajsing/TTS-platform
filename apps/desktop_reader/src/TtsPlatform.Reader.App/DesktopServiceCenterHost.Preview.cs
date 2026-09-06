using System.Net.Http;
using System.Runtime.InteropServices;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

internal sealed partial class DesktopServiceCenterHost
{
    private CancellationTokenSource? _previewCancellation;
    private string _previewMessage = "";
    private VoicePreviewRunner? _isolatedPreview;

    private async Task PreviewVoiceAsync(string voiceId)
    {
        if (_disposed || _openingReader || _exiting || _operationPending || _voices is not { IsBusy: false }) return;
        var reader = Reader;
        if (reader?.TryBeginVoicePreview() is string reason)
        {
            DashboardWindow?.ShowVoicePreview(reason, false);
            return;
        }
        _operationPending = true;
        _previewCancellation = CancellationTokenSource.CreateLinkedTokenSource(_monitorLifetime.Token);
        _previewMessage = "Preparing voice preview…";
        DashboardWindow?.ShowVoicePreview(_previewMessage, true);
        RenderDashboard();
        var gate = false;
        HttpClient? http = null;
        try
        {
            await _monitorGate.WaitAsync(_previewCancellation.Token);
            gate = true;
            VoicePreviewRunner runner;
            if (_isolatedSmoke)
                runner = _isolatedPreview ?? throw new VoiceLibraryException("No isolated preview fixture configured.");
            else
            {
                await EnsureCoordinatorAsync();
                http = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false })
                { Timeout = TimeSpan.FromSeconds(95) };
                var client = new ReaderServiceClient(http, _localEndpoint, new FileTokenProvider(_tokenPath!));
                runner = new VoicePreviewRunner(client, () => new VoicePreviewAudio());
            }
            await runner.RunAsync(voiceId, message =>
            {
                _previewMessage = message;
                DashboardWindow?.ShowVoicePreview(message, true, _previewCancellation.IsCancellationRequested);
            }, _previewCancellation.Token);
            _previewMessage = "Voice preview finished. Reader position and voice preference are unchanged.";
        }
        catch (OperationCanceledException)
        {
            _previewMessage = "Preview audio stopped or timed out. A native synthesis already running may finish before the service becomes free.";
        }
        catch (Exception error) when (LocalServiceCoordinator.IsExpected(error) || error is VoiceLibraryException or COMException)
        {
            _previewMessage = error is VoiceLibraryException ? error.Message :
                "Preview was unavailable. Check local service readiness, activity, installed voice compatibility and the audio device. Nothing was restarted.";
        }
        finally
        {
            http?.Dispose();
            if (gate) _monitorGate.Release();
            reader?.EndLocalServiceOperation();
            _previewCancellation.Dispose();
            _previewCancellation = null;
            _operationPending = false;
            if (!_disposed)
            {
                DashboardWindow?.ShowVoicePreview(_previewMessage, false);
                RenderDashboard();
                ScheduleNextCheck();
            }
        }
    }

    private void CancelVoicePreview()
    {
        if (_previewCancellation is null) return;
        _previewCancellation.Cancel();
        DashboardWindow?.ShowVoicePreview("Stopping voice preview…", true, true);
    }

    internal void ConfigureIsolatedVoicePreview(VoicePreviewRunner runner)
    {
        if (!_isolatedSmoke) throw new InvalidOperationException("Preview fixture requires isolated smoke mode.");
        _isolatedPreview = runner;
    }
}
