using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    internal async Task VerifyChapterViewsAsync(string root)
    {
        if (!_smokeTest || _editor is not null || _playback is not null)
            throw new InvalidOperationException("Chapter smoke requires an isolated Reader.");
        var client = DispatchProxy.Create<IReaderServiceClient, DocumentSwitchSmokeClient>();
        var fake = (DocumentSwitchSmokeClient)client;
        var blocks = Enumerable.Range(0, 12).Select(index => fake.Block("first") with
        {
            Id = $"chapter-{index}",
            Ordinal = index,
            Text = $"Synthetic paragraph {index + 1}. " + string.Concat(Enumerable.Repeat(
                "The same text remains editable in both chapter views. ", 5)),
        }).ToArray();
        var metadata = JsonSerializer.SerializeToElement(new Dictionary<string, object>
        {
            ["chapter_markers_v1"] = new[]
            {
                new { id = "root", title = "Arrival", block_id = blocks[0].Id, codepoint_offset = 0 },
                new { id = "second", title = "Across the boundary", block_id = blocks[4].Id, codepoint_offset = 10 },
                new { id = "third", title = "Home again", block_id = blocks[8].Id, codepoint_offset = 0 },
            },
        });
        var document = fake.Documents[0] with { Metadata = metadata, TotalBlocks = blocks.Length, TotalCharacters = blocks.Sum(b => b.Text.Length) };
        _editor = new DocumentEditor(client);
        _editor.LoadBlock(document, blocks[0]);
        _continuousDocument = new ContinuousDocumentText(blocks);
        _updatingEditor = true;
        RenderChapterEditor();
        _updatingEditor = false;
        DocumentTitleText.Text = "Synthetic chapter view check";
        async Task Idle()
        {
            await Dispatcher.InvokeAsync(() => UpdateLayout(), DispatcherPriority.ApplicationIdle);
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        }
        static void Require(bool value, string reason)
        { if (!value) throw new InvalidOperationException(reason); }
        try
        {
            UpdatePlaybackControls();
            await Idle();
            var full = _continuousDocument.Text;
            Require(_chapters.Count == 3 && EditorTextBox.Text == full, "Whole article lost chapter content.");
            SelectChapter(_chapters[1], false);
            SingleChapterCheckBox.IsChecked = true;
            await Idle();
            Require(EditorTextBox.Text == _chapters[1].Slice.Text(full), "Chapter view did not slice at a mid-paragraph anchor.");
            _highlighterConfiguration = new ReaderHighlighterConfiguration("chapter-smoke", 1, DateTimeOffset.UnixEpoch,
                [new ReaderHighlighterTerm("term", "Synthetic", "synthetic", true, "#FFFF00", 0, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch)]);
            await RefreshWordHighlightsAsync();
            Require(_wordHighlightResult.Matches.Count == 12 && _wordHighlightResult.Matches[0].Start == 0,
                "Word Highlighter searched the chapter projection instead of the whole article.");
            EditorTextBox.CaretIndex = 15;
            UpdateTextCursorFromContinuousEditor();
            Require(_textCursor?.BlockId == blocks[4].Id && _textCursor.CharacterOffset == 25, "Chapter-local caret was not mapped to its source block.");
            EditorTextBox.SelectedText = "EDIT ";
            Require(_editor.HasUnsavedChanges && _editor.WorkingText == blocks[4].Text.Insert(25, "EDIT "), "Chapter edit overwrote hidden text.");
            var before = EditorTextBox.Text;
            SingleChapterCheckBox.IsChecked = false;
            Require(SingleChapterCheckBox.IsChecked == true && EditorTextBox.Text == before, "View switch discarded an unsaved chapter edit.");
            _editor.RevertLocalChanges();
            _updatingEditor = true;
            RenderChapterEditor();
            _updatingEditor = false;
            var intent = _textCursor;
            FollowReadingCheckBox.IsChecked = true;
            ShowContinuousEditorHighlight(document, [new ReaderSourceSpan(blocks[8].Id, 8, 0, 50)]);
            await Idle();
            Require(_selectedChapterId == "third" && EditorTextBox.Text == _chapters[2].Slice.Text(full), "Audible continuation did not open the next chapter.");
            Require(_continuousHighlightAdorner!.HighlightStart == 0 && _continuousHighlightAdorner.HighlightLength == 50,
                "Chapter highlight used whole-article offsets.");
            Require(_textCursor == intent, "Automatic chapter continuation changed Start-at-cursor intent.");
            var viewport = EditorTextBox.VerticalOffset;
            Playback_StateChanged(null, new(ReaderPlaybackState.Paused, document.Id, null));
            await Idle();
            Require(Math.Abs(viewport - EditorTextBox.VerticalOffset) < 1 && _continuousHighlightAdorner.HighlightLength == 50,
                "Paused chapter jumped or lost its audible marker.");
            FindTextBox.Text = "Synthetic paragraph 2";
            FindCurrentChapterCheckBox.IsChecked = false;
            _highlighterConfiguration = null;
            await RunFindNowAsync();
            Require(_findResult.Matches.Count == 1 && _selectedChapterId == "root", "Whole-article Find could not navigate to a hidden chapter.");
            FindCurrentChapterCheckBox.IsChecked = true;
            FindTextBox.Text = "Synthetic paragraph 9";
            await RunFindNowAsync();
            Require(_findResult.Matches.Count == 0, "Current-chapter Find searched hidden chapters.");
            SelectChapter(_chapters[2], true);
            await Idle();
            var bitmap = new RenderTargetBitmap((int)ActualWidth, (int)ActualHeight, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(this);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var capture = File.Create(Path.Combine(root, "chapter-view.png"))) encoder.Save(capture);
            SingleChapterCheckBox.IsChecked = false;
            Require(EditorTextBox.Text == full, "Returning to whole article lost hidden text.");
        }
        finally
        {
            _editor.RevertLocalChanges();
            ClearDocumentDisplay();
            _editor = null;
            _readingWindow = null;
            _singleChapter = false;
            _updatingChapters = true;
            SingleChapterCheckBox.IsChecked = false;
            _updatingChapters = false;
            FindTextBox.Text = string.Empty;
            FindCurrentChapterCheckBox.IsChecked = false;
        }
    }
}
