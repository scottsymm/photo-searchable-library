export interface ParsedQuery {
  text: string;
  who?: string;
  place?: string;
  before?: string;
  after?: string;
  tag?: string;
}

export function parseQuery(raw: string): ParsedQuery {
  const result: ParsedQuery = { text: "" };
  const freeText: string[] = [];
  for (const token of raw.trim().split(/\s+/).filter(Boolean)) {
    const match = token.match(/^(who|place|before|after|tag):(.+)$/i);
    if (!match) {
      freeText.push(token);
      continue;
    }
    result[match[1].toLowerCase() as keyof Omit<ParsedQuery, "text">] = match[2];
  }
  result.text = freeText.join(" ");
  return result;
}
