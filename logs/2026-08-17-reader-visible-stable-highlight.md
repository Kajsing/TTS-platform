# Visible layout-stable playback highlight

## Goal

Make the active sentence unambiguous without reflowing the continuous editor.

## Implementation

- Added a non-interactive WPF adorner over the existing TextBox.
- Draws a rounded background, border, and thin underline for every visual line
  covered by the played source range.
- Uses TextBox character rectangles, so the overlay follows wrapping and
  scrolling without changing text metrics.
- Collapses the native playback selection to a caret so it cannot fade or
  replace glyphs, then uses a lightly translucent overlay for the pale fill,
  border, and underline.
- Does not move keyboard focus during playback; the custom overlay remains
  visible without relying on WPF's active or inactive selection rendering.
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
  readable text and unchanged line wrapping. A second reproduction using the
  user's long article confirmed that collapsing the native playback selection
  removes the washed-out and disappearing-glyph variants.
