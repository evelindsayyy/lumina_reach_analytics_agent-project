// The chat composer keeps its unsent text in localStorage, JSON-encoded by
// usehooks-ts' useLocalStorage, under this key. The home page's search box
// writes the same key, so a question typed there is waiting in the composer.

export const CHAT_DRAFT_KEY = "input";

/** Leave `text` in the chat composer. Storage can be off; then it just doesn't. */
export function saveChatDraft(text: string): void {
  try {
    window.localStorage.setItem(CHAT_DRAFT_KEY, JSON.stringify(text));
  } catch {
    // private mode or storage disabled: the chat opens with an empty box
  }
}
