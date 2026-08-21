"""What Diagram asks the model for, in Diagram's own words.

One prompt: return a title, a diagram type, and valid Mermaid, within bounds
this renderer can actually draw. The bounds are the judgement — flowchart unless
another type is asked for, short node identifiers, no HTML or click directives,
40 nodes and 80 edges — and they exist because a diagram that will not render is
worse than none.

The mechanism stays in `artifacts/diagram.py`: the JSON extraction, the reply
schema, and `validate_diagram_specification`, which refuses anything the prompt
asked for and did not get. The prompt asks; the validator decides.
"""

from backend.core.prompts import load

# Repository context and quoted source reach this model, so the last sentence is
# load-bearing rather than boilerplate: it is the only thing standing between a
# comment in someone's code and an instruction to this agent.
DIAGRAM_SYSTEM = load("diagram/system")
