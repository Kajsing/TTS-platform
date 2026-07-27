using System.Collections.ObjectModel;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
using TtsPlatform.Reader.Client;

namespace TtsPlatform.Reader.App;

public partial class RuleEditorDialog : Window
{
    private const int MaximumImportBytes = 1_048_576;
    private readonly IReaderServiceClient _client;
    private readonly string? _initialSelection;
    private readonly ObservableCollection<ReaderRuleSet> _ruleSets = [];
    private readonly ObservableCollection<ReaderRule> _rules = [];
    private ReaderRuleSet? _selectedRuleSet;
    private ReaderRule? _selectedRule;
    private string? _warningRuleId;
    private bool _busy;

    public RuleEditorDialog(
        IReaderServiceClient client,
        string? initialSelection = null,
        string? initialLanguage = null,
        string? initialDocumentId = null)
    {
        _client = client;
        _initialSelection = string.IsNullOrWhiteSpace(initialSelection) ? null : initialSelection;
        InitializeComponent();
        RuleSetsList.ItemsSource = _ruleSets;
        RulesList.ItemsSource = _rules;
        Loaded += RuleEditorDialog_Loaded;
        LanguageTextBox.Text = initialLanguage ?? string.Empty;
        DocumentTextBox.Text = initialDocumentId ?? string.Empty;
    }

    private async void RuleEditorDialog_Loaded(object sender, RoutedEventArgs e)
    {
        if (_initialSelection is not null)
        {
            PatternTextBox.Text = _initialSelection;
            PreviewInputTextBox.Text = _initialSelection;
            RuleNameTextBox.Text = "Selection rule";
        }
        await ReloadRuleSetsAsync();
    }

    private async Task ReloadRuleSetsAsync(string? selectId = null)
    {
        if (_busy)
        {
            return;
        }
        SetBusy(true, "Loading speech rules…");
        try
        {
            var page = await _client.GetRuleSetsAsync();
            _ruleSets.Clear();
            foreach (var ruleSet in page.RuleSets)
            {
                _ruleSets.Add(ruleSet);
            }
            RuleSetsList.SelectedItem = _ruleSets.FirstOrDefault(item =>
                string.Equals(item.Id, selectId, StringComparison.Ordinal)) ?? _ruleSets.FirstOrDefault();
            StatusText.Text = $"{_ruleSets.Count} rule set(s), rules version {page.RulesVersion}.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Speech rules: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task ReloadRulesAsync(string? selectId = null)
    {
        _rules.Clear();
        _selectedRule = null;
        if (_selectedRuleSet is null)
        {
            return;
        }

        SetBusy(true, "Loading rules…");
        try
        {
            var page = await _client.GetRulesAsync(_selectedRuleSet.Id);
            foreach (var rule in page.Rules)
            {
                _rules.Add(rule);
            }
            RulesList.SelectedItem = _rules.FirstOrDefault(item =>
                string.Equals(item.Id, selectId, StringComparison.Ordinal));
            StatusText.Text = $"{_rules.Count} rule(s) in {_selectedRuleSet.Name}.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Speech rules: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void RuleSetsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _selectedRuleSet = RuleSetsList.SelectedItem as ReaderRuleSet;
        if (_selectedRuleSet is null)
        {
            return;
        }
        RuleSetNameTextBox.Text = _selectedRuleSet.Name;
        RuleSetDescriptionTextBox.Text = _selectedRuleSet.Description;
        RuleSetEnabledCheckBox.IsChecked = _selectedRuleSet.Enabled;
        SelectTag(ScopeComboBox, _selectedRuleSet.Scope);
        await ReloadRulesAsync();
    }

    private void RulesList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _selectedRule = RulesList.SelectedItem as ReaderRule;
        if (_selectedRule is null)
        {
            return;
        }
        RuleNameTextBox.Text = _selectedRule.Name;
        RuleEnabledCheckBox.IsChecked = _selectedRule.Enabled;
        PatternTextBox.Text = _selectedRule.Pattern;
        ReplacementTextBox.Text = _selectedRule.Replacement;
        CaseSensitiveCheckBox.IsChecked = _selectedRule.CaseSensitive;
        WholeWordCheckBox.IsChecked = _selectedRule.WholeWord;
        LanguageTextBox.Text = _selectedRule.LanguageFilter ?? string.Empty;
        EngineTextBox.Text = _selectedRule.EngineFilter ?? string.Empty;
        VoiceTextBox.Text = _selectedRule.VoiceFilter ?? string.Empty;
        DocumentTextBox.Text = _selectedRule.DocumentFilter ?? string.Empty;
        PriorityTextBox.Text = _selectedRule.Priority.ToString(System.Globalization.CultureInfo.InvariantCulture);
        TimeoutTextBox.Text = _selectedRule.RegexTimeoutMs.ToString(System.Globalization.CultureInfo.InvariantCulture);
        SelectTag(StageComboBox, _selectedRule.Stage);
        SelectTag(TypeComboBox, _selectedRule.RuleType);
    }

    private void NewRuleSetButton_Click(object sender, RoutedEventArgs e)
    {
        RuleSetsList.SelectedItem = null;
        _selectedRuleSet = null;
        _rules.Clear();
        RuleSetNameTextBox.Text = string.Empty;
        RuleSetDescriptionTextBox.Text = string.Empty;
        RuleSetEnabledCheckBox.IsChecked = true;
        SelectTag(ScopeComboBox, "global");
        StatusText.Text = "Enter a name and save the new rule set.";
    }

    private async void SaveRuleSetButton_Click(object sender, RoutedEventArgs e)
    {
        var name = RuleSetNameTextBox.Text.Trim();
        if (name.Length == 0)
        {
            StatusText.Text = "A rule set name is required.";
            return;
        }

        SetBusy(true, "Saving rule set…");
        try
        {
            var request = new CreateRuleSetRequest(
                name,
                RuleSetDescriptionTextBox.Text.Trim(),
                SelectedTag(ScopeComboBox));
            ReaderRuleSet saved;
            if (_selectedRuleSet is null)
            {
                saved = await _client.CreateRuleSetAsync(request);
            }
            else
            {
                var latest = await LatestRuleSetAsync(_selectedRuleSet.Id);
                saved = await _client.UpdateRuleSetAsync(
                    latest.Id,
                    request,
                    RuleSetEnabledCheckBox.IsChecked == true,
                    latest.RowVersion);
            }
            await ReloadRuleSetsAfterBusyAsync(saved.Id);
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Save rule set: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void DeleteRuleSetButton_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedRuleSet is null)
        {
            StatusText.Text = "Select a rule set to delete.";
            return;
        }
        if (MessageBox.Show(
                this,
                $"Delete '{_selectedRuleSet.Name}' and all of its rules?",
                "Delete speech rule set",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
        {
            return;
        }

        SetBusy(true, "Deleting rule set…");
        try
        {
            var latest = await LatestRuleSetAsync(_selectedRuleSet.Id);
            await _client.DeleteRuleSetAsync(latest.Id, latest.RowVersion);
            _selectedRuleSet = null;
            _rules.Clear();
            await ReloadRuleSetsAfterBusyAsync(string.Empty);
            StatusText.Text = "Rule set deleted.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Delete rule set: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void NewRuleButton_Click(object sender, RoutedEventArgs e)
    {
        RulesList.SelectedItem = null;
        _selectedRule = null;
        RuleNameTextBox.Text = _initialSelection is null ? string.Empty : "Selection rule";
        PatternTextBox.Text = _initialSelection ?? string.Empty;
        ReplacementTextBox.Text = string.Empty;
        RuleEnabledCheckBox.IsChecked = true;
        CaseSensitiveCheckBox.IsChecked = false;
        WholeWordCheckBox.IsChecked = false;
        LanguageTextBox.Text = string.Empty;
        EngineTextBox.Text = string.Empty;
        VoiceTextBox.Text = string.Empty;
        DocumentTextBox.Text = string.Empty;
        PriorityTextBox.Text = "100";
        TimeoutTextBox.Text = "25";
        SelectTag(StageComboBox, "pronunciation");
        SelectTag(TypeComboBox, "literal_replace");
        StatusText.Text = _selectedRuleSet is null
            ? "Create or select a rule set first."
            : "Enter the rule details and save.";
    }

    private async void SaveRuleButton_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedRuleSet is null)
        {
            StatusText.Text = "Select a rule set before saving a rule.";
            return;
        }
        if (!TryBuildRuleRequest(out var request, out var error))
        {
            StatusText.Text = error;
            return;
        }

        SetBusy(true, "Saving rule…");
        try
        {
            var saved = _selectedRule is null
                ? await _client.CreateRuleAsync(_selectedRuleSet.Id, request!)
                : await _client.UpdateRuleAsync(_selectedRule.Id, request!, _selectedRule.RowVersion);
            await ReloadRulesAfterBusyAsync(saved.Id);
            StatusText.Text = $"Saved {saved.Name}.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Save rule: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void DeleteRuleButton_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedRule is null || _selectedRuleSet is null)
        {
            StatusText.Text = "Select a rule to delete.";
            return;
        }
        if (MessageBox.Show(
                this,
                $"Delete '{_selectedRule.Name}'?",
                "Delete speech rule",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
        {
            return;
        }

        SetBusy(true, "Deleting rule…");
        try
        {
            await _client.DeleteRuleAsync(_selectedRule.Id, _selectedRule.RowVersion);
            await ReloadRulesAfterBusyAsync();
            StatusText.Text = "Rule deleted.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Delete rule: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void PreviewButton_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedRuleSet is null)
        {
            StatusText.Text = "Select a rule set to preview.";
            return;
        }
        if (string.IsNullOrEmpty(PreviewInputTextBox.Text))
        {
            StatusText.Text = "Enter preview text first.";
            return;
        }

        SetBusy(true, "Evaluating preview…");
        try
        {
            var preview = await _client.PreviewRulesAsync(new RulePreviewRequest(
                PreviewInputTextBox.Text,
                [_selectedRuleSet.Id],
                EmptyToNull(LanguageTextBox.Text)));
            var report = new StringBuilder(preview.SpokenText);
            report.AppendLine().AppendLine();
            report.AppendLine($"Source spans: {preview.SourceSpans.Count}; elapsed: {preview.ElapsedMs:N2} ms; rules version: {preview.RulesVersion}");
            foreach (var trace in preview.Trace)
            {
                var name = _rules.FirstOrDefault(item => item.Id == trace.RuleId)?.Name ?? trace.RuleId;
                report.AppendLine($"Applied {name} ({trace.RuleType}) at {trace.StartOffset}–{trace.EndOffset}; output {trace.ReplacementLength} character(s).");
            }
            foreach (var warning in preview.Warnings)
            {
                report.AppendLine($"Warning: {warning.Message} [{warning.Code}]");
            }
            PreviewResultTextBox.Text = report.ToString().TrimEnd();
            _warningRuleId = preview.Warnings.FirstOrDefault(item => !string.IsNullOrWhiteSpace(item.RuleId))?.RuleId;
            DisableWarningRuleButton.IsEnabled = _warningRuleId is not null;
            StatusText.Text = $"Preview completed with {preview.Trace.Count} match(es) and {preview.Warnings.Count} warning(s).";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Rule preview: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void DisableWarningRuleButton_Click(object sender, RoutedEventArgs e)
    {
        var rule = _rules.FirstOrDefault(item => item.Id == _warningRuleId);
        if (rule is null)
        {
            StatusText.Text = "The warned rule is not in the selected rule set.";
            return;
        }

        SetBusy(true, "Disabling rule…");
        try
        {
            var request = RequestFrom(rule) with { Enabled = false };
            var saved = await _client.UpdateRuleAsync(rule.Id, request, rule.RowVersion);
            _warningRuleId = null;
            DisableWarningRuleButton.IsEnabled = false;
            await ReloadRulesAfterBusyAsync(saved.Id);
            StatusText.Text = $"Disabled {saved.Name}.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Disable rule: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void ImportButton_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedRuleSet is null)
        {
            StatusText.Text = "Select a target rule set before importing.";
            return;
        }
        var picker = new OpenFileDialog
        {
            Title = "Import Reader speech rules",
            Filter = "Reader rule sets (*.json)|*.json|All files (*.*)|*.*",
            CheckFileExists = true,
        };
        if (picker.ShowDialog(this) != true)
        {
            return;
        }

        SetBusy(true, "Checking rule import…");
        try
        {
            var file = new FileInfo(picker.FileName);
            if (file.Length > MaximumImportBytes)
            {
                throw new IOException("Rule imports are limited to 1 MiB.");
            }
            var content = await File.ReadAllTextAsync(picker.FileName);
            var preview = await _client.ImportRulesAsync(_selectedRuleSet.Id, content, commit: false);
            var message = ImportMessage(preview) + "\n\nImport these records?";
            if (MessageBox.Show(this, message, "Import speech rules", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
            {
                StatusText.Text = "Rule import cancelled after preview.";
                return;
            }
            var report = await _client.ImportRulesAsync(_selectedRuleSet.Id, content, commit: true);
            await ReloadRulesAfterBusyAsync();
            StatusText.Text = ImportMessage(report);
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Import rules: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void ExportButton_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedRuleSet is null)
        {
            StatusText.Text = "Select a rule set to export.";
            return;
        }
        var picker = new SaveFileDialog
        {
            Title = "Export Reader speech rules",
            Filter = "Reader rule sets (*.json)|*.json",
            FileName = SafeFileName(_selectedRuleSet.Name) + ".reader-rules.json",
            AddExtension = true,
        };
        if (picker.ShowDialog(this) != true)
        {
            return;
        }

        SetBusy(true, "Exporting rule set…");
        try
        {
            var content = await _client.ExportRuleSetAsync(_selectedRuleSet.Id);
            await File.WriteAllBytesAsync(picker.FileName, content);
            StatusText.Text = $"Exported {_selectedRuleSet.Name}.";
        }
        catch (Exception exception) when (IsExpected(exception))
        {
            StatusText.Text = $"Export rules: {exception.Message}";
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();

    private bool TryBuildRuleRequest(out SaveRuleRequest? request, out string error)
    {
        request = null;
        error = string.Empty;
        var name = RuleNameTextBox.Text.Trim();
        var pattern = PatternTextBox.Text;
        if (name.Length == 0 || pattern.Length == 0)
        {
            error = "A rule name and match pattern are required.";
            return false;
        }
        if (!int.TryParse(PriorityTextBox.Text, out var priority) || priority is < -100_000 or > 100_000)
        {
            error = "Priority must be an integer from -100000 through 100000.";
            return false;
        }
        if (!int.TryParse(TimeoutTextBox.Text, out var timeout) || timeout is < 1 or > 1_000)
        {
            error = "Regex timeout must be an integer from 1 through 1000 milliseconds.";
            return false;
        }
        request = new SaveRuleRequest(
            name,
            SelectedTag(StageComboBox),
            SelectedTag(TypeComboBox),
            pattern,
            ReplacementTextBox.Text,
            RuleEnabledCheckBox.IsChecked == true,
            CaseSensitiveCheckBox.IsChecked == true,
            WholeWordCheckBox.IsChecked == true,
            EmptyToNull(LanguageTextBox.Text),
            EmptyToNull(EngineTextBox.Text),
            EmptyToNull(VoiceTextBox.Text),
            EmptyToNull(DocumentTextBox.Text),
            Priority: priority,
            RegexTimeoutMs: timeout);
        return true;
    }

    private async Task ReloadRuleSetsAfterBusyAsync(string selectId)
    {
        _busy = false;
        await ReloadRuleSetsAsync(selectId);
        _busy = true;
    }

    private async Task<ReaderRuleSet> LatestRuleSetAsync(string ruleSetId)
    {
        var page = await _client.GetRuleSetsAsync();
        return page.RuleSets.FirstOrDefault(item => item.Id == ruleSetId)
            ?? throw new InvalidOperationException("The selected rule set no longer exists.");
    }

    private async Task ReloadRulesAfterBusyAsync(string? selectId = null)
    {
        _busy = false;
        await ReloadRulesAsync(selectId);
        _busy = true;
    }

    private void SetBusy(bool busy, string? message = null)
    {
        _busy = busy;
        if (message is not null)
        {
            StatusText.Text = message;
        }
    }

    private static SaveRuleRequest RequestFrom(ReaderRule rule) => new(
        rule.Name,
        rule.Stage,
        rule.RuleType,
        rule.Pattern,
        rule.Replacement,
        rule.Enabled,
        rule.CaseSensitive,
        rule.WholeWord,
        rule.LanguageFilter,
        rule.EngineFilter,
        rule.VoiceFilter,
        rule.DocumentFilter,
        rule.Priority,
        rule.RegexTimeoutMs);

    private static string ImportMessage(ReaderRuleImportReport report) =>
        $"Imported: {report.Imported}; disabled: {report.Disabled}; duplicates: {report.Duplicate}; " +
        $"invalid: {report.Invalid}; unsupported: {report.Unsupported}." +
        (report.Idempotent ? " This file was already imported." : string.Empty);

    private static string SafeFileName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var result = new string(value.Select(character => invalid.Contains(character) ? '_' : character).ToArray());
        return string.IsNullOrWhiteSpace(result) ? "speech-rules" : result;
    }

    private static string SelectedTag(ComboBox comboBox) =>
        (comboBox.SelectedItem as ComboBoxItem)?.Tag?.ToString()
        ?? throw new InvalidOperationException("A rule option must be selected.");

    private static void SelectTag(ComboBox comboBox, string tag)
    {
        comboBox.SelectedItem = comboBox.Items.OfType<ComboBoxItem>().FirstOrDefault(item =>
            string.Equals(item.Tag?.ToString(), tag, StringComparison.Ordinal));
    }

    private static string? EmptyToNull(string value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static bool IsExpected(Exception exception) => exception is
        IOException or UnauthorizedAccessException or ReaderApiException or
        ReaderServiceUnavailableException or InvalidOperationException;
}
