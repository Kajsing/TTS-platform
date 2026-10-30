namespace TtsPlatform.Reader.Client;

public static class ReaderRequestBudget
{
    public const string Header = "X-TTS-Request-Budget";
    public const string Playback = "playback";
    public const string Background = "background";

    public static string ForRequest(HttpRequestMessage request)
    {
        var path = request.RequestUri!.IsAbsoluteUri
            ? request.RequestUri.AbsolutePath
            : "/" + request.RequestUri.OriginalString.Split('?')[0].TrimStart('/');
        var parts = path.Split('/');
        var document = parts.Length >= 5 && parts[1] == "v1" && parts[2] == "reader" &&
            parts[3] == "documents" && parts[4].Length > 0;
        if (document && request.Method == HttpMethod.Get &&
            (parts.Length == 5 || (parts.Length == 6 && parts[5] is "blocks" or "position")))
            return Playback;
        if (document && request.Method == HttpMethod.Put && parts.Length == 6 && parts[5] == "position")
            return Playback;
        if (request.Method == HttpMethod.Post && (path == "/v1/tts" ||
            (parts.Length == 6 && parts[1] == "v1" && parts[2] == "reader" && parts[3] == "queue" &&
                parts[4] == "advance" && parts[5].Length > 0) ||
            (parts.Length == 7 && parts[1] == "v1" && parts[2] == "reader" && parts[3] == "queue" &&
                parts[4] == "items" && parts[5].Length > 0 && parts[6] == "activate")))
            return Playback;
        return Background;
    }
}
