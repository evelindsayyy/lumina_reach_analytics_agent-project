// The home page is a results page: what is typed in the search box marks the
// matching words in the results below it, the way a search engine does.
//
// No imports on purpose, so `node --test` runs it directly (tests_node/).

/** Words that carry no intent, so marking them would mark everything. */
const FILLER = new Set([
  "about", "does", "each", "from", "have", "into", "more", "most", "much", "only",
  "over", "should", "that", "their", "them", "there", "these", "they", "this",
  "what", "when", "where", "which", "while", "with", "would", "your",
]);

/** A term marks a word that starts with it, so "budget" marks "budgets". */
const MIN_TERM_LENGTH = 4;

export interface Segment {
  text: string;
  match: boolean;
}

/** The meaningful words of `query`, lower case, in order, once each. */
export function queryTerms(query: string): string[] {
  const words = query.toLowerCase().match(/[a-z]+/g) ?? [];
  return [...new Set(words.filter((w) => w.length >= MIN_TERM_LENGTH && !FILLER.has(w)))];
}

function matches(word: string, terms: readonly string[]): boolean {
  const lower = word.toLowerCase();
  return terms.some((term) => lower.startsWith(term));
}

/** `text` split into plain and matched pieces; joined, they are `text` again. */
export function highlightSegments(text: string, terms: readonly string[]): Segment[] {
  if (terms.length === 0) return [{ text, match: false }];
  const segments: Segment[] = [];
  for (const piece of text.split(/([A-Za-z]+)/)) {
    if (!piece) continue;
    const match = /^[A-Za-z]+$/.test(piece) && matches(piece, terms);
    const last = segments[segments.length - 1];
    if (last && last.match === match && !match) {
      last.text += piece;
    } else {
      segments.push({ text: piece, match });
    }
  }
  return segments;
}
