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

public sealed record AudioPlaybackCheckpoint(long Generation, long BytePosition);

public sealed record AudioOutputSnapshot(
    double BufferedDurationMs,
    long SuspectedUnderrunCount,
    bool IsPlaying);

public interface IAudioOutputDiagnostics
{
    AudioOutputSnapshot Snapshot { get; }
}

public sealed record PlaybackPerformanceEvent(
    string Name,
    string? DocumentId = null,
    int? WindowIndex = null,
    int? ChunkIndex = null,
    int? BlockOrdinal = null,
    int? CharacterOffset = null,
    long? ElapsedMs = null,
    long? GapMs = null,
    long? OperationMs = null,
    int? PcmBytes = null,
    int? AudioDurationMs = null,
    double? BufferBeforeMs = null,
    double? BufferAfterMs = null,
    long? SuspectedUnderruns = null,
    int? SampleRateHz = null,
    int? Channels = null,
    string? State = null,
    string? ErrorCategory = null);

public interface IPlaybackPerformanceSink
{
    void Record(PlaybackPerformanceEvent performanceEvent);
}

public interface IAudioOutput : IAsyncDisposable
{
    AudioPlaybackCheckpoint SubmittedCheckpoint { get; }
    AudioPlaybackCheckpoint PlayedCheckpoint { get; }
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
    private readonly IPlaybackPerformanceSink? _performanceSink;
    private readonly SemaphoreSlim _transitionLock = new(1, 1);
    private readonly object _audioCursorSync = new();
    private readonly Queue<(AudioPlaybackCheckpoint Checkpoint, ReaderCursor Cursor)>
        _pendingAudioCursors = new();
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
        IAudioOutput audioOutput,
        IPlaybackPerformanceSink? performanceSink = null)
    {
        _serviceClient = serviceClient;
        _streamClient = streamClient;
        _audioOutput = audioOutput;
        _performanceSink = performanceSink;
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
            ClearPendingAudioCursors();
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
            if (startCursor is null && _positionCompleted)
            {
                _lastFullyPlayedCursor = await FirstCursorAsync(document, cancellationToken)
                    .ConfigureAwait(false);
                _positionCompleted = false;
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
        var runTimer = Stopwatch.StartNew();
        var windowIndex = 0;
        long? previousPacketTimestamp = null;
        RecordPerformance(new PlaybackPerformanceEvent(
            "playback_run_start",
            DocumentId: _document?.Id));
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var document = _document ?? throw new InvalidOperationException("Playback has no document.");
                var cursor = _lastFullyPlayedCursor ?? throw new InvalidOperationException("Playback has no cursor.");
                var streamOpenTimer = Stopwatch.StartNew();
                await using var session = await _streamClient.OpenAsync(
                    new ReaderStreamStartRequest(
                        document.Id,
                        cursor,
                        Voice: _voice,
                        LanguageHint: document.LanguageHint),
                    cancellationToken).ConfigureAwait(false);
                RecordPerformance(new PlaybackPerformanceEvent(
                    "stream_opened",
                    DocumentId: document.Id,
                    WindowIndex: windowIndex,
                    BlockOrdinal: cursor.BlockOrdinal,
                    CharacterOffset: cursor.CharacterOffset,
                    ElapsedMs: runTimer.ElapsedMilliseconds,
                    OperationMs: streamOpenTimer.ElapsedMilliseconds));
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
                            RecordPerformance(new PlaybackPerformanceEvent(
                                "stream_started",
                                DocumentId: document.Id,
                                WindowIndex: windowIndex,
                                BlockOrdinal: started.Cursor.BlockOrdinal,
                                CharacterOffset: started.Cursor.CharacterOffset,
                                ElapsedMs: runTimer.ElapsedMilliseconds,
                                SampleRateHz: started.SampleRateHz,
                                Channels: started.Channels));
                            break;
                        case ReaderAudioPacket packet:
                            var packetTimestamp = Stopwatch.GetTimestamp();
                            var packetGapMs = previousPacketTimestamp is long previous
                                ? ElapsedMilliseconds(previous, packetTimestamp)
                                : (long?)null;
                            previousPacketTimestamp = packetTimestamp;
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
                            var before = AudioSnapshot();
                            var submitTimer = Stopwatch.StartNew();
                            await _audioOutput.PlayAsync(
                                packet.PcmBytes,
                                packetFormat,
                                cancellationToken).ConfigureAwait(false);
                            var after = AudioSnapshot();
                            RecordPerformance(new PlaybackPerformanceEvent(
                                "audio_packet",
                                DocumentId: document.Id,
                                WindowIndex: windowIndex,
                                ChunkIndex: packet.ChunkIndex,
                                BlockOrdinal: packet.CursorEnd.BlockOrdinal,
                                CharacterOffset: packet.CursorEnd.CharacterOffset,
                                ElapsedMs: runTimer.ElapsedMilliseconds,
                                GapMs: packetGapMs,
                                OperationMs: submitTimer.ElapsedMilliseconds,
                                PcmBytes: packet.PcmBytes.Length,
                                AudioDurationMs: packet.DurationMs,
                                BufferBeforeMs: before?.BufferedDurationMs,
                                BufferAfterMs: after?.BufferedDurationMs,
                                SuspectedUnderruns: after?.SuspectedUnderrunCount,
                                SampleRateHz: packetFormat.SampleRateHz,
                                Channels: packetFormat.Channels));
                            cancellationToken.ThrowIfCancellationRequested();
                            if (CursorAdvanced(packet.CursorStart, packet.CursorEnd))
                            {
                                var checkpoint = _audioOutput.SubmittedCheckpoint;
                                if (checkpoint.BytePosition > 0)
                                {
                                    EnqueueAudioCursor(checkpoint, packet.CursorEnd);
                                }
                            }
                            if (AcknowledgePlayedAudio() &&
                                saveTimer.Elapsed >= PositionSaveInterval)
                            {
                                await PersistPositionAsync(completed: false, cancellationToken)
                                    .ConfigureAwait(false);
                                saveTimer.Restart();
                            }
                            break;
                        case ReaderStreamDone done:
                            var beforeDrain = AudioSnapshot();
                            var drainTimer = Stopwatch.StartNew();
                            await _audioOutput.DrainAsync(cancellationToken).ConfigureAwait(false);
                            cancellationToken.ThrowIfCancellationRequested();
                            AcknowledgePlayedAudio();
                            var afterDrain = AudioSnapshot();
                            RecordPerformance(new PlaybackPerformanceEvent(
                                "stream_done",
                                DocumentId: document.Id,
                                WindowIndex: windowIndex,
                                BlockOrdinal: done.Cursor.BlockOrdinal,
                                CharacterOffset: done.Cursor.CharacterOffset,
                                ElapsedMs: runTimer.ElapsedMilliseconds,
                                OperationMs: drainTimer.ElapsedMilliseconds,
                                BufferBeforeMs: beforeDrain?.BufferedDurationMs,
                                BufferAfterMs: afterDrain?.BufferedDurationMs,
                                SuspectedUnderruns: afterDrain?.SuspectedUnderrunCount));
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
                windowIndex++;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Pause and stop own the resulting state and durable cursor flush.
            RecordPerformance(new PlaybackPerformanceEvent(
                "playback_run_cancelled",
                DocumentId: _document?.Id,
                ElapsedMs: runTimer.ElapsedMilliseconds));
        }
        catch (Exception exception) when (
            exception is ReaderApiException or
                ReaderServiceUnavailableException or
                ReaderStreamProtocolException or
                WebSocketException)
        {
            RecordPerformance(new PlaybackPerformanceEvent(
                "playback_run_faulted",
                DocumentId: _document?.Id,
                ElapsedMs: runTimer.ElapsedMilliseconds,
                ErrorCategory: exception.GetType().Name));
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
            RecordPerformance(new PlaybackPerformanceEvent(
                "playback_run_end",
                DocumentId: _document?.Id,
                ElapsedMs: runTimer.ElapsedMilliseconds,
                State: State.ToString()));
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
            AcknowledgePlayedAudio();
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
        RecordPerformance(new PlaybackPerformanceEvent(
            "state_change",
            DocumentId: _document?.Id,
            BlockOrdinal: _lastFullyPlayedCursor?.BlockOrdinal,
            CharacterOffset: _lastFullyPlayedCursor?.CharacterOffset,
            State: state.ToString()));
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

    private void EnqueueAudioCursor(
        AudioPlaybackCheckpoint checkpoint,
        ReaderCursor cursor)
    {
        lock (_audioCursorSync)
        {
            _pendingAudioCursors.Enqueue((checkpoint, cursor));
        }
    }

    private bool AcknowledgePlayedAudio()
    {
        var played = _audioOutput.PlayedCheckpoint;
        var advanced = false;
        lock (_audioCursorSync)
        {
            while (_pendingAudioCursors.TryPeek(out var pending))
            {
                if (pending.Checkpoint.Generation < played.Generation)
                {
                    _pendingAudioCursors.Dequeue();
                    continue;
                }
                if (pending.Checkpoint.Generation != played.Generation ||
                    pending.Checkpoint.BytePosition > played.BytePosition)
                {
                    break;
                }
                _pendingAudioCursors.Dequeue();
                _lastFullyPlayedCursor = pending.Cursor;
                advanced = true;
            }
        }
        return advanced;
    }

    private void ClearPendingAudioCursors()
    {
        lock (_audioCursorSync)
        {
            _pendingAudioCursors.Clear();
        }
    }

    private AudioOutputSnapshot? AudioSnapshot() =>
        (_audioOutput as IAudioOutputDiagnostics)?.Snapshot;

    private void RecordPerformance(PlaybackPerformanceEvent performanceEvent)
    {
        try
        {
            _performanceSink?.Record(performanceEvent);
        }
        catch (Exception)
        {
            // Diagnostics must never interrupt playback.
        }
    }

    private static long ElapsedMilliseconds(long startTimestamp, long endTimestamp) =>
        Math.Max(0, (long)Math.Round(
            Stopwatch.GetElapsedTime(startTimestamp, endTimestamp).TotalMilliseconds));

}
