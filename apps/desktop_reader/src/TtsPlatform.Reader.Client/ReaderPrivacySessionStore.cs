namespace TtsPlatform.Reader.Client;

public sealed class ReaderPrivacySessionsChangedEventArgs(
    IReadOnlyCollection<string> removedFolderIds) : EventArgs
{
    public IReadOnlyCollection<string> RemovedFolderIds { get; } = removedFolderIds;
}

public sealed class ReaderPrivacySessionStore : IDisposable
{
    public const string HeaderName = "X-Reader-Privacy-Sessions";
    private const int MaximumSessions = 32;

    private readonly object _gate = new();
    private readonly Dictionary<string, ReaderPrivacySession> _sessions =
        new(StringComparer.Ordinal);
    private readonly Timer _expiryTimer;
    private bool _disposed;

    public ReaderPrivacySessionStore()
    {
        _expiryTimer = new Timer(_ => RemoveExpiredSessions(), null, TimeSpan.FromSeconds(1),
            TimeSpan.FromSeconds(1));
    }

    public event EventHandler<ReaderPrivacySessionsChangedEventArgs>? SessionsChanged;

    public void Store(ReaderPrivacySession session)
    {
        ArgumentNullException.ThrowIfNull(session);
        string? removedFolderId = null;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (!_sessions.ContainsKey(session.FolderId) && _sessions.Count >= MaximumSessions)
            {
                removedFolderId = _sessions.Values
                    .OrderBy(item => item.ExpiresAt)
                    .ThenBy(item => item.FolderId, StringComparer.Ordinal)
                    .First().FolderId;
                _sessions.Remove(removedFolderId);
            }
            _sessions[session.FolderId] = session;
        }
        if (removedFolderId is not null)
        {
            SessionsChanged?.Invoke(
                this,
                new ReaderPrivacySessionsChangedEventArgs([removedFolderId]));
        }
    }

    public void Remove(string folderId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folderId);
        var removed = false;
        lock (_gate)
        {
            if (!_disposed)
            {
                removed = _sessions.Remove(folderId);
            }
        }
        if (removed)
        {
            SessionsChanged?.Invoke(
                this,
                new ReaderPrivacySessionsChangedEventArgs([folderId]));
        }
    }

    public void Clear()
    {
        string[] removed;
        lock (_gate)
        {
            if (_disposed || _sessions.Count == 0)
            {
                return;
            }
            removed = _sessions.Keys.ToArray();
            _sessions.Clear();
        }
        SessionsChanged?.Invoke(this, new ReaderPrivacySessionsChangedEventArgs(removed));
    }

    public bool IsUnlocked(string folderId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folderId);
        RemoveExpiredSessions();
        lock (_gate)
        {
            return !_disposed && _sessions.ContainsKey(folderId);
        }
    }

    public string? GetHeaderValue()
    {
        RemoveExpiredSessions();
        lock (_gate)
        {
            if (_disposed || _sessions.Count == 0)
            {
                return null;
            }
            return string.Join(',', _sessions.Values
                .OrderBy(session => session.FolderId, StringComparer.Ordinal)
                .Select(session => session.SessionToken));
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            _sessions.Clear();
        }
        _expiryTimer.Dispose();
    }

    private void RemoveExpiredSessions()
    {
        string[] removed;
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }
            var now = DateTimeOffset.UtcNow;
            removed = _sessions
                .Where(item => item.Value.ExpiresAt <= now)
                .Select(item => item.Key)
                .ToArray();
            foreach (var folderId in removed)
            {
                _sessions.Remove(folderId);
            }
        }
        if (removed.Length > 0)
        {
            SessionsChanged?.Invoke(this, new ReaderPrivacySessionsChangedEventArgs(removed));
        }
    }
}
