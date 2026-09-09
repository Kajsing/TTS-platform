using System.Text;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.Windows.Tests;

public sealed class ProtectedCaptureOutboxTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), "reader-capture-test-" + Guid.NewGuid());
    [Fact]
    public void Protected_queue_roundtrips_large_unicode_capture_after_restart()
    {
        var text = string.Concat(Enumerable.Repeat("Chapter æøå 😀.\n", 10_000));
        var store = new ProtectedCaptureOutboxStore(_directory);
        var item = new CaptureOutbox(store).Enqueue("workspace-hash", new("create", text), true);
        var file = Assert.Single(Directory.GetFiles(_directory));
        Assert.DoesNotContain("workspace-hash", Encoding.UTF8.GetString(File.ReadAllBytes(file)));
        Assert.DoesNotContain("Chapter", Encoding.UTF8.GetString(File.ReadAllBytes(file)));
        var restored = new CaptureOutbox(new ProtectedCaptureOutboxStore(_directory));
        Assert.Equal(text, Assert.Single(restored.Items).Request.Text);
        Assert.Equal(item.Id, restored.Items[0].Id);
        restored.Discard(item.Id);
        Assert.Empty(Directory.GetFiles(_directory));
    }
    [Fact]
    public void Corrupt_envelope_is_reported_without_deleting_evidence()
    {
        Directory.CreateDirectory(_directory);
        var path = Path.Combine(_directory, Guid.NewGuid() + ".bin");
        File.WriteAllBytes(path, [1, 2, 3]);
        Assert.Throws<ReaderTokenUnavailableException>(() => new ProtectedCaptureOutboxStore(_directory).Load());
        Assert.Equal(new byte[] { 1, 2, 3 }, File.ReadAllBytes(path));
    }
    public void Dispose() { if (Directory.Exists(_directory)) Directory.Delete(_directory, true); }
}
