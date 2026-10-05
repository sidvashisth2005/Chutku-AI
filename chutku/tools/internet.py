"""Read-only internet information: weather, news, web results, page text, YouTube.

Mark LIV answers these through the Gemini cloud; Chutku fetches free, keyless public
sources directly and lets the local model summarise. Everything fetched is untrusted
data (tainting later data changes). Requests go only to public http(s) hosts: loopback,
private and link-local addresses are refused after DNS resolution and on every redirect,
so a page can never make Chutku call its own dashboard or the home network.
"""
from __future__ import annotations

from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_BYTES = 3_000_000
TIMEOUT = 12
PAGE_CHARS = 6000


class Blocked(ValueError):
    pass


def _is_public(address):
    ip = ipaddress.ip_address(address.split("%")[0])
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified)


def public_address(host):
    """Resolve host once; every address must be public. Returns the address to connect to."""
    try:
        addresses = [info[4][0] for info in socket.getaddrinfo(host, None)]
    except socket.gaierror as error:
        raise OSError(f"Could not find {host} (offline?).") from error
    if not addresses or not all(_is_public(address) for address in addresses):
        raise Blocked(f"{host} points to a local or private address; Chutku only reads public websites.")
    return addresses[0]


def check_public_url(url):
    from chutku.tools.everyday import validate_url
    validate_url(url)
    public_address(urllib.parse.urlsplit(url).hostname)
    return url


# The connection goes to the very address that was checked (resolved once, inside connect), so a name that
# answers differently a moment later (DNS rebinding) cannot point a fetch at this PC or the home network.
class _PinnedHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.create_connection((public_address(self.host), self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = socket.create_connection((public_address(self.host), self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=ssl.create_default_context())


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, *, accept="text/html,application/json,application/xml;q=0.9,*/*;q=0.5"):
    check_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirects, _PinnedHTTP, _PinnedHTTPS)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                                   "Accept-Language": "en-IN,en;q=0.8"})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body = _read_bounded(response, time.monotonic() + TIMEOUT * 2)
            final = response.geturl()
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as error:
        raise OSError(f"The site answered HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        raise OSError("The site could not be reached (offline or slow).") from error
    if len(body) > MAX_BYTES:
        body = body[:MAX_BYTES]
    return body.decode(charset, "replace"), final


def _read_bounded(response, deadline):
    """At most MAX_BYTES + 1, and within a total deadline: a server dripping bytes cannot hold Chutku."""
    chunks, size = [], 0
    while size <= MAX_BYTES:
        if time.monotonic() > deadline:
            raise TimeoutError("The page took too long to download.")
        chunk = response.read(min(65536, MAX_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title" and not self.title:  # the page title, not SVG icon titles
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html):
    parser = _Text()
    parser.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return parser.title.strip(), text


# -- tools --------------------------------------------------------------------------

def _validate(required, optional=()):
    def check(arguments):
        if set(arguments) - set(required) - set(optional) or any(k not in arguments for k in required):
            raise ValueError("Unexpected or missing arguments.")
        for key, value in arguments.items():
            if not isinstance(value, (str, int)) or (isinstance(value, str) and not 1 <= len(value.strip()) <= 300):
                raise ValueError(f"{key} must be 1-300 characters.")
    return check


def _read(arguments, _context):
    try:
        html, final = fetch(arguments["url"])
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    title, text = html_to_text(html)
    if not text:
        return ToolResult({"error": "The page had no readable text (it may need a real browser)."}, Verification.FAIL)
    output = {"url": final, "title": title[:200], "text": text[:PAGE_CHARS], "truncated": len(text) > PAGE_CHARS,
              "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS, {"url": final, "characters": len(text), "text": "[REDACTED]"})


def search_results(query, count=6):
    q = urllib.parse.quote_plus(query)
    results = []
    try:
        html, _ = fetch(f"https://lite.duckduckgo.com/lite/?q={q}")
        links = re.findall(r"<a rel=\"nofollow\" href=\"([^\"]+)\" class='result-link'>(.*?)</a>", html, re.S)
        snippets = re.findall(r"<td class='result-snippet'>(.*?)</td>", html, re.S)
        for index, (href, title) in enumerate(links):
            target = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("uddg", [href])[0]
            results.append({"title": html_to_text(title)[1], "url": target,
                            "snippet": html_to_text(snippets[index])[1] if index < len(snippets) else ""})
        source = "duckduckgo"
    except OSError:
        results = []
    if not results:
        html, _ = fetch(f"https://www.bing.com/search?q={q}&setlang=en")
        for href, title in re.findall(r"<h2[^>]*><a[^>]+href=\"(https?://[^\"]+)\"[^>]*>(.*?)</a>", html, re.S):
            results.append({"title": html_to_text(title)[1], "url": href, "snippet": ""})
        source = "bing"
    return [r for r in results if r["url"].startswith(("http://", "https://"))][:count], source


def _results(arguments, _context):
    try:
        results, source = search_results(arguments["query"], int(arguments.get("count", 6)))
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    if not results:
        return ToolResult({"error": "No results were found."}, Verification.FAIL)
    output = {"query": arguments["query"], "source": source, "results": results, "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS, {"query": "[REDACTED]", "count": len(results)})


def _news(arguments, _context):
    topic = arguments.get("topic", "").strip()
    base = "https://news.google.com/rss"
    url = (f"{base}/search?q={urllib.parse.quote_plus(topic)}&hl=en-IN&gl=IN&ceid=IN:en" if topic
           else f"{base}?hl=en-IN&gl=IN&ceid=IN:en")
    try:
        xml, _ = fetch(url, accept="application/rss+xml,application/xml")
        root = ET.fromstring(xml)
    except (OSError, ValueError, ET.ParseError) as error:
        return ToolResult({"error": f"News could not be loaded: {error}"}, Verification.FAIL)
    items = []
    for item in root.iter("item"):
        items.append({"title": (item.findtext("title") or "").strip(), "source": (item.findtext("source") or "").strip(),
                      "published": (item.findtext("pubDate") or "").strip(), "url": (item.findtext("link") or "").strip()})
        if len(items) >= int(arguments.get("count", 8)):
            break
    if not items:
        return ToolResult({"error": "No news items were found."}, Verification.FAIL)
    output = {"topic": topic or "top stories", "headlines": items, "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS, {"topic": topic or "top", "count": len(items)})


_WEATHER_CODES = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
                  51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
                  65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow",
                  75: "heavy snow", 80: "rain showers", 81: "heavy rain showers", 82: "violent rain showers",
                  95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail"}


def _weather(arguments, context):
    city = (arguments.get("city") or "").strip()
    if not city and context.memory is not None:
        for key in ("city", "home_city", "my_city", "location"):
            saved = context.memory.get(key)
            if saved:
                city = saved["value"]
                break
    if not city:
        return ToolResult({"error": "Which city? Say it, or save it once: 'remember city = Delhi'."}, Verification.FAIL)
    try:
        geo = json.loads(fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name="
                               + urllib.parse.quote(city))[0])
        place = (geo.get("results") or [None])[0]
        words = city.split()
        while place is None and len(words) > 1:  # "Delhi right" -> "Delhi"
            words = words[:-1]
            geo = json.loads(fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name="
                                   + urllib.parse.quote(" ".join(words)))[0])
            place = (geo.get("results") or [None])[0]
        if place is None:
            return ToolResult({"error": f"Could not find a place called {city}."}, Verification.FAIL)
        forecast = json.loads(fetch(
            "https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=3"
            f"&latitude={place['latitude']}&longitude={place['longitude']}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code")[0])
    except (OSError, ValueError, KeyError, TypeError) as error:
        return ToolResult({"error": f"Weather could not be loaded: {error}"}, Verification.FAIL)
    current, daily = forecast.get("current", {}), forecast.get("daily", {})
    days = [{"date": daily["time"][i], "max_c": daily["temperature_2m_max"][i], "min_c": daily["temperature_2m_min"][i],
             "rain_chance_percent": daily["precipitation_probability_max"][i],
             "sky": _WEATHER_CODES.get(daily["weather_code"][i], "unknown")} for i in range(len(daily.get("time", [])))]
    output = {"place": f"{place['name']}, {place.get('admin1', '')}, {place.get('country', '')}".replace(", ,", ","),
              "now": {"temperature_c": current.get("temperature_2m"), "feels_like_c": current.get("apparent_temperature"),
                      "humidity_percent": current.get("relative_humidity_2m"), "wind_kmh": current.get("wind_speed_10m"),
                      "sky": _WEATHER_CODES.get(current.get("weather_code"), "unknown")},
              "next_days": days, "source": "open-meteo.com"}
    ok = isinstance(output["now"]["temperature_c"], (int, float))
    return ToolResult(output, Verification.PASS if ok else Verification.FAIL)


def _youtube_play(arguments, _context):
    from chutku.tools.everyday import _open_url
    try:
        html, _ = fetch("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(arguments["query"]))
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    ids = re.findall(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html) or re.findall(r'"videoId":"([\w-]{11})"', html)
    if not ids:
        return ToolResult({"error": "No playable video was found for that search."}, Verification.FAIL)
    title = re.search(r'"videoId":"' + re.escape(ids[0]) + r'".{0,600}?"title":\{"runs":\[\{"text":"(.*?)"\}', html, re.S)
    result = _open_url(f"https://www.youtube.com/watch?v={ids[0]}", arguments.get("browser"), arguments.get("tab", "auto"))
    output = dict(result.output) | {"video_title": title.group(1)[:150] if title else None, "video_id": ids[0]}
    return ToolResult(output, result.verification, result.audit_output)


def register_internet_tools(registry):
    net = dict(required_capability="internet.read", network_egress=True)
    registry.register(Tool("web.read", "Read the text of a public web page (for answering questions about it).",
        Risk.OBSERVATION, _read, _validate(["url"]), reversibility="not_applicable",
        argument_schema={"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}},
                         "required": ["url"], "additionalProperties": False},
        success_predicate="public_page_text_read", **net))
    registry.register(Tool("web.results", "Get web search results (title, link, snippet) to answer a question, "
        "compare things or check prices; read a result with web.read for detail.",
        Risk.OBSERVATION, _results, _validate(["query"], ["count"]), reversibility="not_applicable",
        argument_schema={"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300},
                                                          "count": {"type": "integer", "minimum": 1, "maximum": 10}},
                         "required": ["query"], "additionalProperties": False},
        success_predicate="search_results_returned", **net))
    registry.register(Tool("web.news", "Latest news headlines, optionally about a topic.",
        Risk.OBSERVATION, _news, _validate([], ["topic", "count"]), reversibility="not_applicable",
        argument_schema={"type": "object", "properties": {"topic": {"type": "string", "maxLength": 300},
                                                          "count": {"type": "integer", "minimum": 1, "maximum": 15}},
                         "additionalProperties": False},
        success_predicate="headlines_returned", **net))
    registry.register(Tool("web.weather", "Current weather and 3-day forecast for a city (uses the saved 'city' "
        "memory if no city is given).",
        Risk.OBSERVATION, _weather, _validate([], ["city"]), reversibility="not_applicable",
        argument_schema={"type": "object", "properties": {"city": {"type": "string", "maxLength": 100}},
                         "additionalProperties": False},
        success_predicate="current_temperature_returned", **net))
    from chutku.tools.everyday import _window_verifier
    registry.register(Tool("youtube.play", "Play the top YouTube video for a search in the owner's browser (or "
        "browser=brave/chrome/edge/firefox).",
        Risk.REVERSIBLE, _youtube_play, _validate(["query"], ["browser", "tab"]), verify=_window_verifier,
        reversibility="transient",
        argument_schema={"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300},
                                                          "browser": {"type": "string",
                                                                      "enum": ["brave", "chrome", "edge", "firefox"]},
                                                          "tab": {"type": "string", "enum": ["auto", "new", "same"]}},
                         "required": ["query"], "additionalProperties": False},
        prerequisites=("interactive Windows desktop",), success_predicate="default_browser_window_observed",
        required_capability="browser.navigate", network_egress=True))
