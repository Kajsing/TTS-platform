using System.Collections.Concurrent;

namespace TtsPlatform.Reader.Client;

public sealed class ReaderRequestCooldown(TimeProvider? time = null)
{
    public const int MaxPendingRequestsPerBudget = 16;
    private static readonly ConcurrentDictionary<string, ReaderRequestCooldown> Shared = new(StringComparer.Ordinal);
    private readonly TimeProvider _time = time ?? TimeProvider.System;
    private readonly ConcurrentDictionary<string, BudgetState> _budgets = new(StringComparer.Ordinal);
    private long _legacyUntilTicks;
    public static ReaderRequestCooldown ForService(string serviceUrl) =>
        Shared.GetOrAdd(new Uri(serviceUrl).GetLeftPart(UriPartial.Authority), _ => new());
    public void Observe(HttpResponseMessage response)
    {
        if ((int)response.StatusCode != 429) return;
        var labels = response.Headers.TryGetValues(ReaderRequestBudget.Header, out var values)
            ? values.ToArray() : [];
        var budget = labels.Length == 1 ? labels[0] : null;
        var seconds = response.Headers.RetryAfter?.Delta?.TotalSeconds ??
            (response.Headers.RetryAfter?.Date - _time.GetUtcNow())?.TotalSeconds ?? 61;
        Observe(budget, seconds);
    }

    public void Observe(ReaderStreamError error)
    {
        if (error.ErrorType == "rate_limited") Observe(error.RequestBudget, error.RetryAfterSeconds ?? 61);
    }

    private void Observe(string? budget, double seconds)
    {
        var deadline = _time.GetUtcNow().AddSeconds(Math.Clamp(seconds, 1, 3600)).Ticks;
        if (budget is ReaderRequestBudget.Playback or ReaderRequestBudget.Background)
            Extend(ref State(budget).UntilTicks, deadline);
        else
            Extend(ref _legacyUntilTicks, deadline); // Older services/gateways have a shared limit.
    }

    private static void Extend(ref long untilTicks, long deadline)
    {
        long previous;
        do
        {
            previous = Interlocked.Read(ref untilTicks);
            if (previous >= deadline) return;
        } while (Interlocked.CompareExchange(ref untilTicks, deadline, previous) != previous);
    }
    public int RemainingSeconds => Math.Max(RemainingSecondsFor(ReaderRequestBudget.Playback),
        RemainingSecondsFor(ReaderRequestBudget.Background));

    public int RemainingSecondsFor(string budget) => Math.Max(0, (int)Math.Ceiling(
        (Math.Max(Interlocked.Read(ref _legacyUntilTicks), Interlocked.Read(ref State(budget).UntilTicks)) -
            _time.GetUtcNow().Ticks) / (double)TimeSpan.TicksPerSecond));

    public void Check(HttpRequestMessage request) => Check(ReaderRequestBudget.ForRequest(request));

    public void Check(string budget)
    {
        var seconds = RemainingSecondsFor(budget);
        if (seconds > 0) throw new ReaderApiException("rate_limited", "Waiting for the service request budget to recover.", 429,
            details: new Dictionary<string, object?> { ["retry_after_seconds"] = seconds, ["request_budget"] = budget });
    }

    internal async Task<IDisposable> AcquireAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var budget = ReaderRequestBudget.ForRequest(request);
        Check(budget);
        var state = State(budget);
        if (Interlocked.Increment(ref state.Pending) > MaxPendingRequestsPerBudget)
        {
            Interlocked.Decrement(ref state.Pending);
            throw new ReaderApiException("reader_request_queue_full", "Too many Reader requests are waiting. Try again shortly.", 503);
        }
        var acquired = false;
        try
        {
            await state.Slots.WaitAsync(cancellationToken).ConfigureAwait(false);
            acquired = true;
            Check(budget); // An in-flight request may just have received a 429.
            return new RequestLease(state);
        }
        catch
        {
            if (acquired) state.Slots.Release();
            Interlocked.Decrement(ref state.Pending);
            throw;
        }
    }

    private BudgetState State(string budget) => _budgets.GetOrAdd(budget, _ => new());

    private sealed class BudgetState
    {
        public long UntilTicks;
        public int Pending;
        public SemaphoreSlim Slots { get; } = new(2, 2);
    }

    private sealed class RequestLease(BudgetState state) : IDisposable
    {
        private BudgetState? _state = state;
        public void Dispose()
        {
            var released = Interlocked.Exchange(ref _state, null);
            if (released is null) return;
            Interlocked.Decrement(ref released.Pending);
            released.Slots.Release();
        }
    }
}
