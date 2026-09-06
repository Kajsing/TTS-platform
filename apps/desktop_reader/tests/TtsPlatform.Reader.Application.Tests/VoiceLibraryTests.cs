using TtsPlatform.Reader.Application;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class VoiceLibraryTests
{
    private static readonly VoiceLibraryInventory Inventory = new(new string('a', 64), new string('b', 64), "old", true,
        [new("old", "Existing voice", "en-US", "vits", "test", "models/voices/old", true, true)],
        [new("new", "New voice", "da-DK", "vits", 1048576, "Fixture only", "https://example.test/license", "https://example.test/source",
            [new("new", "New voice", "da-DK")], false, true, null)]);

    [Fact]
    public async Task License_review_is_required_and_duplicates_are_blocked_until_actual_completion()
    {
        var fake = new Library();
        var controller = new VoiceLibraryController(fake);
        await controller.RefreshAsync();
        await controller.InstallAsync("new", false);
        Assert.Equal(0, fake.Installs);
        var pending = controller.InstallAsync("new", true);
        Assert.True(controller.IsInstalling);
        await controller.InstallAsync("new", true);
        await controller.RefreshAsync();
        Assert.Equal(1, fake.Installs);
        Assert.Equal(1, fake.Lists);
        Assert.Equal(Inventory.CatalogFingerprint, fake.Fingerprint);
        fake.Completion.SetResult(new(true, false, "Installed; restart required."));
        await pending;
        Assert.False(controller.IsBusy);
        Assert.Equal(2, fake.Lists);
        Assert.Contains("restart required", controller.Message);
    }

    [Fact]
    public async Task Cancellation_keeps_owner_busy_and_late_commit_success_is_not_discarded()
    {
        var fake = new Library();
        var controller = new VoiceLibraryController(fake);
        await controller.RefreshAsync();
        var pending = controller.InstallAsync("new", true);
        controller.Cancel();
        Assert.True(fake.Token.IsCancellationRequested);
        Assert.True(controller.IsBusy);
        Assert.False(controller.CanCancel);
        Assert.False(pending.IsCompleted);
        fake.Completion.SetResult(new(true, false, "Commit completed before cancellation."));
        await pending;
        Assert.Contains("Commit completed", controller.Message);
        Assert.NotNull(controller.Inventory);
        Assert.False(controller.IsBusy);
    }

    [Fact]
    public async Task Unknown_outcome_invalidates_old_inventory_until_refresh()
    {
        var fake = new Library();
        var controller = new VoiceLibraryController(fake);
        await controller.RefreshAsync();
        var pending = controller.InstallAsync("new", true);
        fake.Completion.SetException(new VoiceLibraryException("Outcome unknown."));
        await pending;
        Assert.Null(controller.Inventory);
        Assert.Contains("Refresh", controller.Message);
        Assert.False(controller.IsBusy);
    }

    [Fact]
    public async Task Raw_operating_system_errors_are_not_shown_in_the_library()
    {
        var controller = new VoiceLibraryController(new Library { ReadFailure = true });
        await controller.RefreshAsync();
        Assert.Null(controller.Inventory);
        Assert.DoesNotContain("secret", controller.Message);
        Assert.False(controller.IsBusy);
    }

    [Theory]
    [InlineData("extracting", null, null, null)]
    [InlineData("downloading", 5L, 10L, 50d)]
    [InlineData("verifying", 15L, 10L, 100d)]
    [InlineData("verifying", 0L, 0L, null)]
    public void Progress_has_phase_specific_truthful_percent(string phase, long? bytes, long? total, double? percent)
    {
        Assert.Equal(percent, new VoiceInstallationProgress(phase, bytes, total, true).Percent);
    }

    private sealed class Library : ILocalVoiceLibrary
    {
        internal int Lists;
        internal int Installs;
        internal string? Fingerprint;
        internal bool ReadFailure;
        internal CancellationToken Token;
        internal readonly TaskCompletionSource<VoiceInstallationOutcome> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public Task<VoiceLibraryInventory> ListAsync(CancellationToken token)
        {
            Lists++;
            if (ReadFailure) throw new IOException("secret location");
            return Task.FromResult(Inventory);
        }
        public Task<VoiceInstallationOutcome> InstallAsync(string id, string fingerprint, bool accepted,
            IProgress<VoiceInstallationProgress> progress, CancellationToken token)
        {
            Installs++;
            Fingerprint = fingerprint;
            Token = token;
            return Completion.Task;
        }
    }
}
