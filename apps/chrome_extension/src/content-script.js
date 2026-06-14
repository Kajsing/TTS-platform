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
  "script, style, noscript, template, nav, header, footer, aside, form, button, input, select, textarea, svg, canvas";

const HIDDEN_SUBTREE_SELECTOR = "[hidden], [inert], [aria-hidden='true']";
const BLOCK_SELECTOR_LIST = BLOCK_SELECTORS.join(", ");
const MAX_ROOT_CANDIDATE_MATCHES = 64;
const MAX_READABLE_BLOCK_MATCHES = 2500;
const MAX_STRUCTURE_HEADING_MATCHES = 1000;
const MAX_FALLBACK_TEXT_NODES = 6000;
const MAX_DOM_TRAVERSAL_NODES = 20000;

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

function getPageCapture(maxChars = 24000, startSectionIndex = 0, startTextChar = 0) {
  const requestedMaxChars = sanitizeMaxChars(maxChars);
  const requestedStartSectionIndex = sanitizeSectionIndex(startSectionIndex);
  const requestedStartTextChar = sanitizeTextCharOffset(startTextChar);
  const root = pickReadableRoot();
  const extracted = extractReadableText(
    root,
    requestedMaxChars,
    requestedStartSectionIndex,
    requestedStartTextChar
  );
  if (extracted.text) {
    return buildCaptureResult(extracted.text, {
      maxChars: requestedMaxChars,
      startSectionIndex: requestedStartSectionIndex,
      startTextChar: requestedStartTextChar,
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
      startTextChar: requestedStartTextChar,
      source: extracted.source,
      truncated: false,
      readableBlocks: 0,
      structure: extracted.structure || emptyStructureSummary(),
    });
  }

  const fallback = extractFallbackText(document.body);
  const fallbackText = fallback.text;
  const text = fallbackText
    .slice(requestedStartTextChar, requestedStartTextChar + requestedMaxChars)
    .trim();
  const structure = emptyStructureSummary();
  structure.startSectionIndex = requestedStartSectionIndex;
  structure.startTextChar = requestedStartTextChar;
  structure.traversalLimitReached = fallback.limitReached;
  structure.nextTextCharStart =
    fallback.limitReached || fallbackText.length > requestedStartTextChar + requestedMaxChars
      ? requestedStartTextChar + text.length
      : null;
  return buildCaptureResult(text, {
    maxChars: requestedMaxChars,
    startSectionIndex: requestedStartSectionIndex,
    startTextChar: requestedStartTextChar,
    source: "fallback-body",
    truncated:
      fallback.limitReached || fallbackText.length > requestedStartTextChar + requestedMaxChars,
    readableBlocks: 0,
    structure,
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
  let bestCandidate = null;
  let bestScore = 0;
  for (const selector of PRIMARY_CONTENT_SELECTORS) {
    const selection = collectMatchingElements(
      document.body || document.documentElement,
      selector,
      MAX_ROOT_CANDIDATE_MATCHES
    );
    for (const candidate of selection.elements) {
      if (shouldSkipElement(candidate)) {
        continue;
      }
      const score = scoreReadableRootCandidate(candidate);
      if (score > bestScore) {
        bestCandidate = candidate;
        bestScore = score;
      }
    }
  }
  return bestCandidate || document.body;
}

function scoreReadableRootCandidate(candidate) {
  const textLength = extractFallbackText(candidate).text.length;
  if (textLength < 200) {
    return 0;
  }
  const blockCount = collectMatchingElements(
    candidate,
    BLOCK_SELECTOR_LIST,
    MAX_READABLE_BLOCK_MATCHES
  ).elements.filter((element) => !shouldSkipElement(element)).length;
  return textLength + blockCount * 50;
}

function extractReadableText(root, maxChars, startSectionIndex = 0, startTextChar = 0) {
  if (!root) {
    return emptyCapture("missing-root", maxChars);
  }

  const blockEntries = [];
  const seen = new Set();
  const structure = createStructureSummary(root);
  structure.startSectionIndex = startSectionIndex;
  structure.startTextChar = startTextChar;
  let truncated = false;
  let captureLimitReached = false;
  let currentSectionIndex = -1;
  let textCharCursor = 0;
  const candidateSelection = collectMatchingElements(
    root,
    BLOCK_SELECTOR_LIST,
    MAX_READABLE_BLOCK_MATCHES
  );
  if (candidateSelection.limitReached) {
    truncated = true;
    structure.traversalLimitReached = true;
  }
  for (const element of candidateSelection.elements) {
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
    const separatorLength = textCharCursor > 0 ? 2 : 0;
    const blockTextStart = textCharCursor + separatorLength;
    const blockTextEnd = blockTextStart + text.length;
    textCharCursor = blockTextEnd;
    if (blockTextEnd <= startTextChar) {
      seen.add(text);
      continue;
    }
    if (captureLimitReached) {
      if (structure.nextTextCharStart == null) {
        structure.nextTextCharStart = blockTextStart;
      }
      if (blockKind === "heading") {
        structure.nextSectionIndex = currentSectionIndex;
        break;
      }
      continue;
    }

    const startOffset = Math.max(0, startTextChar - blockTextStart);
    const capturedText = text.slice(startOffset).trimStart();
    if (!capturedText) {
      seen.add(text);
      continue;
    }
    blockEntries.push({
      text: capturedText,
      kind: blockKind,
      sectionIndex: Math.max(currentSectionIndex, 0),
      level: getHeadingLevel(element),
    });
    seen.add(text);
    recordCapturedBlock(structure, blockKind);

    if (joinBlockEntries(blockEntries).length >= maxChars) {
      truncated = true;
      captureLimitReached = true;
    }
  }

  const joined = joinBlockEntries(blockEntries).trim();
  if (joined) {
    const text = joined.slice(0, maxChars).trim();
    const isTruncated = truncated || joined.length > maxChars;
    structure.sections = buildCapturedSections(blockEntries, maxChars);
    structure.nextTextCharStart = isTruncated ? startTextChar + text.length : null;
    return {
      text,
      source: "readable-blocks",
      truncated: isTruncated,
      readableBlocks: blockEntries.length,
      structure,
    };
  }
  const fallback = extractFallbackText(root);
  const fallbackText = fallback.text;
  const fallbackSlice = fallbackText.slice(startTextChar, startTextChar + maxChars).trim();
  structure.traversalLimitReached = structure.traversalLimitReached || fallback.limitReached;
  structure.nextTextCharStart =
    fallback.limitReached || fallbackText.length > startTextChar + maxChars
      ? startTextChar + fallbackSlice.length
      : null;
  return {
    text: fallbackSlice,
    source: "root-text",
    truncated: fallback.limitReached || fallbackText.length > startTextChar + maxChars,
    readableBlocks: 0,
    structure,
  };
}

function shouldSkipElement(element) {
  return (
    Boolean(element.closest(SKIP_SELECTOR)) ||
    Boolean(element.closest(HIDDEN_SUBTREE_SELECTOR)) ||
    isElementHidden(element)
  );
}

function isElementHidden(element) {
  const style = window.getComputedStyle(element);
  return style.display === "none" || style.visibility === "hidden";
}

function extractFallbackText(root) {
  if (!root) {
    return { text: "", limitReached: false };
  }
  const textParts = [];
  let visitedTextNodes = 0;
  let limitReached = false;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || shouldSkipElement(parent)) {
        return NodeFilter.FILTER_REJECT;
      }
      if (!normalizeInlineText(node.textContent || "")) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  while (walker.nextNode()) {
    visitedTextNodes += 1;
    if (visitedTextNodes > MAX_FALLBACK_TEXT_NODES) {
      limitReached = true;
      break;
    }
    const text = normalizeInlineText(walker.currentNode.textContent || "");
    if (text) {
      textParts.push(text);
    }
  }
  return {
    text: normalizeInlineText(textParts.join(" ")),
    limitReached,
  };
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
  const headingSelection = collectMatchingElements(
    root,
    "h1, h2, h3, h4",
    MAX_STRUCTURE_HEADING_MATCHES
  );
  summary.traversalLimitReached = headingSelection.limitReached;
  summary.headingCount = headingSelection.elements.filter(
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
    startTextChar: 0,
    nextTextCharStart: null,
    nextSectionIndex: null,
    sections: [],
    traversalLimitReached: false,
  };
}

function collectMatchingElements(root, selector, maxMatches) {
  const elements = [];
  let visited = 0;
  let limitReached = false;

  function maybeAddElement(element) {
    if (!element.matches(selector)) {
      return true;
    }
    if (elements.length >= maxMatches) {
      limitReached = true;
      return false;
    }
    elements.push(element);
    return true;
  }

  if (root instanceof Element && !maybeAddElement(root)) {
    return { elements, limitReached };
  }

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode(node) {
      if (shouldSkipElement(node)) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  while (walker.nextNode()) {
    visited += 1;
    if (visited > MAX_DOM_TRAVERSAL_NODES) {
      limitReached = true;
      break;
    }
    if (!maybeAddElement(walker.currentNode)) {
      break;
    }
  }
  return { elements, limitReached };
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

function sanitizeTextCharOffset(value) {
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
  structure.startTextChar = meta.startTextChar || structure.startTextChar || 0;
  return {
    text,
    meta: {
      source: meta.source,
      textChars: text.length,
      maxChars: meta.maxChars,
      startSectionIndex: meta.startSectionIndex,
      startTextChar: meta.startTextChar,
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
    sendResponse(
      getPageCapture(message.maxChars, message.startSectionIndex, message.startTextChar)
    );
  }
});
