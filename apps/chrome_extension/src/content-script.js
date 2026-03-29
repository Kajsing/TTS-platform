function getSelectedText() {
  const selection = window.getSelection();
  return selection ? selection.toString().trim() : "";
}

function getPageText(maxChars = 4000) {
  const bodyText = document.body?.innerText || "";
  const normalized = bodyText.replace(/\s+/g, " ").trim();
  return normalized.slice(0, maxChars);
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
