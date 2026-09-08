using System.Windows;
using System.Windows.Controls;
using TtsPlatform.Reader.Application;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class MainWindow
{
    private IReadOnlyList<ReaderChapter> _chapters = [];
    private ChapterSlice _chapterSlice;
    private string? _chapterDocumentId;
    private string? _selectedChapterId;
    private bool _updatingChapters;
    private bool _singleChapter;
    private (int Start, int Length)? _chapterAudibleMark;

    private ChapterSlice VisibleChapterSlice => _singleChapter && _chapters.Count > 0
        ? _chapterSlice : new(0, _continuousDocument?.Text.Length ?? 0);
    private ChapterSlice DisplayedChapterSlice => new(VisibleChapterSlice.Start,
        VisibleChapterSlice.Start + EditorTextBox.Text.Length);

    private string ExpandChapterEditor() => _continuousDocument is null ? EditorTextBox.Text :
        VisibleChapterSlice.Expand(EditorTextBox.Text, _continuousDocument.Text);

    private string ProjectWorkingChapter(string text)
    {
        if (_continuousDocument is null || !_singleChapter || _chapters.Count == 0) return text;
        var delta = text.Length - _continuousDocument.Text.Length;
        return text[_chapterSlice.Start..Math.Clamp(_chapterSlice.End + delta, _chapterSlice.Start, text.Length)];
    }

    private void RebuildChapterCatalog()
    {
        var document = _editor?.Document;
        if (!string.Equals(_chapterDocumentId, document?.Id, StringComparison.Ordinal))
        {
            _selectedChapterId = null;
            _chapterAudibleMark = null;
            _chapterDocumentId = document?.Id;
        }
        _chapters = document is not null && _continuousDocument is not null
            ? ReaderChapters.Build(document, _continuousDocument) : [];
        var selected = _chapters.FirstOrDefault(item => item.Id == _selectedChapterId) ?? _chapters.FirstOrDefault();
        _selectedChapterId = selected?.Id;
        _chapterSlice = selected?.Slice ?? default;
        _updatingChapters = true;
        ChapterComboBox.ItemsSource = _chapters;
        ChapterComboBox.SelectedItem = selected;
        _updatingChapters = false;
        ChapterToolbar.Visibility = _chapters.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private void RenderChapterEditor()
    {
        RebuildChapterCatalog();
        EditorTextBox.Text = ProjectWorkingChapter(_continuousDocument?.Text ?? string.Empty);
    }

    private bool CanChangeChapterView()
    {
        if (_editor?.HasUnsavedChanges == true || _documentReloadInProgress || _documentMutationInProgress)
        {
            FooterText.Text = "Save or revert changes before changing the chapter view.";
            return false;
        }
        return _chapters.Count > 0;
    }

    private void SelectChapter(ReaderChapter chapter, bool navigate, bool refreshFind = true)
    {
        var globalCaret = EditorTextBox.CaretIndex + VisibleChapterSlice.Start;
        var selectionStart = EditorTextBox.SelectionStart + VisibleChapterSlice.Start;
        var selectionLength = EditorTextBox.SelectionLength;
        _selectedChapterId = chapter.Id;
        _chapterSlice = chapter.Slice;
        _updatingChapters = true;
        ChapterComboBox.SelectedItem = chapter;
        _updatingChapters = false;
        if (_singleChapter)
        {
            var updating = _updatingEditor;
            _updatingEditor = true;
            EditorTextBox.Text = chapter.Slice.Text(_continuousDocument!.Text);
            EditorTextBox.CaretIndex = Math.Clamp(globalCaret - chapter.Start, 0, EditorTextBox.Text.Length);
            if (selectionLength > 0 && selectionStart >= chapter.Start && selectionStart + selectionLength <= chapter.End)
                EditorTextBox.Select(selectionStart - chapter.Start, selectionLength);
            _updatingEditor = updating;
            ApplyWordHighlights();
            RestoreChapterAudibleMark();
        }
        if (navigate) BringContinuousHighlightIntoView(chapter.Start);
        if (refreshFind) ScheduleFindRefresh();
        UpdatePlaybackControls();
    }

    private void EnsureChapterForOffset(int offset)
    {
        if (_chapters.Count == 0 || _editor?.HasUnsavedChanges == true) return;
        var chapter = ReaderChapters.At(_chapters, offset);
        if (chapter.Id != _selectedChapterId) SelectChapter(chapter, false, false);
    }

    private void RestoreChapterAudibleMark()
    {
        if (_chapterAudibleMark is not { } mark) return;
        var clipped = DisplayedChapterSlice.Clip(mark.Start, mark.Length);
        _continuousHighlightAdorner?.Show(clipped.Start, clipped.Length);
    }

    private void ChapterSelection_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_updatingChapters || ChapterComboBox.SelectedItem is not ReaderChapter chapter) return;
        if (CanChangeChapterView()) SelectChapter(chapter, true);
        else
        {
            _updatingChapters = true;
            ChapterComboBox.SelectedItem = _chapters.FirstOrDefault(item => item.Id == _selectedChapterId);
            _updatingChapters = false;
        }
    }

    private void ChapterView_Changed(object sender, RoutedEventArgs e)
    {
        if (_updatingChapters) return;
        if (!CanChangeChapterView())
        {
            _updatingChapters = true;
            SingleChapterCheckBox.IsChecked = _singleChapter;
            _updatingChapters = false;
            return;
        }
        var globalCaret = EditorTextBox.CaretIndex + VisibleChapterSlice.Start;
        var firstLine = EditorTextBox.GetFirstVisibleLineIndex();
        var globalTop = (firstLine < 0 ? 0 : EditorTextBox.GetCharacterIndexFromLineIndex(firstLine)) + VisibleChapterSlice.Start;
        var selectionStart = EditorTextBox.SelectionStart + VisibleChapterSlice.Start;
        var selectionLength = EditorTextBox.SelectionLength;
        _singleChapter = SingleChapterCheckBox.IsChecked == true;
        var chapter = _chapters.First(item => item.Id == _selectedChapterId);
        var updating = _updatingEditor;
        _updatingEditor = true;
        EditorTextBox.Text = _singleChapter ? chapter.Slice.Text(_continuousDocument!.Text) : _continuousDocument!.Text;
        EditorTextBox.CaretIndex = Math.Clamp(globalCaret - VisibleChapterSlice.Start, 0, EditorTextBox.Text.Length);
        if (selectionLength > 0 && selectionStart >= VisibleChapterSlice.Start && selectionStart + selectionLength <= VisibleChapterSlice.End)
            EditorTextBox.Select(selectionStart - VisibleChapterSlice.Start, selectionLength);
        _updatingEditor = updating;
        EditorTextBox.UpdateLayout();
        var line = EditorTextBox.GetLineIndexFromCharacterIndex(Math.Clamp(globalTop - VisibleChapterSlice.Start, 0, EditorTextBox.Text.Length));
        if (line >= 0) EditorTextBox.ScrollToLine(line);
        ApplyWordHighlights();
        RestoreChapterAudibleMark();
        ScheduleFindRefresh();
    }

    private void PreviousChapter_Click(object sender, RoutedEventArgs e) => NavigateChapter(-1);
    private void NextChapter_Click(object sender, RoutedEventArgs e) => NavigateChapter(1);
    private void NavigateChapter(int delta)
    {
        if (!CanChangeChapterView()) return;
        var index = _chapters.ToList().FindIndex(item => item.Id == _selectedChapterId);
        SelectChapter(_chapters[Math.Clamp(index + delta, 0, _chapters.Count - 1)], true);
    }

    private async void AddChapter_Click(object sender, RoutedEventArgs e) => await MutateChapterAsync("add");
    private async void RenameChapter_Click(object sender, RoutedEventArgs e) => await MutateChapterAsync("rename");
    private async void MergeChapter_Click(object sender, RoutedEventArgs e) => await MutateChapterAsync("merge");

    private async Task MutateChapterAsync(string action)
    {
        if (_editor?.Document is not { IsEditable: true } document || _continuousDocument is null ||
            _editor.HasUnsavedChanges || _playback?.IsActive == true || _ephemeralPlaying ||
            _documentReloadInProgress || _documentMutationInProgress) return;
        var selected = _chapters.FirstOrDefault(item => item.Id == _selectedChapterId);
        if (selected is null) return;
        var offset = EditorTextBox.CaretIndex + VisibleChapterSlice.Start;
        var cursor = _continuousDocument.CursorAt(document.Id, document.ContentRevision, offset);
        string? title = null;
        if (action != "merge")
        {
            var dialog = new RenameDocumentDialog(action == "add" ? $"Chapter {_chapters.Count + 1}" : selected.Title, chapter: true)
            { Owner = this, Title = action == "add" ? "New chapter at cursor" : "Rename chapter" };
            if (dialog.ShowDialog() != true) return;
            title = dialog.NewTitle;
        }
        else if (selected == _chapters[0] || MessageBox.Show(this,
            "Remove this chapter boundary and join it to the previous chapter? No text will be deleted. You can Undo this change.",
            "Merge chapters", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        _documentMutationInProgress = true;
        UpdateEditorButtons();
        UpdatePlaybackControls();
        try
        {
            var response = await GetClient().EditChapterAsync(document.Id, new EditChapterRequest(
                document.RowVersion, action, selected.Id, title, cursor.BlockId, cursor.CharacterOffset));
            _chapterAudibleMark = null;
            await _documentLoadLock.WaitAsync();
            try
            {
                _documentReloadInProgress = true;
                await LoadDocumentCoreAsync(response.Document, ++_documentLoadGeneration);
            }
            finally
            {
                _documentReloadInProgress = false;
                _documentLoadLock.Release();
            }
            if (_chapters.Count > 0) SelectChapter(ReaderChapters.At(_chapters, offset), false);
            var updating = _updatingEditor;
            _updatingEditor = true;
            EditorTextBox.CaretIndex = Math.Clamp(offset - VisibleChapterSlice.Start, 0, EditorTextBox.Text.Length);
            _updatingEditor = updating;
            UpdateTextCursorFromContinuousEditor();
            FooterText.Text = "Chapter change saved. Text is unchanged; Undo is available.";
        }
        catch (Exception error) when (error is ReaderApiException or ReaderServiceUnavailableException or ReaderTokenUnavailableException or NotSupportedException)
        { FooterText.Text = $"Chapter change: {error.Message}"; }
        finally { _documentMutationInProgress = false; UpdatePlaybackControls(); UpdateEditorButtons(); }
    }

    private void UpdateChapterControls(bool documentBusy, bool documentActive)
    {
        if (ChapterToolbar is null) return;
        var editable = _chapters.Count > 0 && _editor?.Document?.IsEditable == true &&
            _editor.HasUnsavedChanges != true && !documentBusy && !documentActive && !_ephemeralPlaying;
        AddChapterMenuItem.IsEnabled = editable;
        RenameChapterMenuItem.IsEnabled = editable;
        MergeChapterMenuItem.IsEnabled = editable && _selectedChapterId != _chapters.FirstOrDefault()?.Id;
        ChapterToolbar.IsEnabled = !documentBusy;
        FindCurrentChapterCheckBox.IsEnabled = _chapters.Count > 0;
    }
}
