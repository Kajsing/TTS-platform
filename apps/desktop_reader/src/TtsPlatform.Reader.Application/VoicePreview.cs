using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public interface IVoicePreviewAudio : IAsyncDisposable
{
    TimeSpan Load(ReadOnlyMemory<byte> wave);
    Task PlayAsync(CancellationToken cancellationToken);
    Task StopAsync();
}

// No articles, settings or service lifecycle commands. Rendering and audible
// playback each require their own current, globally idle service reservation.
public sealed class VoicePreviewRunner(ILocalVoicePreviewClient client, Func<IVoicePreviewAudio> audioFactory,
    TimeProvider? timeProvider = null)
{
    private readonly TimeProvider _time = timeProvider ?? TimeProvider.System;
    private readonly SemaphoreSlim _gate = new(1, 1);

    public async Task RunAsync(string voiceId, Action<string> progress, CancellationToken cancellationToken)
    {
        if (!await _gate.WaitAsync(0, cancellationToken)) throw new VoiceLibraryException("A voice preview is already running.");
        string? reservation = null;
        IVoicePreviewAudio? audio = null;
        try
        {
            progress("Checking that the local service is idle…");
            using var check = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            check.CancelAfter(TimeSpan.FromSeconds(5));
            var status = await client.GetLocalStatusAsync(check.Token);
            var dashboard = ServiceDashboard.FromStatus(status);
            if (!dashboard.CanRequestMaintenance || !status.BackendReady)
                throw new VoiceLibraryException("Preview needs an idle, ready local service. Existing reading and exports were left untouched.");

            var renderLease = await ReserveAsync(status.InstanceId, cancellationToken);
            reservation = renderLease.Reservation;
            ValidateLease(renderLease);
            progress("Preparing a short fixed voice sample…");
            using var render = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            render.CancelAfter(TimeSpan.FromSeconds(90));
            var wave = await client.RenderVoicePreviewAsync(reservation, voiceId, render.Token);
            // The render endpoint consumed/released its lease only after the
            // native worker exited. Never reuse that ticket for audible playback.
            reservation = null;
            cancellationToken.ThrowIfCancellationRequested();
            audio = audioFactory();
            var duration = audio.Load(wave);
            if (duration <= TimeSpan.Zero || duration > TimeSpan.FromSeconds(10))
                throw new VoiceLibraryException("The voice returned an invalid or overlong sample; no preview was played.");

            var started = _time.GetTimestamp();
            var playbackLease = await ReserveAsync(status.InstanceId, cancellationToken);
            reservation = playbackLease.Reservation;
            ValidateLease(playbackLease);
            var remaining = TimeSpan.FromSeconds(playbackLease.ExpiresInSeconds - 1) - _time.GetElapsedTime(started);
            if (remaining < duration + TimeSpan.FromMilliseconds(500))
                throw new VoiceLibraryException("The preview reservation expired before playback. Try again when the service responds promptly.");
            using var deadline = new CancellationTokenSource(remaining, _time);
            using var playing = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, deadline.Token);
            progress("Playing voice preview · articles and Reader preference are unchanged.");
            await audio.PlayAsync(playing.Token);
        }
        finally
        {
            // Audio must be stopped/disposed before permitting other service work.
            try
            {
                if (audio is not null)
                {
                    try { await audio.StopAsync(); }
                    finally { await audio.DisposeAsync(); }
                }
            }
            finally
            {
                try
                {
                    if (!string.IsNullOrEmpty(reservation))
                    {
                        using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                        try { await client.ReleaseMaintenanceAsync(reservation, cleanup.Token); }
                        catch (Exception error) when (LocalServiceCoordinator.IsExpected(error)) { }
                    }
                }
                finally { _gate.Release(); }
            }
        }
    }

    private async Task<ServiceMaintenanceReservation> ReserveAsync(string instance, CancellationToken token)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(5));
        return await client.ReserveMaintenanceAsync(instance, timeout.Token);
    }

    private static void ValidateLease(ServiceMaintenanceReservation lease)
    {
        if (string.IsNullOrWhiteSpace(lease.Reservation) || lease.Reservation.Length > 128 || lease.ExpiresInSeconds is < 1 or > 15)
            throw new VoiceLibraryException("The service returned an unsupported preview reservation.");
    }
}
