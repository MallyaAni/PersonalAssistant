name: memory/share_in_group
used by: backend/memory/share_screen.py -> shareable (the group turn's member context)
runs on: the routing model (schema-enforcing engine), temperature 0
pinned by: functional/test_group_share_screen_behaviour.py

Which of a person's remembered statements may be said in a group chat of
their friends. The operator's decision, 2026-08-28: "non sensitive memory
data should be known automatically in group chats where all users are
approved" - their name, what they like, the everyday things they have told
the assistant. What stays theirs is the sensitive: health, money, legal
matters, relationships and sexuality, exact addresses and contact details,
credentials, work or family trouble, anything said to be private. Judged by
meaning: no keyword list separates "I drive a red Mini" from "I'm seeing a
therapist on Tuesdays". Deterministic screens (secrets, card numbers,
personal medical/financial/legal framing) run before this.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are deciding which of a person's remembered statements may be repeated by an assistant in a group text chat with that person's friends, where the person is also present. Everyday things a friend would happily hear are fine: their name, what they like and do, their pets, their car, food they enjoy or avoid, hobbies, favourite places, plans they have mentioned, the city they live in. Private is anything a person would reasonably not want an assistant announcing to their friends: health and medical matters (conditions, medication, therapy, pregnancy), money (income, debts, purchases they would not mention, financial trouble), legal matters, immigration, relationships and dating, sexuality, exact home or work addresses and contact details, passwords or account details, trouble at work or in the family, grief, anything they said was a secret or private, and anything embarrassing. When a statement mixes both, it is private. When in doubt, it is private.

Return the numbers of the private statements as "private"; an empty list means all may be repeated.
