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

        await playback.PlayAsync(Document());
        await WaitUntilAsync(() => playback.State == ReaderPlaybackState.Completed);

        Assert.Equal(2, streams.Requests.Count);
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

        public Task<ReaderPosition?> GetPositionAsync(
            string documentId,
            CancellationToken cancellationToken = default) => Task.FromResult<ReaderPosition?>(null);

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

    private sealed class FakeAudioOutput(int? blockCall = null) : IAudioOutput
    {
        private readonly TaskCompletionSource _stop = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource<int> _calls = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _activeCalls;
        public int CallCount { get; private set; }
        public int MaxConcurrentCalls { get; private set; }

        public async Task PlayAsync(
            ReadOnlyMemory<byte> pcmBytes,
            PcmAudioFormat format,
            CancellationToken cancellationToken = default)
        {
            _ = pcmBytes;
            _ = format;
            CallCount++;
            _calls.TrySetResult(CallCount);
            _activeCalls++;
            MaxConcurrentCalls = Math.Max(MaxConcurrentCalls, _activeCalls);
            try
            {
                if (blockCall == CallCount)
                {
                    await _stop.Task.WaitAsync(cancellationToken);
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
            return Task.CompletedTask;
        }

        public Task DrainAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
