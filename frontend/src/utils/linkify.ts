// A markdown link already in the text is left untouched; a bare URL is wrapped
// so react-markdown renders it as a tappable link. Tried in one pass so a URL
// that sits inside a markdown link's destination is never wrapped twice.
const LINK_OR_URL =
  /(\[[^\]\n]*\]\([^)\n]*\))|(https?:\/\/[^\s<>"'\u2018\u2019`]+|www\.[^\s<>"'\u2018\u2019`]+)/g

// Wrap bare URLs in markdown links, leaving existing markdown links alone.
export function linkifyMarkdown(text: string): string {
  return text.replace(LINK_OR_URL, (_match, markdownLink, url) => {
    if (markdownLink) return markdownLink
    return `[${url}](${url})`
  })
}
