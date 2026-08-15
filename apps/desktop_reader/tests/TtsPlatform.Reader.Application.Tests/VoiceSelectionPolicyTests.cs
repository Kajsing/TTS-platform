using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application.Tests;

public sealed class VoiceSelectionPolicyTests
{
    private static readonly VoiceDescriptor First = Voice("first", "First");
    private static readonly VoiceDescriptor Second = Voice("second", "Second");

    [Fact]
    public void Preferred_available_voice_wins()
    {
        var selected = VoiceSelectionPolicy.Resolve(
            new VoicePage([First, Second], First.Id),
            Second.Id);

        Assert.Equal(Second, selected);
    }

    [Fact]
    public void Missing_preference_falls_back_to_service_default_then_first_voice()
    {
        var defaultSelected = VoiceSelectionPolicy.Resolve(
            new VoicePage([First, Second], Second.Id),
            "removed");
        var firstSelected = VoiceSelectionPolicy.Resolve(
            new VoicePage([First, Second], "removed"),
            "also-removed");

        Assert.Equal(Second, defaultSelected);
        Assert.Equal(First, firstSelected);
    }

    [Fact]
    public void Empty_voice_page_has_no_selection()
    {
        Assert.Null(VoiceSelectionPolicy.Resolve(new VoicePage([], null), "removed"));
        Assert.Null(VoiceSelectionPolicy.Resolve(null, "removed"));
    }

    private static VoiceDescriptor Voice(string id, string name) => new(
        id,
        name,
        "test",
        "en-US",
        24_000,
        "test",
        "test",
        null,
        "test",
        "local");
}
