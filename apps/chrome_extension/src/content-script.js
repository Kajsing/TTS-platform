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

const HEADING_TAGS = new Set(["H1", "H2", "H3", "H4"]);

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
  return extractReadableText(anchorElement, 1000).text;
}

function getPageCapture(maxChars = 24000, startSectionIndex = 0) {
  const requestedMaxChars = sanitizeMaxChars(maxChars);
  const requestedStartSectionIndex = sanitizeSectionIndex(startSectionIndex);
  const root = pickReadableRoot();
  const extracted = extractReadableText(root, requestedMaxChars, requestedStartSectionIndex);
  if (extracted.text) {
    return buildCaptureResult(extracted.text, {
      maxChars: requestedMaxChars,
      startSectionIndex: requestedStartSectionIndex,
      source: extracted.source,
      truncated: extracted.truncated,
      readableBlocks: extracted.readableBlocks,
      structure: extracted.structure,
    });
  }
  if (requestedStartSectionIndex > 0) {
    return buildCaptureResult("", {
      maxChars: requestedMaxChars,
      startSectionIndex: requestedStartSectionIndex,
      source: extracted.source,
      truncated: false,
      readableBlocks: 0,
      structure: extracted.structure || emptyStructureSummary(),
    });
  }

  const fallbackText = normalizeInlineText(document.body?.innerText || "");
  const text = fallbackText.slice(0, requestedMaxChars).trim();
  return buildCaptureResult(text, {
    maxChars: requestedMaxChars,
    startSectionIndex: requestedStartSectionIndex,
    source: "fallback-body",
    truncated: fallbackText.length > requestedMaxChars,
    readableBlocks: 0,
    structure: emptyStructureSummary(),
  });
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

function extractReadableText(root, maxChars, startSectionIndex = 0) {
  if (!root) {
    return emptyCapture("missing-root", maxChars);
  }

  const blockEntries = [];
  const seen = new Set();
  const structure = createStructureSummary(root);
  structure.startSectionIndex = startSectionIndex;
  let truncated = false;
  let currentSectionIndex = -1;
  const candidates = root.querySelectorAll(BLOCK_SELECTORS.join(", "));
  for (const element of candidates) {
    if (shouldSkipElement(element)) {
      continue;
    }

    const blockKind = getBlockKind(element);
    const text = normalizeInlineText(element.innerText || element.textContent || "");
    if (text.length < minimumBlockLength(blockKind) || seen.has(text)) {
      continue;
    }

    if (blockKind === "heading") {
      currentSectionIndex += 1;
    }
    if (currentSectionIndex >= 0 && currentSectionIndex < startSectionIndex) {
      continue;
    }
    if (currentSectionIndex < 0 && startSectionIndex > 0) {
      continue;
    }

    blockEntries.push({
      text,
      kind: blockKind,
      sectionIndex: Math.max(currentSectionIndex, 0),
      level: getHeadingLevel(element),
    });
    seen.add(text);
    recordCapturedBlock(structure, blockKind);

    if (joinBlockEntries(blockEntries).length >= maxChars) {
      truncated = true;
      break;
    }
  }

  const joined = joinBlockEntries(blockEntries).trim();
  if (joined) {
    const text = joined.slice(0, maxChars).trim();
    structure.sections = buildCapturedSections(blockEntries, maxChars);
    return {
      text,
      source: "readable-blocks",
      truncated: truncated || joined.length > maxChars,
      readableBlocks: blockEntries.length,
      structure,
    };
  }
  const fallbackText = normalizeInlineText(root.innerText || root.textContent || "");
  return {
    text: fallbackText.slice(0, maxChars).trim(),
    source: "root-text",
    truncated: fallbackText.length > maxChars,
    readableBlocks: 0,
    structure,
  };
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

function getBlockKind(element) {
  if (isHeadingElement(element)) {
    return "heading";
  }
  if (element.tagName === "LI") {
    return "listItem";
  }
  if (element.tagName === "BLOCKQUOTE") {
    return "quote";
  }
  return "body";
}

function getHeadingLevel(element) {
  if (!isHeadingElement(element)) {
    return null;
  }
  return Number(element.tagName.slice(1));
}

function isHeadingElement(element) {
  return HEADING_TAGS.has(element.tagName);
}

function minimumBlockLength(blockKind) {
  return blockKind === "heading" ? 3 : 30;
}

function createStructureSummary(root) {
  const summary = emptyStructureSummary();
  if (!root) {
    return summary;
  }
  summary.headingCount = Array.from(root.querySelectorAll("h1, h2, h3, h4")).filter(
    (element) =>
      !shouldSkipElement(element) &&
      normalizeInlineText(element.innerText || element.textContent || "").length >= 3
  ).length;
  return summary;
}

function emptyStructureSummary() {
  return {
    headingCount: 0,
    capturedHeadingCount: 0,
    bodyBlockCount: 0,
    listItemCount: 0,
    quoteBlockCount: 0,
    startSectionIndex: 0,
    sections: [],
  };
}

function recordCapturedBlock(summary, blockKind) {
  if (blockKind === "heading") {
    summary.capturedHeadingCount += 1;
  } else if (blockKind === "listItem") {
    summary.listItemCount += 1;
  } else if (blockKind === "quote") {
    summary.quoteBlockCount += 1;
  } else {
    summary.bodyBlockCount += 1;
  }
}

function joinBlockEntries(blockEntries) {
  return blockEntries.map((entry) => entry.text).join("\n\n");
}

function buildCapturedSections(blockEntries, maxChars) {
  const sections = [];
  let textCharStart = 0;
  for (const entry of blockEntries) {
    if (entry.kind === "heading" && textCharStart < maxChars) {
      sections.push({
        index: entry.sectionIndex,
        level: entry.level,
        textCharStart,
      });
    }
    textCharStart += entry.text.length + 2;
  }
  return sections;
}

function sanitizeMaxChars(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 24000;
  }
  return Math.max(200, Math.min(48000, Math.round(parsed)));
}

function sanitizeSectionIndex(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.max(0, Math.floor(parsed));
}

function emptyCapture(source, maxChars) {
  return {
    text: "",
    source,
    truncated: false,
    readableBlocks: 0,
    maxChars,
    structure: emptyStructureSummary(),
  };
}

function buildCaptureResult(text, meta) {
  const structure = meta.structure || emptyStructureSummary();
  structure.startSectionIndex = meta.startSectionIndex || structure.startSectionIndex || 0;
  return {
    text,
    meta: {
      source: meta.source,
      textChars: text.length,
      maxChars: meta.maxChars,
      startSectionIndex: meta.startSectionIndex,
      truncated: Boolean(meta.truncated),
      readableBlocks: meta.readableBlocks,
      structure,
    },
  };
}

chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
  if (message?.type === "tts-extension:get-selection") {
    sendResponse({ text: getSelectedText() });
    return;
  }

  if (message?.type === "tts-extension:get-page-text") {
    sendResponse(getPageCapture(message.maxChars, message.startSectionIndex));
  }
});
