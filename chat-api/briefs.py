"""Project briefs: checked, sectioned Markdown about each project, and the routing that decides whether a question
gets a prepared brief (instant, nothing invented) or a short model context built from one brief."""
import re
from dataclasses import dataclass
from pathlib import Path

PROJECTS = ("trust", "radar", "blueprints", "tradfi", "web3", "chat")
NAMES = {"trust": "Trust", "radar": "Radar", "blueprints": "Blueprints", "tradfi": "TradFi", "web3": "Web3", "chat": "Chat"}
SECTIONS = ("intro", "architecture", "strengths", "intelligence")
HEADINGS = {name: name.capitalize() for name in SECTIONS}
CONTEXT_CHARS = 1600        # about 400 tokens: the server reads a prompt at roughly 50-85 tokens a second
MORE = "<!-- more -->"
# Never in a brief, a prompt or the page: brand names, hosts, private tools, advice.
BANNED = ("zerodha", "kite", "binance", "n8n", "flowise", "portainer", "kuma", "tailscale", "187.126.",
          "/internal/control", ":9100", ":9200", ":9300", "investment advice")

# Longer aliases first so "red team" wins over nothing and "blueprints" over "blueprint".
ALIASES = (("red team", "trust"), ("upgrade agent", "radar"), ("blueprints", "blueprints"), ("blueprint", "blueprints"),
           ("architect", "blueprints"), ("trust", "trust"), ("radar", "radar"), ("tradfi", "tradfi"), ("web3", "web3"),
           ("chat", "chat"))
_ALIAS = "|".join(re.escape(alias) for alias, _ in ALIASES)
_ALIAS_RE = re.compile(rf"\b({_ALIAS})\b", re.I)
_A = rf"(?:the )?(?:{_ALIAS})(?: project| app)?"
_OVERVIEW = re.compile(
    rf"^(?:how (?:is|was|does) {_A}(?: built| made| designed| work| works)?"
    rf"|tell me about {_A}|what(?:'s| is) {_A}|(?:explain|describe) {_A}|{_A}(?: overview)?)$")
_SECTION_WORDS = {"intro": ("intro", "introduction", "overview"), "architecture": ("architecture",),
                  "strengths": ("strengths", "strength", "strong points"), "intelligence": ("intelligence",)}


@dataclass(frozen=True)
class Section:
    short: str
    detail: str


@dataclass(frozen=True)
class Brief:
    project: str
    sections: dict

    def full(self) -> str:
        parts = [f"# {NAMES[self.project]}"]
        parts += [f"## {HEADINGS[name]}\n\n{self.sections[name].short}" for name in SECTIONS]
        return "\n\n".join(parts)

    def section(self, name: str, detail: bool) -> str:
        part = self.sections[name]
        return f"## {HEADINGS[name]}\n\n{part.detail if detail else part.short}"


def _parse(path: Path) -> Brief:
    chunks = re.split(r"^## (.+)$", path.read_text(encoding="utf-8"), flags=re.M)
    found = {heading.strip(): body for heading, body in zip(chunks[1::2], chunks[2::2])}
    sections = {}
    for name in SECTIONS:
        body = found.get(HEADINGS[name])
        if body is None or MORE not in body:
            raise ValueError(f"{path.name}: section '{HEADINGS[name]}' is missing or has no '{MORE}' line")
        short, detail = (part.strip() for part in body.split(MORE, 1))
        if not short or not detail:
            raise ValueError(f"{path.name}: section '{HEADINGS[name]}' needs a short and a detailed form")
        sections[name] = Section(short, detail)
    return Brief(path.stem, sections)


def load_briefs(directory: Path) -> dict:
    return {project: _parse(Path(directory) / f"{project}.md") for project in PROJECTS}


def find_project(message: str, current: str | None) -> str | None:
    match = _ALIAS_RE.search(message)
    if match:
        return dict(ALIASES)[match.group(1).lower()]
    return current if current in PROJECTS else None


def _clean(message: str) -> str:
    return re.sub(r"\s+", " ", message.lower()).strip().rstrip("?.! ")


def prepared(message: str, project: str | None, briefs: dict) -> str | None:
    """The full brief for an overview question, one section's short form when a short question names it, else None."""
    named = find_project(message, None)
    if named is None:
        return None
    text = _clean(message)
    if _OVERVIEW.match(text):
        return briefs[named].full()
    if len(text.split()) <= 7:
        for name, words in _SECTION_WORDS.items():
            if any(re.search(rf"\b{re.escape(word)}\b", text) for word in words):
                return briefs[named].section(name, detail=False)
    return None


def _words(text: str) -> set:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 3}


def model_context(project: str, message: str, briefs: dict) -> str:
    """The sections that share most words with the question, detailed when they fit, within CONTEXT_CHARS."""
    brief, asked = briefs[project], _words(message)
    order = sorted(SECTIONS, key=lambda name: (-len(asked & _words(brief.sections[name].short + " " + brief.sections[name].detail)),
                                               SECTIONS.index(name)))
    text = f"{NAMES[project]}:"
    for name in order:
        for detail in (True, False):
            block = "\n\n" + brief.section(name, detail)
            if len(text) + len(block) <= CONTEXT_CHARS:
                text += block
                break
    return text
