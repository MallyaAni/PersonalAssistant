name: document/picture
used by: backend/services/document_parser.py
runs on: the Docling picture-description endpoint (DOCLING_PICTURE_API_URL)
pinned by: backend/tests/test_document_parser.py

Sent once per picture Docling finds in a converted document, with the picture
attached. The answer comes back as a caption paragraph under the picture's
placeholder, and mark_pictures turns it into a "[Picture: ...]" passage so a
citation reads as a description rather than as the document's own words.

This was the last model instruction still written inside Python. It is a
description prompt like the vision ones, so it belongs here: the wording can be
tuned without editing the parser, and the prompt-file checks catch an emptied
file or a stray separator before a document is ever uploaded.

===== PROMPT BELOW — everything under this line is sent to the model =====

Describe what this picture shows in one or two factual sentences, including any text, names, numbers, or places in it. No opinions.
