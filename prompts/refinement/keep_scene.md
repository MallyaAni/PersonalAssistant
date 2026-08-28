name: refinement/keep_scene
used by: backend/services/image_refinement_service.py
runs on: sent to the image editor (FLUX Kontext), not a chat model
pinned by: none yet - the scene-keeping edit prompt has no test that runs the edit model on a real picture

What an edit must preserve. Wrong wording here restages the scene, which
was the original editing complaint.

===== PROMPT BELOW — everything under this line is sent to the model =====

Preserve every unmentioned subject attribute, object identity, geometry, position, camera angle, background, lighting, reflections, and composition. Do not add, remove, or move anything unless the instruction explicitly asks.
