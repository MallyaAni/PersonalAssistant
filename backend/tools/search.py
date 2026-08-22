"""search_web and get_weather: the two live-data tools on the internet server.

Neither is a built-in row: both come from the MCP server with their own
schema, resolved live by the router. What lives here is the conversation's
account of them and their waiting lines. The server's own description
("Research a minimized public query with bounded free-provider policy")
describes its interface rather than the product's capability, and reading
it costs a session against that server.
"""

SEARCH_TOOL = "search_web"
WEATHER_TOOL = "get_weather"

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
