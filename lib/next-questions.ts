// What the chat offers to ask after an answer: two or three of the example
// questions, so a visitor (an interviewer, say) never runs out of things to
// try. Deployed, every one of them replays an answer recorded from the live
// agent (lib/demo-answers.ts), so following them needs no sign-in and no budget.
//
// No imports on purpose, so `node --test` runs it directly (tests_node/).

/** The fields of an example question this needs (`SuggestedAction`). */
export interface Askable {
  render: string;
  title: string;
  label: string;
  action: string;
}

/**
 * Up to `count` examples not yet `asked` in this chat. They continue from the
 * example asked last, in the order the site lists them (after a typed
 * question, from the start), and spread over what they draw (a table, a
 * chart, a flowchart) before a kind repeats.
 */
export function nextQuestions<T extends Askable>(examples: readonly T[], asked: readonly string[], count = 3): T[] {
  const askedSet = new Set(asked.map((text) => text.trim()));
  let lastIndex = -1;
  for (let i = asked.length - 1; i >= 0 && lastIndex < 0; i--) {
    lastIndex = examples.findIndex((e) => e.action.trim() === asked[i].trim());
  }
  const start = lastIndex + 1;
  const remaining = [...examples.slice(start), ...examples.slice(0, start)].filter(
    (e) => !askedSet.has(e.action.trim()),
  );

  const picked: T[] = [];
  const kinds = new Set<string>();
  for (const example of remaining) {
    if (picked.length < count && !kinds.has(example.render)) {
      picked.push(example);
      kinds.add(example.render);
    }
  }
  for (const example of remaining) {
    if (picked.length < count && !picked.includes(example)) picked.push(example);
  }
  return picked;
}
