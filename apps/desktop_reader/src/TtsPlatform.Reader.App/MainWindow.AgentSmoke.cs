using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;
using TtsPlatform.Reader.Windows;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private async Task RunAgentSmokeAsync(AgentSmokeScenario scenario)
    {
        var files = new AgentConnectionFiles(scenario.ConnectionsPath);
        var options = new OptionsDialog(_settings, files) { Owner = this };
        options.Show();
        options.AgentAccessTab.IsSelected = true;
        var pane = options.AgentAccessControl;
        pane.AgentPythonTextBox.Text = scenario.Python;
        await pane.RefreshForSmokeAsync(scenario.GrantId);
        object result;
        if (scenario.Phase == "provision")
        {
            var grant = await pane.ProvisionAsync(scenario.FolderId, "Isolated MCP smoke");
            await pane.RefreshForSmokeAsync(grant.Id);
            if (!await files.CheckAsync(grant.Id, scenario.Python))
            {
                throw new InvalidOperationException("C# protected credential did not pass the Python MCP check.");
            }
            pane.AgentStatusText.Text = "Connection ready: Windows protected key verified by the MCP adapter.";
            pane.AgentConfigurationTextBox.Text = files.ClientConfiguration(grant.Id, scenario.Python);
            CaptureSmokeWindow(options, Path.Combine(scenario.Root, "agent-options.png"));
            result = new { provisioned = true, dpapi_cross_language = true, grant_id = grant.Id, config_path = files.ConfigurationPath(grant.Id) };
        }
        else if (scenario.Phase == "read-revoke")
        {
            options.Hide();
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
            var token = new FileTokenProvider(_settings.EffectiveTokenSource.Path);
            _client = new ReaderServiceClient(http, scenario.ServiceUrl, token);
            _editor = new DocumentEditor(_client);
            _library = new LibraryPager(_client);
            _readingWindow = new ReadingWindowPager(_client);
            DocumentsGrid.ItemsSource = _library.Documents;
            await _library.RefreshAsync(folderId: scenario.FolderId);
            var document = _library.Documents.Single(item => item.Id == scenario.ArticleId);
            await LoadDocumentAsync(document);
            if (EditorTextBox.Text.Replace("\r\n", "\n", StringComparison.Ordinal) != scenario.ExpectedText || EditorTextBox.IsReadOnly)
            {
                throw new InvalidOperationException("The MCP article did not appear intact and editable in the ordinary Reader editor.");
            }
            var block = _continuousDocument!.Blocks.First();
            var cursor = new ReaderCursor(document.Id, block.Id, block.Ordinal, 0, document.ContentRevision);
            var stream = new ReaderStreamClient(scenario.ServiceUrl, token);
            var packets = 0;
            var sourceSpans = 0;
            var complete = false;
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            await using (var session = await stream.OpenAsync(new ReaderStreamStartRequest(document.Id, cursor), deadline.Token))
            {
                await foreach (var item in session.ReadEventsAsync(deadline.Token))
                {
                    if (item is ReaderAudioPacket packet && packet.PcmBytes.Length > 0)
                    {
                        packets++;
                        sourceSpans += packet.SourceSpans.Count;
                    }
                    else if (item is ReaderStreamDone done)
                    {
                        complete = done.DocumentComplete;
                    }
                    else if (item is ReaderStreamError)
                    {
                        throw new InvalidOperationException("The MCP article failed normal Reader speech streaming.");
                    }
                }
                await session.ReleaseAsync();
            }
            if (!complete || packets == 0 || sourceSpans == 0)
            {
                throw new InvalidOperationException("Normal Reader speech returned incomplete or unmapped audio.");
            }
            FooterText.Text = "MCP article verified: editable text and complete source-mapped speech stream.";
            CaptureSmokeWindow(this, Path.Combine(scenario.Root, "agent-article.png"));
            await pane.RevokeAsync(scenario.GrantId!);
            await pane.RefreshForSmokeAsync(scenario.GrantId);
            if (files.HasConnection(scenario.GrantId!))
            {
                throw new InvalidOperationException("Revocation left usable connection files.");
            }
            result = new { library_visible = true, editor_complete = true, ordinary_reader_stream = true, packets, source_spans = sourceSpans, revoked = true };
        }
        else
        {
            throw new InvalidOperationException("Unknown isolated agent smoke phase.");
        }
        options.Close();
        File.WriteAllText(scenario.MarkerPath, JsonSerializer.Serialize(result));
    }

    private static void CaptureSmokeWindow(Window window, string path)
    {
        window.UpdateLayout();
        var bitmap = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(window);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var output = File.Create(path);
        encoder.Save(output);
    }
}
