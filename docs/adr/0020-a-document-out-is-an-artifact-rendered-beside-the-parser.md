# 0020 - A document out is an artifact, rendered beside the parser

Date: 2026-09-02. Status: accepted.

## Context

The assistant offered a PDF of an itinerary it had composed in chat and had
no way to make one. The question was whether to make the offer true through
a Microsoft 365 integration (a Graph or Office MCP), or with what the
household already runs.

## Decision

A written document is a binary artifact of kind `document`, stored and served
exactly as a generated picture is. Word files are built in the backend from the
standard library; a PDF is that Word file printed by Gotenberg's LibreOffice
route on the desktop, next to Docling (its Chromium route cannot start under
the desktop's Docker), under the same hosting principle: bursty rendering lives where
the GPU box is, retrieval and delivery stay on the always-on Spark. Both surfaces deliver the
file through paths that already exist (the owned-artifact route; the bridge's
typed, magic-checked outbound attachment rules), extended by one kind and two
media types.

Microsoft 365 is not integrated. It would place the file in a tenant the
household does not have and needs consent and tokens for, to answer a request
that was for a file to send.

## Consequences

- A PDF asked for while the desktop is off is answered with the Word file, and
  the reply says the PDF returns with the desktop.
- The bridge's allowlist grows by two document types, each proven by its
  first bytes and capped like a picture; it remains a typed list, not a
  general file-sending endpoint.
- A document the assistant wrote can be shared back and read through the
  parse path, which is how its content is verified in the gate.
