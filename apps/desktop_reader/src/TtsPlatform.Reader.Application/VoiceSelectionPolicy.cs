using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.Application;

public static class VoiceSelectionPolicy
{
    public static VoiceDescriptor? Resolve(VoicePage? page, string? preferredVoiceId)
    {
        if (page is null || page.Voices.Count == 0)
        {
            return null;
        }

        var preferred = Find(page, preferredVoiceId);
        if (preferred is not null)
        {
            return preferred;
        }

        return Find(page, page.DefaultVoice) ?? page.Voices[0];
    }

    private static VoiceDescriptor? Find(VoicePage page, string? voiceId) =>
        string.IsNullOrWhiteSpace(voiceId)
            ? null
            : page.Voices.FirstOrDefault(
                voice => string.Equals(voice.Id, voiceId, StringComparison.Ordinal));
}
