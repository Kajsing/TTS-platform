using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Client.Tests;

public sealed class ReaderStreamProtocolParserTests
{
    [Fact]
    public void Parser_pairs_one_mark_with_one_exact_pcm_frame()
    {
        var parser = StartedParser();

        Assert.Null(parser.ProcessText(MarkJson));
        var packet = parser.ProcessBinary(new byte[] { 1, 2, 3, 4 });
        var done = Assert.IsType<ReaderStreamDone>(parser.ProcessText(DoneJson));

        Assert.Equal(0, packet.ChunkIndex);
        Assert.Equal(4, packet.PcmBytes.Length);
        Assert.Equal(3, packet.CursorEnd.CharacterOffset);
        Assert.Equal(3, packet.SourceSpans.Single().EndOffset);
        Assert.True(done.DocumentComplete);
    }

    [Fact]
    public void Parser_rejects_pcm_without_a_mark()
    {
        var parser = StartedParser();

        var exception = Assert.Throws<ReaderStreamProtocolException>(() =>
            parser.ProcessBinary(new byte[] { 1, 2 }));

        Assert.Contains("without a preceding mark", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Parser_rejects_two_marks_or_a_wrong_pcm_length()
    {
        var duplicateParser = StartedParser();
        duplicateParser.ProcessText(MarkJson);
        Assert.Throws<ReaderStreamProtocolException>(() => duplicateParser.ProcessText(MarkJson));

        var lengthParser = StartedParser();
        lengthParser.ProcessText(MarkJson);
        Assert.Throws<ReaderStreamProtocolException>(() =>
            lengthParser.ProcessBinary(new byte[] { 1, 2 }));
    }

    [Fact]
    public void Parser_rejects_identity_and_cursor_regressions()
    {
        var identityParser = StartedParser();
        Assert.Throws<ReaderStreamProtocolException>(() =>
            identityParser.ProcessText(MarkJson.Replace("\"doc\"", "\"other\"", StringComparison.Ordinal)));

        var cursorParser = StartedParser(characterOffset: 4);
        Assert.Throws<ReaderStreamProtocolException>(() => cursorParser.ProcessText(MarkJson));
    }

    [Fact]
    public void Parser_rejects_an_audio_format_change_at_start()
    {
        var parser = new ReaderStreamProtocolParser();

        Assert.Throws<ReaderStreamProtocolException>(() =>
            parser.ProcessText(StartedJson.Replace("pcm16le", "float32", StringComparison.Ordinal)));
    }

    private static ReaderStreamProtocolParser StartedParser(int characterOffset = 0)
    {
        var parser = new ReaderStreamProtocolParser();
        var started = parser.ProcessText(
            StartedJson.Replace(
                "\"character_offset\":0",
                $"\"character_offset\":{characterOffset}",
                StringComparison.Ordinal));
        Assert.IsType<ReaderStreamStarted>(started);
        return parser;
    }

    private const string StartedJson = """
        {
          "type":"started","stream_id":"stream","document_id":"doc",
          "sample_rate_hz":22050,"channels":1,"sample_format":"pcm16le",
          "pipeline_version":1,"rules_version":1,"source_offset_encoding":"utf-16",
          "cursor":{"block_id":"block","block_ordinal":0,"character_offset":0,"content_revision":1,"segment_index":null}
        }
        """;

    private const string MarkJson = """
        {
          "type":"mark","stream_id":"stream","document_id":"doc","chunk_index":0,
          "pcm_byte_count":4,"duration_ms":10,
          "cursor_start":{"block_id":"block","block_ordinal":0,"character_offset":0,"content_revision":1,"segment_index":0},
          "cursor_end":{"block_id":"block","block_ordinal":0,"character_offset":3,"content_revision":1,"segment_index":0},
          "source_spans":[{"block_id":"block","block_ordinal":0,"start_offset":0,"end_offset":3}],
          "section_id":"section","is_last":true
        }
        """;

    private const string DoneJson = """
        {
          "type":"done","stream_id":"stream","chunks_sent":1,
          "cursor":{"block_id":"block","block_ordinal":0,"character_offset":3,"content_revision":1,"segment_index":0},
          "document_complete":true,"next_window_available":false
        }
        """;
}
