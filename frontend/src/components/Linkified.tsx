import React from 'react'

// Split text on URLs so each can be rendered as a link while the surrounding
// text keeps its exact whitespace (the digest previews are plain `<pre>` text,
// not markdown, so react-markdown is not used there).
const URL_IN_TEXT = /https?:\/\/[^\s<>"'\u2018\u2019`]+|www\.[^\s<>"'\u2018\u2019`]+/g

// Render text with each bare URL as a tappable link, preserving whitespace.
export default function Linkified({ text }: { text: string }) {
  const parts: React.ReactNode[] = []
  let last = 0
  let key = 0
  for (const match of text.matchAll(URL_IN_TEXT)) {
    const index = match.index ?? 0
    if (index > last) parts.push(text.slice(last, index))
    const url = match[0]
    parts.push(
      <a key={key++} href={url} target="_blank" rel="noreferrer" className="text-[#0071e3] underline">
        {url}
      </a>,
    )
    last = index + url.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}
