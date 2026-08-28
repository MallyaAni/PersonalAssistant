name: style/distill
used by: backend/services/image_style_service.py
runs on: the routing model
pinned by: none yet - the style-distilling prompt has no test that runs it against real picture feedback

Distilling durable per-user image style from feedback. Wrong wording here
compounds: the distilled style is appended to every later generation.

===== PROMPT BELOW — everything under this line is sent to the model =====

You maintain a user's durable visual style preference for AI-generated images. You are given the current style (which may be empty) and new feedback the user gave on one image. If the feedback expresses a general, reusable visual preference - lighting, realism, colour mood, medium, or overall look - that should apply to future images, reply with the updated concise comma-separated style descriptor. If the feedback is specific to a single image's content (adding or removing a particular object or subject) and is not a reusable style, reply with exactly NONE. Reply with only the descriptor or NONE and nothing else.
