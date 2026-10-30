namespace TtsPlatform.Reader.Client;

// Only overlapping reads share work. Completed/failed responses are never cached.
internal sealed class ReaderReadCoalescer
{
    internal const int MaximumRequests = 32;
    internal const int MaximumWaiters = 16;
    private readonly object _gate = new();
    private readonly Dictionary<(long Epoch, string Key), Flight> _flights = [];
    private long _epoch;

    public void Invalidate()
    {
        lock (_gate) _epoch++;
    }

    public async Task<T> ReadAsync<T>(string key, Func<CancellationToken, Task<T>> read,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Flight flight;
        (long Epoch, string Key) identity;
        var start = false;
        lock (_gate)
        {
            identity = (_epoch, key);
            if (!_flights.TryGetValue(identity, out flight!))
            {
                if (_flights.Count >= MaximumRequests) throw Full();
                flight = new();
                _flights.Add(identity, flight);
                start = true;
            }
            if (flight.Waiters >= MaximumWaiters) throw Full();
            flight.Waiters++;
        }
        if (start) _ = CompleteAsync(identity, flight, read);
        try
        {
            return (T)(await flight.Completion.Task.WaitAsync(cancellationToken).ConfigureAwait(false))!;
        }
        finally
        {
            var cancel = false;
            lock (_gate)
            {
                flight.Waiters--;
                if (flight.Waiters == 0 && !flight.Finished)
                {
                    Remove(identity, flight);
                    cancel = true;
                }
            }
            if (cancel)
            {
                try { flight.Cancellation.Cancel(); }
                catch (ObjectDisposedException) { } // Completion won the last-waiter race.
            }
        }
    }

    private async Task CompleteAsync<T>((long Epoch, string Key) identity, Flight flight,
        Func<CancellationToken, Task<T>> read)
    {
        object? result = null;
        Exception? failure = null;
        try { result = await read(flight.Cancellation.Token).ConfigureAwait(false); }
        catch (Exception exception) { failure = exception; }
        lock (_gate)
        {
            flight.Finished = true;
            Remove(identity, flight);
        }
        if (failure is OperationCanceledException)
            flight.Completion.TrySetCanceled();
        else if (failure is not null)
        {
            flight.Completion.TrySetException(failure);
            _ = flight.Completion.Task.Exception; // Last waiter may already have cancelled.
        }
        else
            flight.Completion.TrySetResult(result);
        flight.Cancellation.Dispose();
    }

    private void Remove((long Epoch, string Key) identity, Flight flight)
    {
        if (_flights.TryGetValue(identity, out var current) && ReferenceEquals(current, flight))
            _flights.Remove(identity);
    }

    private static ReaderApiException Full() => new("reader_request_queue_full",
        "Too many Reader reads are waiting. Try again shortly.", 503);

    private sealed class Flight
    {
        public int Waiters;
        public bool Finished;
        public CancellationTokenSource Cancellation { get; } = new();
        public TaskCompletionSource<object?> Completion { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    }
}
