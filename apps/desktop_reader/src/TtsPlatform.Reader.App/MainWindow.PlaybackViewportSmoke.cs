using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    internal async Task VerifyPlaybackViewportAsync(string root)
    {
        if (!_smokeTest || _editor is not null || _playback is not null)
            throw new InvalidOperationException("Viewport smoke requires an isolated Reader.");
        var client = DispatchProxy.Create<IReaderServiceClient, DocumentSwitchSmokeClient>();
        var fake = (DocumentSwitchSmokeClient)client;
        var blocks = Enumerable.Range(0, 80).Select(index => fake.Block("first") with
        {
            Id = $"viewport-{index}",
            Ordinal = index,
            Text = $"Synthetic paragraph {index + 1}. " + string.Concat(Enumerable.Repeat(
                "A wrapped sentence keeps its layout while the reader pauses and resumes. ", 5)),
        }).ToArray();
        var document = fake.Documents[0] with { TotalBlocks = blocks.Length, TotalCharacters = blocks.Sum(b => b.Text.Length) };
        _editor = new DocumentEditor(client);
        _editor.LoadBlock(document, blocks[0]);
        _continuousDocument = new ContinuousDocumentText(blocks);
        _updatingEditor = true;
        EditorTextBox.Text = _continuousDocument.Text;
        _updatingEditor = false;
        DocumentTitleText.Text = "Synthetic pause and viewport check";
        async Task Idle()
        {
            await Dispatcher.InvokeAsync(() => UpdateLayout(), DispatcherPriority.ApplicationIdle);
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        }
        static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }
        ReaderCursor Cursor(ReaderBlock block) => new(document.Id, block.Id, block.Ordinal, 0, document.ContentRevision);
        void Highlight(ReaderBlock block) => ShowContinuousEditorHighlight(document,
            [new ReaderSourceSpan(block.Id, block.Ordinal, 0, block.Text.Length)]);
        try
        {
            UpdatePlaybackControls();
            await Idle();
            EditorTextBox.Select(20, 12);
            await Idle();
            var caretIntent = _textCursor;
            var selection = (EditorTextBox.SelectionStart, EditorTextBox.SelectionLength);
            var font = EditorTextBox.FontWeight;
            var lineHeight = TextBlock.GetLineHeight(EditorTextBox);
            FollowReadingCheckBox.IsChecked = true;
            Highlight(blocks[35]);
            await Idle();
            Require(selection == (EditorTextBox.SelectionStart, EditorTextBox.SelectionLength) && _textCursor == caretIntent,
                "An audible highlight stole the user's selection or Start-at-cursor intent.");
            Require(EditorTextBox.VerticalOffset > 500, "Viewport fixture was not scrolled into the article.");

            foreach (var state in new[] { ReaderPlaybackState.Paused, ReaderPlaybackState.Completed, ReaderPlaybackState.Faulted })
            {
                if (state == ReaderPlaybackState.Completed) { Highlight(blocks[^1]); await Idle(); }
                var offset = EditorTextBox.VerticalOffset;
                var marker = (_continuousHighlightAdorner!.HighlightStart, _continuousHighlightAdorner.HighlightLength);
                var geometry = EditorTextBox.GetRectFromCharacterIndex(marker.HighlightStart);
                EditorTextBox.IsReadOnly = true;
                Playback_StateChanged(null, new(state, document.Id, Cursor(blocks[1])));
                await Idle();
                Require(Math.Abs(EditorTextBox.VerticalOffset - offset) < 1,
                    $"{state} moved the continuous viewport.");
                Require(marker == (_continuousHighlightAdorner.HighlightStart, _continuousHighlightAdorner.HighlightLength) && marker.HighlightLength > 0,
                    $"{state} removed the audible reading marker.");
                Require(selection == (EditorTextBox.SelectionStart, EditorTextBox.SelectionLength) && _textCursor == caretIntent,
                    $"{state} overwrote the editing selection/caret.");
                Require(!EditorTextBox.IsReadOnly && EditorTextBox.FontWeight == font && TextBlock.GetLineHeight(EditorTextBox) == lineHeight &&
                    EditorTextBox.GetRectFromCharacterIndex(marker.HighlightStart) == geometry,
                    $"{state} left editing locked or changed text geometry.");
            }
            // Manual scrolling while paused is respected; incoming marks do not
            // override it when Follow reading is off.
            FollowReadingCheckBox.IsChecked = false;
            EditorTextBox.ScrollToVerticalOffset(700);
            await Idle();
            var manualOffset = EditorTextBox.VerticalOffset;
            Highlight(blocks[35]);
            await Idle();
            Require(Math.Abs(EditorTextBox.VerticalOffset - manualOffset) < 1, "Follow-off moved the viewport.");
            FollowReadingCheckBox.IsChecked = true;
            Highlight(blocks[35]);
            Playback_StateChanged(null, new(ReaderPlaybackState.Paused, document.Id, Cursor(blocks[35])));
            await Idle();
            var bitmap = new RenderTargetBitmap((int)ActualWidth, (int)ActualHeight, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(this);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var capture = File.Create(Path.Combine(root, "paused-viewport.png"))) encoder.Save(capture);

            var stoppedOffset = EditorTextBox.VerticalOffset;
            Playback_StateChanged(null, new(ReaderPlaybackState.Stopped, document.Id, Cursor(blocks[0])));
            await Idle();
            Require(_continuousHighlightAdorner!.HighlightLength == 0 && Math.Abs(EditorTextBox.VerticalOffset - stoppedOffset) < 1,
                "Explicit Stop retained a stale marker or jumped the view.");
            Highlight(blocks[35]);
            EditorTextBox.Select(0, 0);
            EditorTextBox.SelectedText = "Edit: ";
            await Idle();
            Require(_continuousHighlightAdorner.HighlightLength == 0 && _editor.HasUnsavedChanges,
                "Editing paused text kept a stale marker or failed to create a local edit.");

            // Structured/paged view must retain its own mark and selected block.
            _editor.RevertLocalChanges();
            _continuousDocument = null;
            _readingBlocks.Clear();
            foreach (var block in blocks) _readingBlocks.Add(new ReaderBlockDisplay(block));
            UpdatePlaybackControls();
            await Idle();
            var selected = _readingBlocks[35];
            selected.HighlightStart = 0;
            selected.HighlightLength = selected.Block.Text.Length;
            ReadingBlocksList.SelectedItem = selected;
            ReadingBlocksList.ScrollIntoView(selected);
            await Idle();
            var scroll = FindVisualChild<ScrollViewer>(ReadingBlocksList)!;
            var structuredOffset = scroll.VerticalOffset;
            Playback_StateChanged(null, new(ReaderPlaybackState.Paused, document.Id, Cursor(blocks[0])));
            await Idle();
            Require(ReferenceEquals(ReadingBlocksList.SelectedItem, selected) && selected.HighlightLength > 0 &&
                Math.Abs(scroll.VerticalOffset - structuredOffset) < 1, "Paused structured view moved or lost its marker.");
            ClearDocumentDisplay();
            Require(_continuousHighlightAdorner.HighlightLength == 0 && _readingBlocks.Count == 0,
                "Closing/changing articles retained a stale reading marker.");
        }
        finally
        {
            ClearDocumentDisplay();
            _editor = null;
            _readingWindow = null;
            FollowReadingCheckBox.IsChecked = true;
        }
    }
}
