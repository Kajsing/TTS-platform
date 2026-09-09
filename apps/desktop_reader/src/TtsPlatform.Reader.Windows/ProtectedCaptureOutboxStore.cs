using System.Text.Json;
using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Windows;

/// <summary>DPAPI CurrentUser envelopes. Plaintext never enters an on-disk index.</summary>
public sealed class ProtectedCaptureOutboxStore : ICaptureOutboxStore
{
    private readonly string _directory;
    private readonly DpapiCredentialStore _protected;
    public ProtectedCaptureOutboxStore(string? directory = null)
    {
        _directory = directory ?? Path.Combine(DesktopPaths.ReaderHome, "capture-outbox");
        _protected = new DpapiCredentialStore(_directory);
    }
    public IReadOnlyList<PendingCapture> Load()
    {
        if (!Directory.Exists(_directory)) return [];
        var paths = Directory.GetFiles(_directory, "*.bin");
        if (paths.Length > CaptureOutbox.MaxItems) throw new IOException("Capture queue exceeds its safety limit. Files have been preserved.");
        var items = new List<PendingCapture>();
        foreach (var path in paths)
        {
            if (new FileInfo(path).Length > 16_000_000) throw new IOException("Invalid capture envelope. Files have been preserved.");
            var id = Path.GetFileNameWithoutExtension(path);
            PendingCapture item;
            try { item = JsonSerializer.Deserialize<PendingCapture>(_protected.Load(id)!) ?? throw new JsonException(); }
            catch (JsonException) { throw new IOException("A capture could not be decoded. Files have been preserved."); }
            if (item.StorageVersion != 1 || item.Id != id || string.IsNullOrWhiteSpace(item.Workspace) || item.Request is null ||
                string.IsNullOrWhiteSpace(item.Request.Text) || item.Request.Text.Length > CaptureOutbox.MaxItemCharacters)
                throw new IOException("Invalid capture envelope. Files have been preserved.");
            items.Add(item);
        }
        if (items.Sum(item => item.Request.Text.Length) > CaptureOutbox.MaxCharacters)
            throw new IOException("Capture queue exceeds its text budget. Files have been preserved.");
        return items;
    }
    public void Save(PendingCapture capture) => _protected.Save(capture.Id, JsonSerializer.Serialize(capture));
    public void Delete(string id) => _protected.Delete(id);
}
