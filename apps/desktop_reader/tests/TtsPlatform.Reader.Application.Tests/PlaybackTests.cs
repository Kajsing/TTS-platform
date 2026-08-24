using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using System.Text.Json;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class PlaybackTests
{
    [Fact]
    public async Task Pause_persists_only_fully_played_audio_and_resume_starts_there()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true),
            request => CompletedSession(request));
        var audio = new FakeAudioOutput(blockCall: 2);
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document());
        await audio.WaitForCallAsync(2);
        await playback.PauseAsync();

        Assert.Equal(ReaderPlaybackState.Paused, playback.State);
        Assert.Equal(3, playback.LastFullyPlayedCursor?.CharacterOffset);
        Assert.Equal(3, service.SavedPositions.Last().Cursor.CharacterOffset);
        Assert.Equal(1, streams.Sessions[0].CancelCalls);
        Assert.Equal(1, audio.MaxConcurrentCalls);

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => streams.Requests.Count == 2);

        Assert.Equal(3, streams.Requests[1].Cursor.CharacterOffset);
    }

    [Fact]
    public async Task Playback_continues_next_window_and_marks_document_complete()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => WindowDoneSession(request),
            request => CompletedSession(request));
        var audio = new FakeAudioOutput();
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document(), voice: "voice-two");
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);

        Assert.Equal(2, streams.Requests.Count);
        Assert.All(streams.Requests, request => Assert.Equal("voice-two", request.Voice));
        Assert.Equal(1, streams.Requests[1].Cursor.BlockOrdinal);
        Assert.True(service.SavedPositions.Last().Completed);
    }

    [Fact]
    public async Task Stop_is_idempotent_and_never_advances_an_interrupted_packet()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(request => SessionWithPackets(request, includeSecondPacket: false));
        var audio = new FakeAudioOutput(blockCall: 1);
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document());
        await audio.WaitForCallAsync(1);
        await playback.StopAsync();
        await playback.StopAsync();

        Assert.Equal(ReaderPlaybackState.Stopped, playback.State);
        Assert.Equal(0, playback.LastFullyPlayedCursor?.CharacterOffset);
        Assert.All(service.SavedPositions, item => Assert.Equal(0, item.Cursor.CharacterOffset));
    }

    [Fact]
    public async Task Stop_resets_the_next_normal_play_to_the_document_beginning()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true),
            request => CompletedSession(request));
        var audio = new FakeAudioOutput(blockCall: 2);
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document());
        await audio.WaitForCallAsync(2);
        await playback.StopAsync();

        Assert.Equal(ReaderPlaybackState.Stopped, playback.State);
        Assert.Equal(0, playback.LastFullyPlayedCursor?.CharacterOffset);
        Assert.Equal(0, service.SavedPositions.Last().Cursor.CharacterOffset);

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => streams.Requests.Count == 2);

        Assert.Equal(0, streams.Requests[1].Cursor.CharacterOffset);
    }

    [Fact]
    public async Task Caret_cursor_overrides_the_beginning_after_stop()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true),
            request => CompletedSession(request));
        var audio = new FakeAudioOutput(blockCall: 2);
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);
        var caretCursor = new ReaderCursor("doc", "block-0", 0, 4, 1);

        await playback.PlayAsync(Document());
        await audio.WaitForCallAsync(2);
        await playback.StopAsync();
        await playback.PlayAsync(Document(), startCursor: caretCursor);
        await WaitUntilAsync(() => streams.Requests.Count == 2);

        Assert.Equal(caretCursor, streams.Requests[1].Cursor);
    }

    [Fact]
    public async Task Disposing_preserves_the_last_fully_played_position()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true));
        var audio = new FakeAudioOutput(blockCall: 2);
        var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document());
        await audio.WaitForCallAsync(2);
        await playback.DisposeAsync();

        Assert.Equal(3, service.SavedPositions.Last().Cursor.CharacterOffset);
    }

    [Fact]
    public async Task Playback_buffers_across_cursor_boundaries_and_drains_once_at_stream_end()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true));
        var audio = new FakeAudioOutput();
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);

        Assert.Equal(2, audio.CallCount);
        Assert.Equal(1, audio.DrainCount);
        Assert.Equal(6, playback.LastFullyPlayedCursor?.CharacterOffset);
    }

    [Fact]
    public async Task Playback_records_privacy_safe_chunk_and_buffer_timings()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true));
        var audio = new FakeAudioOutput();
        var diagnostics = new FakePerformanceSink();
        await using var playback = new ReaderPlaybackCoordinator(
            service,
            streams,
            audio,
            diagnostics);

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);

        var packets = diagnostics.Events.Where(item => item.Name == "audio_packet_sample").ToArray();
        Assert.Single(packets);
        Assert.Equal(0, packets[0].ChunkIndex);
        Assert.All(packets, item => Assert.Equal("doc", item.DocumentId));
        Assert.All(packets, item => Assert.Equal(4, item.PcmBytes));
        Assert.All(packets, item => Assert.NotNull(item.BufferAfterMs));
        var summary = Assert.Single(diagnostics.Events, item => item.Name == "stream_done");
        Assert.Equal(2, summary.PacketCount);
        Assert.Equal(8, summary.TotalPcmBytes);
        Assert.Equal(125, summary.MinBufferMs);
        Assert.Equal(125, summary.MaxBufferMs);
        Assert.True(summary.DocumentComplete);
        var request = Assert.Single(diagnostics.Events, item => item.Name == "playback_requested");
        Assert.Equal("document_start", request.StartMode);
        Assert.False(string.IsNullOrWhiteSpace(request.RunId));
        Assert.All(
            diagnostics.Events.Where(item => item.Name != "playback_interrupt_requested"),
            item => Assert.Equal(request.RunId, item.RunId));
        Assert.DoesNotContain(
            diagnostics.Events,
            item => item.ErrorCategory is not null);
    }

    [Fact]
    public async Task Playback_samples_routine_packets_but_keeps_the_complete_window_summary()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(request => SessionWithPacketCount(request, 60));
        var diagnostics = new FakePerformanceSink();
        await using var playback = new ReaderPlaybackCoordinator(
            service,
            streams,
            new FakeAudioOutput(),
            diagnostics);

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);

        var samples = diagnostics.Events
            .Where(item => item.Name == "audio_packet_sample")
            .ToArray();
        Assert.Equal([0, 49], samples.Select(item => item.ChunkIndex));
        Assert.Equal([1, 50], samples.Select(item => item.PacketCount));
        var summary = Assert.Single(diagnostics.Events, item => item.Name == "stream_done");
        Assert.Equal(60, summary.PacketCount);
        Assert.Equal(240, summary.TotalPcmBytes);
    }

    [Fact]
    public async Task Highlights_follow_played_audio_instead_of_submitted_audio()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(
            request => SessionWithPackets(request, includeSecondPacket: true));
        var audio = new FakeAudioOutput(autoAdvance: false, blockDrain: true);
        var highlights = new ConcurrentQueue<PlaybackHighlight>();
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);
        playback.HighlightChanged += (_, highlight) => highlights.Enqueue(highlight);

        await playback.PlayAsync(Document());
        await audio.WaitForDrainAsync();
        await WaitUntilAsync(() => highlights.Count == 1);

        Assert.Equal(0, highlights.Single().SourceSpans.Single().StartOffset);

        audio.SetPlayedBytes(4);
        await WaitUntilAsync(() => highlights.Count == 2);

        Assert.Equal(3, highlights.Last().SourceSpans.Single().StartOffset);

        audio.ReleaseDrain();
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);
    }

    [Fact]
    public async Task Explicit_start_cursor_overrides_the_saved_resume_position()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(request => CompletedSession(request));
        var audio = new FakeAudioOutput();
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);
        var startCursor = new ReaderCursor("doc", "block-0", 0, 4, 1);

        await playback.PlayAsync(Document(), startCursor: startCursor);
        await WaitUntilAsync(() => streams.Requests.Count == 1);

        Assert.Equal(startCursor, streams.Requests[0].Cursor);
    }

    [Fact]
    public async Task Playback_complete_restarts_from_first_cursor_on_next_play()
    {
        var service = new PlaybackService();
        var streams = new FakeStreamClient(request => CompletedSession(request));
        var audio = new FakeAudioOutput();
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);
        var nearEnd = new ReaderCursor("doc", "block-0", 0, 5, 1);

        await playback.PlayAsync(Document(), startCursor: nearEnd);
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);
        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => streams.Requests.Count == 2);

        Assert.Equal(nearEnd, streams.Requests[0].Cursor);
        Assert.Equal(0, streams.Requests[1].Cursor.CharacterOffset);
    }

    [Fact]
    public async Task Persisted_completed_position_restarts_from_first_cursor()
    {
        var completedCursor = new ReaderCursor("doc", "block-0", 0, 6, 1);
        var service = new PlaybackService
        {
            Position = new ReaderPosition(
                "doc",
                completedCursor,
                null,
                1,
                1,
                DateTimeOffset.UtcNow,
                true,
                7),
        };
        var streams = new FakeStreamClient(request => CompletedSession(request));
        var audio = new FakeAudioOutput();
        await using var playback = new ReaderPlaybackCoordinator(service, streams, audio);

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => streams.Requests.Count == 1);

        Assert.Equal(0, streams.Requests[0].Cursor.CharacterOffset);
    }

    private static FakeStreamSession SessionWithPackets(
        ReaderStreamStartRequest request,
        bool includeSecondPacket)
    {
        var events = new List<ReaderStreamEvent>
        {
            Started(request),
            Packet(request, 0, request.Cursor.CharacterOffset, 3),
        };
        if (includeSecondPacket)
        {
            events.Add(Packet(request, 1, 3, 6));
        }
        events.Add(new ReaderStreamDone("stream", Cursor(request, 6), true, false));
        return new FakeStreamSession(events);
    }

    private static FakeStreamSession WindowDoneSession(ReaderStreamStartRequest request)
    {
        var next = new ReaderCursor(request.DocumentId, "block-1", 1, 0, 1);
        return new FakeStreamSession(
        [
            Started(request),
            new ReaderStreamDone("stream", next, false, true),
        ]);
    }

    private static FakeStreamSession SessionWithPacketCount(
        ReaderStreamStartRequest request,
        int packetCount)
    {
        var events = new List<ReaderStreamEvent> { Started(request) };
        events.AddRange(Enumerable.Range(0, packetCount).Select(
            index => Packet(request, index, 0, 1)));
        events.Add(new ReaderStreamDone("stream", Cursor(request, 1), true, false));
        return new FakeStreamSession(events);
    }

    private static FakeStreamSession CompletedSession(ReaderStreamStartRequest request) => new(
    [
        Started(request),
        new ReaderStreamDone("stream", request.Cursor, true, false),
    ]);

    private static ReaderStreamStarted Started(ReaderStreamStartRequest request) => new(
        "stream",
        request.DocumentId,
        22_050,
        1,
        "pcm16le",
        1,
        1,
        request.Cursor);

    private static ReaderAudioPacket Packet(
        ReaderStreamStartRequest request,
        int index,
        int start,
        int end) => new(
            "stream",
            request.DocumentId,
            index,
            10,
            Cursor(request, start),
            Cursor(request, end),
            [new ReaderSourceSpan("block-0", 0, start, end)],
            "section",
            false,
            new byte[] { 1, 2, 3, 4 });

    private static ReaderCursor Cursor(ReaderStreamStartRequest request, int offset) =>
        new(request.DocumentId, "block-0", 0, offset, 1);

    private static ReaderDocument Document() => new(
        "doc",
        "Document",
        "plain_text",
        null,
        null,
        null,
        "da",
        "inbox",
        DateTimeOffset.Parse("2026-07-27T12:00:00Z"),
        DateTimeOffset.Parse("2026-07-27T12:00:00Z"),
        DateTimeOffset.Parse("2026-07-27T12:00:00Z"),
        null,
        1,
        1,
        1,
        1,
        10,
        JsonDocument.Parse("{}").RootElement.Clone());

    private static async Task WaitUntilAsync(Func<bool> predicate)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while (!predicate())
        {
            await Task.Delay(10, timeout.Token);
        }
    }

    private sealed class PlaybackService : IReaderServiceClient
    {
        public List<SavePositionRequest> SavedPositions { get; } = [];
        public ReaderPosition? Position { get; init; }

        public Task<ReaderPosition?> GetPositionAsync(
            string documentId,
            CancellationToken cancellationToken = default) => Task.FromResult(Position);

        public Task<ReaderPosition> SavePositionAsync(
            string documentId,
            SavePositionRequest request,
            CancellationToken cancellationToken = default)
        {
            SavedPositions.Add(request);
            return Task.FromResult(new ReaderPosition(
                documentId,
                request.Cursor,
                request.VoiceProfileId,
                request.PipelineVersion,
                request.RulesVersion,
                DateTimeOffset.UtcNow,
                request.Completed,
                SavedPositions.Count));
        }

        public Task<BlockPage> GetBlocksAsync(
            string documentId,
            int afterOrdinal = -1,
            int limit = 200,
            CancellationToken cancellationToken = default) => Task.FromResult(new BlockPage(
            [new ReaderBlock("block-0", documentId, "section", 0, "paragraph", "abcdef", 6, "hash", 1, JsonDocument.Parse("{}").RootElement.Clone())],
            null));

        public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderCapabilities> GetCapabilitiesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<VoicePage> GetVoicesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ReaderDocument> CreateDocumentAsync(CreateDocumentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DocumentPage> GetDocumentsAsync(int limit = 50, string? cursor = null, string? query = null, string? state = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> ReplaceContentAsync(string documentId, ReplaceContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> AppendContentAsync(string documentId, AppendContentRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> UndoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<MutationResponse> RedoAsync(string documentId, ExpectedVersionRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<byte[]> SynthesizeAsync(EphemeralSynthesisRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }

    private sealed class FakeStreamClient(params Func<ReaderStreamStartRequest, FakeStreamSession>[] factories)
        : IReaderStreamClient
    {
        private readonly Queue<Func<ReaderStreamStartRequest, FakeStreamSession>> _factories = new(factories);
        public List<ReaderStreamStartRequest> Requests { get; } = [];
        public List<FakeStreamSession> Sessions { get; } = [];

        public Task<IReaderStreamSession> OpenAsync(
            ReaderStreamStartRequest request,
            CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            var factory = _factories.Count > 1 ? _factories.Dequeue() : _factories.Peek();
            var session = factory(request);
            Sessions.Add(session);
            return Task.FromResult<IReaderStreamSession>(session);
        }
    }

    private sealed class FakeStreamSession(IReadOnlyList<ReaderStreamEvent> events) : IReaderStreamSession
    {
        public int CancelCalls { get; private set; }

        public async IAsyncEnumerable<ReaderStreamEvent> ReadEventsAsync(
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            foreach (var streamEvent in events)
            {
                cancellationToken.ThrowIfCancellationRequested();
                yield return streamEvent;
                await Task.Yield();
            }
        }

        public Task CancelAsync(CancellationToken cancellationToken = default)
        {
            CancelCalls++;
            return Task.CompletedTask;
        }

        public Task ReleaseAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FakeAudioOutput(
        int? blockCall = null,
        bool autoAdvance = true,
        bool blockDrain = false) : IAudioOutput, IAudioOutputDiagnostics
    {
        private readonly TaskCompletionSource _stop = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource<int> _calls = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _drainStarted = new(
            TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _drainRelease = new(
            TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly object _sync = new();
        private int _activeCalls;
        private long _generation = 1;
        private long _submittedBytes;
        private long _playedBytes;
        public int CallCount { get; private set; }
        public int DrainCount { get; private set; }
        public int MaxConcurrentCalls { get; private set; }

        public AudioOutputSnapshot Snapshot => new(
            BufferedDurationMs: 125,
            SuspectedUnderrunCount: 0,
            IsPlaying: CallCount > 0);

        public AudioPlaybackCheckpoint SubmittedCheckpoint
        {
            get
            {
                lock (_sync)
                {
                    return new AudioPlaybackCheckpoint(_generation, _submittedBytes);
                }
            }
        }

        public AudioPlaybackCheckpoint PlayedCheckpoint
        {
            get
            {
                lock (_sync)
                {
                    return new AudioPlaybackCheckpoint(_generation, _playedBytes);
                }
            }
        }

        public async Task PlayAsync(
            ReadOnlyMemory<byte> pcmBytes,
            PcmAudioFormat format,
            CancellationToken cancellationToken = default)
        {
            _ = pcmBytes;
            _ = format;
            CallCount++;
            long generation;
            long submittedBytes;
            lock (_sync)
            {
                generation = _generation;
                _submittedBytes += pcmBytes.Length;
                submittedBytes = _submittedBytes;
            }
            _calls.TrySetResult(CallCount);
            _activeCalls++;
            MaxConcurrentCalls = Math.Max(MaxConcurrentCalls, _activeCalls);
            try
            {
                if (blockCall == CallCount)
                {
                    await _stop.Task.WaitAsync(cancellationToken);
                }
                cancellationToken.ThrowIfCancellationRequested();
                if (autoAdvance)
                {
                    lock (_sync)
                    {
                        if (_generation == generation)
                        {
                            _playedBytes = submittedBytes;
                        }
                    }
                }
            }
            finally
            {
                _activeCalls--;
            }
        }

        public async Task WaitForCallAsync(int call)
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            while (CallCount < call)
            {
                await _calls.Task.WaitAsync(timeout.Token);
                if (CallCount < call)
                {
                    await Task.Delay(10, timeout.Token);
                }
            }
        }

        public Task StopAsync(CancellationToken cancellationToken = default)
        {
            _stop.TrySetResult();
            _drainRelease.TrySetResult();
            lock (_sync)
            {
                _generation++;
                _submittedBytes = 0;
                _playedBytes = 0;
            }
            return Task.CompletedTask;
        }

        public async Task DrainAsync(CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            DrainCount++;
            _drainStarted.TrySetResult();
            if (blockDrain)
            {
                await _drainRelease.Task.WaitAsync(cancellationToken);
            }
            lock (_sync)
            {
                _playedBytes = _submittedBytes;
            }
        }

        public async Task WaitForDrainAsync()
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            await _drainStarted.Task.WaitAsync(timeout.Token);
        }

        public void SetPlayedBytes(long bytePosition)
        {
            lock (_sync)
            {
                _playedBytes = Math.Clamp(bytePosition, 0, _submittedBytes);
            }
        }

        public void ReleaseDrain() => _drainRelease.TrySetResult();

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FakePerformanceSink : IPlaybackPerformanceSink
    {
        public List<PlaybackPerformanceEvent> Events { get; } = [];

        public void Record(PlaybackPerformanceEvent performanceEvent) =>
            Events.Add(performanceEvent);
    }
}
