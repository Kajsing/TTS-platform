using System.Diagnostics;
using System.Net.WebSockets;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public enum ReaderPlaybackState
{
    Stopped,
    Playing,
    Paused,
    Completed,
    Faulted,
}

public sealed record PcmAudioFormat(int SampleRateHz, int Channels, int BitsPerSample = 16);

public interface IAudioOutput : IAsyncDisposable
{
    Task PlayAsync(
        ReadOnlyMemory<byte> pcmBytes,
        PcmAudioFormat format,
        CancellationToken cancellationToken = default);
    Task DrainAsync(CancellationToken cancellationToken = default);
    Task StopAsync(CancellationToken cancellationToken = default);
}

public sealed record PlaybackStateChanged(
    ReaderPlaybackState State,
    string? DocumentId,
    ReaderCursor? Cursor,
    string? Message = null);

public sealed record PlaybackHighlight(
    string DocumentId,
    IReadOnlyList<ReaderSourceSpan> SourceSpans,
    ReaderCursor CursorStart,
    ReaderCursor CursorEnd);

public sealed class ReaderPlaybackCoordinator : IAsyncDisposable
{
    private static readonly TimeSpan PositionSaveInterval = TimeSpan.FromSeconds(1);
    private readonly IReaderServiceClient _serviceClient;
    private readonly IReaderStreamClient _streamClient;
    private readonly IAudioOutput _audioOutput;
    private readonly SemaphoreSlim _transitionLock = new(1, 1);
    private CancellationTokenSource? _runCancellation;
    private Task? _runTask;
    private IReaderStreamSession? _activeSession;
    private ReaderDocument? _document;
    private ReaderCursor? _lastFullyPlayedCursor;
    private int? _positionRowVersion;
    private bool _positionCompleted;
    private string? _voice;
    private ReaderPlaybackState _desiredState = ReaderPlaybackState.Stopped;

    public ReaderPlaybackCoordinator(
        IReaderServiceClient serviceClient,
        IReaderStreamClient streamClient,
        IAudioOutput audioOutput)
    {
        _serviceClient = serviceClient;
        _streamClient = streamClient;
        _audioOutput = audioOutput;
    }

    public event EventHandler<PlaybackStateChanged>? StateChanged;
    public event EventHandler<PlaybackHighlight>? HighlightChanged;
    public event EventHandler<ReaderStreamWarning>? RuleWarning;

    public ReaderPlaybackState State { get; private set; } = ReaderPlaybackState.Stopped;
    public ReaderCursor? LastFullyPlayedCursor => _lastFullyPlayedCursor;
    public bool IsActive => State == ReaderPlaybackState.Playing;

    public async Task PlayAsync(
        ReaderDocument document,
        string? voice = null,
        ReaderCursor? startCursor = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(document);
        await _transitionLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_runTask is { IsCompleted: false })
            {
                return;
            }

            _document = document;
            _voice = voice;
            if (startCursor is not null)
            {
                ValidateCursorDocument(startCursor, document.Id);
                _lastFullyPlayedCursor = startCursor;
                _positionRowVersion = (await _serviceClient.GetPositionAsync(
                    document.Id,
                    cancellationToken).ConfigureAwait(false))?.RowVersion ?? 0;
                _positionCompleted = false;
            }
            else if (_lastFullyPlayedCursor is null ||
                !string.Equals(_lastFullyPlayedCursor.DocumentId, document.Id, StringComparison.Ordinal) ||
                _lastFullyPlayedCursor.ContentRevision != document.ContentRevision)
            {
                var position = await _serviceClient.GetPositionAsync(document.Id, cancellationToken)
                    .ConfigureAwait(false);
                _lastFullyPlayedCursor = position?.Cursor ?? await FirstCursorAsync(document, cancellationToken)
                    .ConfigureAwait(false);
                _positionRowVersion = position?.RowVersion ?? 0;
                _positionCompleted = position?.Completed ?? false;
            }

            _desiredState = ReaderPlaybackState.Playing;
            _runCancellation = new CancellationTokenSource();
            SetState(ReaderPlaybackState.Playing);
            _runTask = RunAsync(_runCancellation.Token);
        }
        finally
        {
            _transitionLock.Release();
        }
    }

    public Task PauseAsync(CancellationToken cancellationToken = default) =>
        InterruptAsync(ReaderPlaybackState.Paused, cancellationToken);

    public Task StopAsync(CancellationToken cancellationToken = default) =>
        InterruptAsync(ReaderPlaybackState.Stopped, cancellationToken);

    public async Task SeekAsync(
        ReaderDocument document,
        ReaderCursor cursor,
        string? voice = null,
        CancellationToken cancellationToken = default)
    {
        ValidateCursorDocument(cursor, document.Id);
        await StopAsync(cancellationToken).ConfigureAwait(false);
        await PlayAsync(document, voice, cursor, cancellationToken).ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync().ConfigureAwait(false);
        await _audioOutput.DisposeAsync().ConfigureAwait(false);
        _runCancellation?.Dispose();
        _transitionLock.Dispose();
    }

    private async Task RunAsync(CancellationToken cancellationToken)
    {
        var saveTimer = Stopwatch.StartNew();
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var document = _document ?? throw new InvalidOperationException("Playback has no document.");
                var cursor = _lastFullyPlayedCursor ?? throw new InvalidOperationException("Playback has no cursor.");
                await using var session = await _streamClient.OpenAsync(
                    new ReaderStreamStartRequest(
                        document.Id,
                        cursor,
                        Voice: _voice,
                        LanguageHint: document.LanguageHint),
                    cancellationToken).ConfigureAwait(false);
                _activeSession = session;
                var continueAt = cursor;
                var shouldContinue = false;
                var completed = false;
                PcmAudioFormat? audioFormat = null;

                await foreach (var streamEvent in session.ReadEventsAsync(cancellationToken).ConfigureAwait(false))
                {
                    switch (streamEvent)
                    {
                        case ReaderStreamStarted started:
                            ValidateCursorDocument(started.Cursor, document.Id);
                            audioFormat = new PcmAudioFormat(
                                started.SampleRateHz,
                                started.Channels);
                            break;
                        case ReaderAudioPacket packet:
                            var packetFormat = audioFormat
                                ?? throw new ReaderStreamProtocolException(
                                    "Reader PCM arrived before its audio format.");
                            HighlightChanged?.Invoke(
                                this,
                                new PlaybackHighlight(
                                    document.Id,
                                    packet.SourceSpans,
                                    packet.CursorStart,
                                    packet.CursorEnd));
                            await _audioOutput.PlayAsync(
                                packet.PcmBytes,
                                packetFormat,
                                cancellationToken).ConfigureAwait(false);
                            if (CursorAdvanced(packet.CursorStart, packet.CursorEnd))
                            {
                                await _audioOutput.DrainAsync(cancellationToken).ConfigureAwait(false);
                                cancellationToken.ThrowIfCancellationRequested();
                                _lastFullyPlayedCursor = packet.CursorEnd;
                                if (saveTimer.Elapsed >= PositionSaveInterval)
                                {
                                    await PersistPositionAsync(completed: false, cancellationToken)
                                        .ConfigureAwait(false);
                                    saveTimer.Restart();
                                }
                            }
                            break;
                        case ReaderStreamDone done:
                            continueAt = done.Cursor;
                            shouldContinue = done.NextWindowAvailable;
                            completed = done.DocumentComplete;
                            break;
                        case ReaderStreamCancelled:
                            shouldContinue = false;
                            break;
                        case ReaderStreamWarning warning:
                            RuleWarning?.Invoke(this, warning);
                            break;
                        case ReaderStreamError error:
                            throw new ReaderStreamProtocolException(
                                $"{error.ErrorType}: {error.Message}");
                    }
                }

                await session.ReleaseAsync(cancellationToken).ConfigureAwait(false);
                _activeSession = null;
                if (cancellationToken.IsCancellationRequested)
                {
                    break;
                }
                if (completed)
                {
                    _lastFullyPlayedCursor = continueAt;
                    _positionCompleted = true;
                    await PersistPositionAsync(completed: true, cancellationToken).ConfigureAwait(false);
                    _desiredState = ReaderPlaybackState.Completed;
                    SetState(ReaderPlaybackState.Completed);
                    return;
                }
                if (!shouldContinue)
                {
                    break;
                }

                _lastFullyPlayedCursor = continueAt;
                await PersistPositionAsync(completed: false, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Pause and stop own the resulting state and durable cursor flush.
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderStreamProtocolException or
                WebSocketException)
        {
            try
            {
                await _audioOutput.StopAsync(CancellationToken.None).ConfigureAwait(false);
            }
            catch (Exception stopException) when (
                stopException is InvalidOperationException or ObjectDisposedException)
            {
                // Preserve the original playback failure as the actionable state.
            }
            _desiredState = ReaderPlaybackState.Faulted;
            SetState(ReaderPlaybackState.Faulted, exception.Message);
        }
        finally
        {
            _activeSession = null;
            if (_desiredState == ReaderPlaybackState.Playing)
            {
                _desiredState = ReaderPlaybackState.Stopped;
                SetState(ReaderPlaybackState.Stopped);
            }
        }
    }

    private async Task InterruptAsync(
        ReaderPlaybackState requestedState,
        CancellationToken cancellationToken)
    {
        Task? runTask;
        IReaderStreamSession? session;
        await _transitionLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_runTask is null || _runTask.IsCompleted)
            {
                _desiredState = requestedState;
                SetState(requestedState);
                if (_lastFullyPlayedCursor is not null)
                {
                    await PersistPositionSafelyAsync(
                        completed: _positionCompleted,
                        cancellationToken).ConfigureAwait(false);
                }
                return;
            }

            _desiredState = requestedState;
            runTask = _runTask;
            session = _activeSession;
            _runCancellation?.Cancel();
            if (session is not null)
            {
                try
                {
                    await session.CancelAsync(cancellationToken).ConfigureAwait(false);
                }
                catch (Exception exception) when (
                    exception is WebSocketException or ObjectDisposedException)
                {
                    // The server/session already completed while the transition began.
                }
            }
            await _audioOutput.StopAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _transitionLock.Release();
        }

        try
        {
            await runTask.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // The cancellation is the requested transition.
        }
        await PersistPositionSafelyAsync(
            completed: _positionCompleted,
            cancellationToken).ConfigureAwait(false);
        SetState(requestedState);
    }

    private async Task<ReaderCursor> FirstCursorAsync(
        ReaderDocument document,
        CancellationToken cancellationToken)
    {
        var page = await _serviceClient.GetBlocksAsync(
            document.Id,
            afterOrdinal: -1,
            limit: 1,
            cancellationToken).ConfigureAwait(false);
        var block = page.Blocks.FirstOrDefault()
            ?? throw new ReaderStreamProtocolException("The selected document has no readable blocks.");
        return new ReaderCursor(document.Id, block.Id, block.Ordinal, 0, document.ContentRevision);
    }

    private async Task PersistPositionAsync(bool completed, CancellationToken cancellationToken)
    {
        var document = _document;
        var cursor = _lastFullyPlayedCursor;
        if (document is null || cursor is null)
        {
            return;
        }

        var saved = await _serviceClient.SavePositionAsync(
            document.Id,
            new SavePositionRequest(
                cursor,
                PipelineVersion: 1,
                RulesVersion: 1,
                Completed: completed,
                ExpectedRowVersion: _positionRowVersion ?? 0),
            cancellationToken).ConfigureAwait(false);
        _positionRowVersion = saved.RowVersion;
        _positionCompleted = completed;
    }

    private async Task PersistPositionSafelyAsync(
        bool completed,
        CancellationToken cancellationToken)
    {
        try
        {
            await PersistPositionAsync(completed, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception exception) when (
            exception is ReaderApiException or ReaderServiceUnavailableException)
        {
            SetState(_desiredState, $"Playback position was not saved: {exception.Message}");
        }
    }

    private void SetState(ReaderPlaybackState state, string? message = null)
    {
        State = state;
        StateChanged?.Invoke(
            this,
            new PlaybackStateChanged(state, _document?.Id, _lastFullyPlayedCursor, message));
    }

    private static void ValidateCursorDocument(ReaderCursor cursor, string documentId)
    {
        if (!string.Equals(cursor.DocumentId, documentId, StringComparison.Ordinal))
        {
            throw new ArgumentException("The playback cursor belongs to another document.", nameof(cursor));
        }
    }

    private static bool CursorAdvanced(ReaderCursor start, ReaderCursor end) =>
        start.BlockOrdinal != end.BlockOrdinal || start.CharacterOffset != end.CharacterOffset;

}
