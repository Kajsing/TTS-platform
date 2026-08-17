# Visible layout-stable playback highlight

## Goal

Make the active sentence unambiguous without reflowing the continuous editor.

## Implementation

- Added a non-interactive WPF adorner over the existing TextBox.
- Draws a rounded yellow background and a thin underline for every visual line
  covered by the played source range.
- Uses TextBox character rectangles, so the overlay follows wrapping and
  scrolling without changing text metrics.
- Combines the overlay with WPF's low-opacity native selection so an inactive
  TextBox paints the range reliably while retaining dark text.
- Keeps the overlay fill very light; the high-contrast border and underline
  carry most of the visual emphasis without washing out glyphs.
- Returns keyboard focus from Play to the read-only TextBox while the window is
  active, because WPF otherwise suppresses the selected range despite its
  inactive-selection setting.
- Clears the playback selection and overlay when playback is no longer active.
- Centers the active range near the upper third of the viewport instead of
  accepting WPF's minimal bottom-edge `ScrollToLine` visibility.

## Scope

- No service, storage, model, voice, dependency, security, licensing, or
  deployment contract changed.

## Validation

- 100 .NET Release tests passed.
- The Release `win-x64` WPF build passed without warnings.
- Ruff, .NET formatting, and `git diff --check` passed.
- The complete Windows desktop integration check passed after the final focus,
  centering, and contrast changes.
- A live screen capture confirmed a visible pale-yellow active range with dark
  readable text and unchanged line wrapping.
