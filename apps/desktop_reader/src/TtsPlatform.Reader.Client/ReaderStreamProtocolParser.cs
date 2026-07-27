using System.Text.Json;

namespace TtsPlatform.Reader.Client;

public sealed class ReaderStreamProtocolParser
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private string? _streamId;
    private string? _documentId;
    private ReaderCursor? _lastCursor;
    private PendingMark? _pendingMark;
    private int _nextChunkIndex;
    private bool _terminal;

    public ReaderStreamEvent? ProcessText(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            throw Invalid("Reader stream returned an empty text event.");
        }

        WireEnvelope envelope;
        try
        {
            envelope = JsonSerializer.Deserialize<WireEnvelope>(json, JsonOptions)
                ?? throw Invalid("Reader stream returned an empty JSON object.");
        }
        catch (JsonException exception)
        {
            throw new ReaderStreamProtocolException("Reader stream returned invalid JSON.", exception);
        }

        return envelope.Type switch
        {
            "started" => ParseStarted(json),
            "mark" => ParseMark(json),
            "done" => ParseDone(json),
            "cancelled" => ParseCancelled(json),
            "error" => ParseError(json),
            _ => throw Invalid($"Reader stream returned an unknown event type '{envelope.Type}'."),
        };
    }

    public ReaderAudioPacket ProcessBinary(ReadOnlyMemory<byte> pcmBytes)
    {
        EnsureActive();
        var mark = _pendingMark ?? throw Invalid("Reader stream returned PCM without a preceding mark.");
        if (pcmBytes.Length != mark.PcmByteCount)
        {
            throw Invalid("Reader stream PCM length did not match its mark.");
        }

        _pendingMark = null;
        _lastCursor = mark.CursorEnd;
        _nextChunkIndex++;
        return new ReaderAudioPacket(
            StreamId: RequiredStreamId(),
            DocumentId: RequiredDocumentId(),
            ChunkIndex: mark.ChunkIndex,
            DurationMs: mark.DurationMs,
            CursorStart: mark.CursorStart,
            CursorEnd: mark.CursorEnd,
            SourceSpans: mark.SourceSpans,
            SectionId: mark.SectionId,
            IsLast: mark.IsLast,
            PcmBytes: pcmBytes.ToArray());
    }

    private ReaderStreamStarted ParseStarted(string json)
    {
        if (_streamId is not null || _terminal)
        {
            throw Invalid("Reader stream returned more than one started event.");
        }

        var wire = Deserialize<WireStarted>(json);
        if (string.IsNullOrWhiteSpace(wire.StreamId) || string.IsNullOrWhiteSpace(wire.DocumentId))
        {
            throw Invalid("Reader stream started event omitted its identity.");
        }
        if (wire.SampleRateHz <= 0 || wire.Channels != 1 || wire.SampleFormat != "pcm16le")
        {
            throw Invalid("Reader stream returned an unsupported audio format.");
        }
        if (wire.SourceOffsetEncoding != "utf-16")
        {
            throw Invalid("Reader stream returned an unsupported source offset encoding.");
        }

        _streamId = wire.StreamId;
        _documentId = wire.DocumentId;
        _lastCursor = ToCursor(wire.Cursor, wire.DocumentId);
        return new ReaderStreamStarted(
            wire.StreamId,
            wire.DocumentId,
            wire.SampleRateHz,
            wire.Channels,
            wire.SampleFormat,
            wire.PipelineVersion,
            wire.RulesVersion,
            _lastCursor);
    }

    private ReaderStreamEvent? ParseMark(string json)
    {
        EnsureActive();
        if (_pendingMark is not null)
        {
            throw Invalid("Reader stream returned a second mark before PCM.");
        }

        var wire = Deserialize<WireMark>(json);
        ValidateIdentity(wire.StreamId, wire.DocumentId);
        if (wire.ChunkIndex != _nextChunkIndex || wire.PcmByteCount <= 0 || wire.DurationMs < 0)
        {
            throw Invalid("Reader stream returned invalid chunk metadata.");
        }

        var cursorStart = ToCursor(wire.CursorStart, RequiredDocumentId());
        var cursorEnd = ToCursor(wire.CursorEnd, RequiredDocumentId());
        if (_lastCursor is not null && Compare(cursorStart, _lastCursor) < 0)
        {
            throw Invalid("Reader stream cursor moved backwards without a seek.");
        }
        if (Compare(cursorEnd, cursorStart) < 0)
        {
            throw Invalid("Reader stream chunk ended before it started.");
        }

        var spans = (wire.SourceSpans ?? []).Select(ToSourceSpan).ToArray();
        _pendingMark = new PendingMark(
            wire.ChunkIndex,
            wire.PcmByteCount,
            wire.DurationMs,
            cursorStart,
            cursorEnd,
            spans,
            wire.SectionId,
            wire.IsLast);
        return null;
    }

    private ReaderStreamDone ParseDone(string json)
    {
        EnsureActive();
        EnsureNoPendingPcm();
        var wire = Deserialize<WireDone>(json);
        ValidateStreamId(wire.StreamId);
        var cursor = ToCursor(wire.Cursor, RequiredDocumentId());
        if (_lastCursor is not null && Compare(cursor, _lastCursor) < 0)
        {
            throw Invalid("Reader stream completion cursor moved backwards.");
        }

        _terminal = true;
        return new ReaderStreamDone(
            RequiredStreamId(),
            cursor,
            wire.DocumentComplete,
            wire.NextWindowAvailable);
    }

    private ReaderStreamCancelled ParseCancelled(string json)
    {
        EnsureActive();
        EnsureNoPendingPcm();
        var wire = Deserialize<WireCancelled>(json);
        ValidateStreamId(wire.StreamId);
        _terminal = true;
        return new ReaderStreamCancelled(
            RequiredStreamId(),
            ToCursor(wire.GeneratedCursor, RequiredDocumentId()));
    }

    private ReaderStreamError ParseError(string json)
    {
        EnsureNoPendingPcm();
        var wire = Deserialize<WireErrorEnvelope>(json);
        _terminal = true;
        return new ReaderStreamError(
            _streamId ?? string.Empty,
            wire.Error?.Type ?? "reader_stream_error",
            wire.Error?.Message ?? "The Reader stream failed.");
    }

    private static ReaderSourceSpan ToSourceSpan(WireSourceSpan wire)
    {
        if (string.IsNullOrWhiteSpace(wire.BlockId) ||
            wire.BlockOrdinal < 0 ||
            wire.StartOffset < 0 ||
            wire.EndOffset < wire.StartOffset)
        {
            throw Invalid("Reader stream returned an invalid source span.");
        }

        return new ReaderSourceSpan(
            wire.BlockId,
            wire.BlockOrdinal,
            wire.StartOffset,
            wire.EndOffset);
    }

    private static ReaderCursor ToCursor(WireCursor? wire, string documentId)
    {
        if (wire is null || string.IsNullOrWhiteSpace(wire.BlockId) ||
            wire.BlockOrdinal < 0 || wire.CharacterOffset < 0 || wire.ContentRevision <= 0)
        {
            throw Invalid("Reader stream returned an invalid cursor.");
        }

        return new ReaderCursor(
            documentId,
            wire.BlockId,
            wire.BlockOrdinal,
            wire.CharacterOffset,
            wire.ContentRevision,
            wire.SegmentIndex);
    }

    private static int Compare(ReaderCursor left, ReaderCursor right)
    {
        if (!string.Equals(left.DocumentId, right.DocumentId, StringComparison.Ordinal) ||
            left.ContentRevision != right.ContentRevision)
        {
            throw Invalid("Reader stream changed document identity or content revision.");
        }

        var ordinal = left.BlockOrdinal.CompareTo(right.BlockOrdinal);
        return ordinal != 0 ? ordinal : left.CharacterOffset.CompareTo(right.CharacterOffset);
    }

    private void EnsureActive()
    {
        if (_streamId is null)
        {
            throw Invalid("Reader stream event arrived before started.");
        }
        if (_terminal)
        {
            throw Invalid("Reader stream event arrived after completion.");
        }
    }

    private void EnsureNoPendingPcm()
    {
        if (_pendingMark is not null)
        {
            throw Invalid("Reader stream ended before marked PCM arrived.");
        }
    }

    private void ValidateIdentity(string? streamId, string? documentId)
    {
        ValidateStreamId(streamId);
        if (!string.Equals(documentId, _documentId, StringComparison.Ordinal))
        {
            throw Invalid("Reader stream changed document identity.");
        }
    }

    private void ValidateStreamId(string? streamId)
    {
        if (!string.Equals(streamId, _streamId, StringComparison.Ordinal))
        {
            throw Invalid("Reader stream changed stream identity.");
        }
    }

    private string RequiredStreamId() =>
        _streamId ?? throw Invalid("Reader stream has not started.");

    private string RequiredDocumentId() =>
        _documentId ?? throw Invalid("Reader stream has no document identity.");

    private static T Deserialize<T>(string json) =>
        JsonSerializer.Deserialize<T>(json, JsonOptions)
        ?? throw Invalid("Reader stream returned an incomplete event.");

    private static ReaderStreamProtocolException Invalid(string message) => new(message);

    private sealed record PendingMark(
        int ChunkIndex,
        int PcmByteCount,
        int DurationMs,
        ReaderCursor CursorStart,
        ReaderCursor CursorEnd,
        IReadOnlyList<ReaderSourceSpan> SourceSpans,
        string? SectionId,
        bool IsLast);

    private sealed record WireEnvelope(string Type);
    private sealed record WireCursor(
        string? BlockId,
        int BlockOrdinal,
        int CharacterOffset,
        int ContentRevision,
        int? SegmentIndex);
    private sealed record WireStarted(
        string StreamId,
        string DocumentId,
        int SampleRateHz,
        int Channels,
        string SampleFormat,
        int PipelineVersion,
        int RulesVersion,
        string SourceOffsetEncoding,
        WireCursor? Cursor);
    private sealed record WireSourceSpan(
        string? BlockId,
        int BlockOrdinal,
        int StartOffset,
        int EndOffset);
    private sealed record WireMark(
        string? StreamId,
        string? DocumentId,
        int ChunkIndex,
        int PcmByteCount,
        int DurationMs,
        WireCursor? CursorStart,
        WireCursor? CursorEnd,
        IReadOnlyList<WireSourceSpan>? SourceSpans,
        string? SectionId,
        bool IsLast);
    private sealed record WireDone(
        string? StreamId,
        WireCursor? Cursor,
        bool DocumentComplete,
        bool NextWindowAvailable);
    private sealed record WireCancelled(string? StreamId, WireCursor? GeneratedCursor);
    private sealed record WireError(string? Type, string? Message);
    private sealed record WireErrorEnvelope(WireError? Error);
}

public sealed class ReaderStreamProtocolException(string message, Exception? innerException = null)
    : Exception(message, innerException);
