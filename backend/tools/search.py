"""search_web and get_weather: the two live-data tools on the internet server.

Neither is a built-in row: both come from the MCP server with their own
schema, resolved live by the router. What lives here is the conversation's
account of them and their waiting lines. The server's own description
("Research a minimized public query with bounded free-provider policy")
describes its interface rather than the product's capability, and reading
it costs a session against that server.
"""

from .contracts import EffectContract

SEARCH_TOOL = "search_web"
WEATHER_TOOL = "get_weather"
SEARCH_CREDITS_TOOL = "search_credits"

# What each internet tool does to the world. All three are reads, so a
# dropped call may be replayed and a later step in a bounded loop may start
# one - a search with time in hand, the two quick lookups always. A search
# is keyed on its query so the same question is not bought twice in a turn.
SEARCH_CONTRACT = EffectContract(
    effect="read",
    cost="slow",
    idempotency=lambda action: " ".join(action.query.casefold().split()),
)
WEATHER_CONTRACT = EffectContract(effect="read", cost="fast")
SEARCH_CREDITS_CONTRACT = EffectContract(effect="read", cost="fast")

SEARCH_CAPABILITY: dict[str, str] = {
    "label": "Web search",
    "description": (
        "Look up current information on the web when the answer could have "
        "changed since training - news, prices, availability, schedules, or "
        "whoever currently holds a role, title, office, or record."
    ),
}

WEATHER_CAPABILITY: dict[str, str] = {
    "label": "Weather",
    "description": (
        "Check the current conditions and forecast for a place from live "
        "forecast data, for any question about weather now or in the coming "
        "days."
    ),
}

# Offered to operators only: the number is about the shared key, and the
# question "are we about to run out?" is the operator's to ask, in chat or
# from a scheduled check that messages them when it is low.
SEARCH_CREDITS_CAPABILITY: dict[str, str] = {
    "label": "Search credits",
    "description": (
        "Report how many web-search credits the shared search key has left "
        "this billing period - spent, limit, remaining - straight from the "
        "provider. For the operator asking about search usage, credits, or "
        "quota, or a scheduled check that should say something only when "
        "credits are low."
    ),
}
SEARCH_CREDITS_WAITING: tuple[str, ...] = (
    "🧾 Checking the search meter…",
    "💳 Counting the credits…",
)
SEARCH_WAITING: tuple[str, ...] = (
    "🔎 Rummaging through the internet…",
    "🌐 Asking the web nicely…",
    "🕵️ Following the trail…",
    "📡 Pinging the wider world…",
)

WEATHER_WAITING: tuple[str, ...] = (
    "🌤️ Peeking out the window…",
    "☁️ Consulting the clouds…",
    "🌡️ Reading the sky…",
)

TOOLBOX_WAITING: tuple[str, ...] = (
    "🧰 Reaching into the toolbox…",
    "🔧 Spinning up {tool}…",
    "⚙️ Putting {tool} to work…",
)
