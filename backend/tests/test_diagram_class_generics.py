"""Passive class type syntax remains renderable without admitting active Mermaid content."""
import pytest

from backend.artifacts.diagram import validate_diagram_specification


# Normalize ordinary generic type annotations into the syntax used by the installed Mermaid renderer.
@pytest.mark.parametrize(('member','expected'),(
    ('+List<Entry> entries','+List~Entry~ entries'),
    ('+Set<Entry> getEntries()','+Set~Entry~ getEntries()'),
    ('+Map<Key, Value> values','+Map~Key, Value~ values'),
))
def test_passive_class_generic_types_preserve_identifiers_and_relationships(member,expected):
    source='classDiagram\nclass Container {\n'+member+'\n}\nclass Entry\nBase <|-- Derived'
    result=validate_diagram_specification({'title':'Generic types','source':source})
    assert result.diagram_type=='class' and expected in result.source
    assert 'Base <|-- Derived' in result.source and '<Entry>' not in result.source


# A class generic normalization cannot authorize attributes, scripts, directives, links or another diagram family.
@pytest.mark.parametrize('source',(
    'classDiagram\nclass A {\n+List<img src=x onerror=alert(1)> items\n}',
    'classDiagram\nclass A\n<script>alert(1)</script>',
    'classDiagram\nclass A {\n+List<Entry> items\n}\nclick A https://example.com',
    "classDiagram\nclass A {\n+List<Entry> items\n}\n%%{init: {'securityLevel':'loose'}}%%",
    'flowchart TD\nA[List<Entry>] --> B',
))
def test_class_generic_normalization_keeps_active_content_refusal(source):
    with pytest.raises(ValueError,match='unsupported active content'):
        validate_diagram_specification({'title':'Unsafe content','source':source})
