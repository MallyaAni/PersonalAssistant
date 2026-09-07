name: locality/city
used by: backend/discovery/locality_city.py
runs on: the structured/routing role (schema-enforcing engine)
pinned by: functional/test_locality_city_behaviour.py

Completes a stored home locality with the city it actually sits in, so a
search knows which city the person means.

===== PROMPT BELOW — everything under this line is sent to the model =====

A person's home locality is stored as a label (usually a neighbourhood,
district, or small area) and a region (the broader place they wrote). The
region often names only the state or country, with no city in it. A search
built from such a locality holds the neighbourhood against a whole state, so a
listing in some other town in that state looks like it is near the person.

Your job is to return the region that should be stored beside the label so
the city is present.

- When the region already names the city — two or more comma-separated parts —
  return it unchanged.
- When the region names only a state, province, or country and the label is
  itself the city or town, return the region exactly as it was given: the
  label already carries the city.
- When the region names only a state, province, or country and the label is a
  neighbourhood, district, or small area, return the city the label sits in
  followed by the state, province, or country (for example "City, State").
- Never repeat the label in the region. The label is stored separately and
  joined to whatever you return, so returning it again duplicates the place.
- Never invent a place. Add only a real city, town, or district the label is
  known to sit in. When you are not confident the label has a real containing
  city, return the region exactly as it was given.
- Keep the answer to at most four comma-separated segments.

A wrong city is worse than none, because it anchors every future search to the
wrong place and nothing looks broken.
