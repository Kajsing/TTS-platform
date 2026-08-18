using System.Buffers;
using System.Net.Http.Headers;
using System.Net.WebSockets;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace TtsPlatform.Reader.Client;

public sealed class ReaderStreamClient : IReaderStreamClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly Uri _serviceBaseUri;
    private readonly ITokenProvider _tokenProvider;
    private readonly ReaderPrivacySessionStore? _privacySessions;

    public ReaderStreamClient(
        string serviceBaseUrl,
        ITokenProvider tokenProvider,
        ReaderPrivacySessionStore? privacySessions = null)
    {
        _serviceBaseUri = ServiceBaseUrl.Parse(serviceBaseUrl);
        _tokenProvider = tokenProvider;
        _privacySessions = privacySessions;
    }

    public async Task<IReaderStreamSession> OpenAsync(
        ReaderStreamStartRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.DocumentId);
        if (!string.Equals(request.Cursor.DocumentId, request.DocumentId, StringComparison.Ordinal))
        {
            throw new ArgumentException("The stream cursor must belong to the requested document.", nameof(request));
        }

        var token = (await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false))?.Trim();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ReaderTokenUnavailableException(
                "Choose the service token file before starting Reader playback.");
        }

        var socket = new ClientWebSocket();
        socket.Options.SetRequestHeader("Authorization", new AuthenticationHeaderValue("Bearer", token).ToString());
        var privacyHeader = _privacySessions?.GetHeaderValue();
        if (!string.IsNullOrWhiteSpace(privacyHeader))
        {
            socket.Options.SetRequestHeader(ReaderPrivacySessionStore.HeaderName, privacyHeader);
        }
        var streamUri = new UriBuilder(_serviceBaseUri)
        {
            Scheme = "ws",
            Path = "/v1/reader/stream",
        }.Uri;
        try
        {
            await socket.ConnectAsync(streamUri, cancellationToken).ConfigureAwait(false);
            var start = new
            {
                type = "start",
                payload = new
                {
                    document_id = request.DocumentId,
                    cursor = new
                    {
                        block_id = request.Cursor.BlockId,
                        block_ordinal = request.Cursor.BlockOrdinal,
                        character_offset = request.Cursor.CharacterOffset,
                        content_revision = request.Cursor.ContentRevision,
                        segment_index = request.Cursor.SegmentIndex,
                    },
                    voice = request.Voice,
                    language_hint = request.LanguageHint,
                    prosody = request.Prosody ?? new ReaderProsody(),
                    window = request.Window ?? new ReaderStreamWindow(),
                },
            };
            var bytes = JsonSerializer.SerializeToUtf8Bytes(start, JsonOptions);
            await socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken)
                .ConfigureAwait(false);
            return new ReaderStreamSession(socket);
        }
        catch
        {
            socket.Dispose();
            throw;
        }
    }

    private sealed class ReaderStreamSession(ClientWebSocket socket) : IReaderStreamSession
    {
        private const int ReceiveChunkBytes = 16 * 1024;
        private const int MaxTextMessageBytes = 64 * 1024;
        private const int MaxBinaryMessageBytes = 2 * 1024 * 1024;
        private readonly ReaderStreamProtocolParser _parser = new();
        private readonly SemaphoreSlim _sendLock = new(1, 1);
        private string? _streamId;
        private bool _controlSent;

        public async IAsyncEnumerable<ReaderStreamEvent> ReadEventsAsync(
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            var receiveBuffer = ArrayPool<byte>.Shared.Rent(ReceiveChunkBytes);
            try
            {
                while (socket.State is WebSocketState.Open or WebSocketState.CloseSent)
                {
                    using var message = new MemoryStream();
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await socket.ReceiveAsync(
                            new ArraySegment<byte>(receiveBuffer),
                            cancellationToken).ConfigureAwait(false);
                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            yield break;
                        }

                        var limit = result.MessageType == WebSocketMessageType.Text
                            ? MaxTextMessageBytes
                            : MaxBinaryMessageBytes;
                        if (message.Length + result.Count > limit)
                        {
                            throw new ReaderStreamProtocolException("Reader stream message exceeded the client limit.");
                        }
                        message.Write(receiveBuffer, 0, result.Count);
                    }
                    while (!result.EndOfMessage);

                    ReaderStreamEvent? parsed;
                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        parsed = _parser.ProcessText(Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length));
                    }
                    else if (result.MessageType == WebSocketMessageType.Binary)
                    {
                        parsed = _parser.ProcessBinary(message.ToArray());
                    }
                    else
                    {
                        throw new ReaderStreamProtocolException("Reader stream returned an unsupported message type.");
                    }

                    if (parsed is null)
                    {
                        continue;
                    }
                    if (parsed is ReaderStreamStarted started)
                    {
                        _streamId = started.StreamId;
                    }
                    yield return parsed;
                    if (parsed is ReaderStreamDone or ReaderStreamCancelled or ReaderStreamError)
                    {
                        yield break;
                    }
                }
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(receiveBuffer);
            }
        }

        public Task CancelAsync(CancellationToken cancellationToken = default) =>
            SendControlAsync("cancel", cancellationToken);

        public Task ReleaseAsync(CancellationToken cancellationToken = default) =>
            SendControlAsync("release", cancellationToken);

        public async ValueTask DisposeAsync()
        {
            if (socket.State == WebSocketState.Open)
            {
                try
                {
                    await socket.CloseOutputAsync(
                        WebSocketCloseStatus.NormalClosure,
                        "Reader session closed",
                        CancellationToken.None).ConfigureAwait(false);
                }
                catch (WebSocketException)
                {
                    // The service may already have closed after a terminal event.
                }
            }
            socket.Dispose();
            _sendLock.Dispose();
        }

        private async Task SendControlAsync(string type, CancellationToken cancellationToken)
        {
            await _sendLock.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                if (_controlSent || socket.State != WebSocketState.Open)
                {
                    return;
                }

                var bytes = JsonSerializer.SerializeToUtf8Bytes(
                    new { type, stream_id = _streamId },
                    JsonOptions);
                await socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken)
                    .ConfigureAwait(false);
                _controlSent = true;
            }
            finally
            {
                _sendLock.Release();
            }
        }
    }
}
