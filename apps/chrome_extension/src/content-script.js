const PRIMARY_CONTENT_SELECTORS = [
  "article",
  "main",
  "[role='main']",
  ".article-content",
  ".entry-content",
  ".post-content",
  ".content",
];

const BLOCK_SELECTORS = [
  "h1",
  "h2",
  "h3",
  "h4",
  "p",
  "li",
  "blockquote",
  "pre",
  "figcaption",
];

const SKIP_SELECTOR =
  "script, style, noscript, nav, header, footer, aside, form, button, input, select, textarea, svg, canvas";

function getSelectedText() {
  const controlSelection = getControlSelection(document.activeElement);
  if (controlSelection) {
    return controlSelection;
  }

  const selection = window.getSelection();
  if (!selection) {
    return "";
  }

  const selectedText = normalizeInlineText(selection.toString());
  if (selectedText) {
    return selectedText;
  }

  const anchorElement = selection.anchorNode?.parentElement?.closest(
    PRIMARY_CONTENT_SELECTORS.join(", ")
  );
  if (!anchorElement) {
    return "";
  }
  return extractReadableText(anchorElement, 1000);
}

function getPageText(maxChars = 4000) {
  const root = pickReadableRoot();
  const extracted = extractReadableText(root, maxChars);
  if (extracted) {
    return extracted;
  }

  const fallbackText = normalizeInlineText(document.body?.innerText || "");
  return fallbackText.slice(0, maxChars);
}

function getControlSelection(element) {
  if (!element) {
    return "";
  }
  if (
    element instanceof HTMLTextAreaElement ||
    (element instanceof HTMLInputElement &&
      ["search", "text", "url", "tel", "password"].includes(element.type))
  ) {
    const start = element.selectionStart ?? 0;
    const end = element.selectionEnd ?? 0;
    return normalizeInlineText(element.value.slice(start, end));
  }
  return "";
}

function pickReadableRoot() {
  for (const selector of PRIMARY_CONTENT_SELECTORS) {
    const candidate = document.querySelector(selector);
    if (!candidate || isElementHidden(candidate)) {
      continue;
    }
    if (normalizeInlineText(candidate.innerText || "").length >= 200) {
      return candidate;
    }
  }
  return document.body;
}

function extractReadableText(root, maxChars) {
  if (!root) {
    return "";
  }

  const blocks = [];
  const seen = new Set();
  const candidates = root.querySelectorAll(BLOCK_SELECTORS.join(", "));
  for (const element of candidates) {
    if (shouldSkipElement(element)) {
      continue;
    }

    const text = normalizeInlineText(element.innerText || element.textContent || "");
    if (text.length < 30 || seen.has(text)) {
      continue;
    }

    blocks.push(text);
    seen.add(text);

    if (blocks.join("\n\n").length >= maxChars) {
      break;
    }
  }

  const joined = blocks.join("\n\n").trim();
  if (joined) {
    return joined.slice(0, maxChars).trim();
  }
  return normalizeInlineText(root.innerText || root.textContent || "").slice(0, maxChars);
}

function shouldSkipElement(element) {
  return Boolean(element.closest(SKIP_SELECTOR)) || isElementHidden(element);
}

function isElementHidden(element) {
  const style = window.getComputedStyle(element);
  return style.display === "none" || style.visibility === "hidden";
}

function normalizeInlineText(text) {
  return text.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
}

chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
  if (message?.type === "tts-extension:get-selection") {
    sendResponse({ text: getSelectedText() });
    return;
  }

  if (message?.type === "tts-extension:get-page-text") {
    sendResponse({ text: getPageText(message.maxChars) });
  }
});
