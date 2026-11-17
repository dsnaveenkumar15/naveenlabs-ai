"""Project briefs: checked, sectioned Markdown about each project. The model answers project questions from the whole
brief (facts), and code checks every number in its answer against the brief (invented_numbers)."""
import re
from dataclasses import dataclass
from pathlib import Path

PROJECTS = ("trust", "radar", "blueprints", "tradfi", "web3", "chat")
NAMES = {"trust": "Trust", "radar": "Radar", "blueprints": "Blueprints", "tradfi": "TradFi", "web3": "Web3", "chat": "Chat"}
SECTIONS = ("intro", "architecture", "strengths", "intelligence")
HEADINGS = {name: name.capitalize() for name in SECTIONS}
CONTEXT_CHARS = 1600        # a section's short form stays under half of this, so the brief stays compact
MORE = "<!-- more -->"
# Never in a brief, a prompt or the page: brand names, hosts, private tools, advice.
BANNED = ("zerodha", "kite", "binance", "n8n", "flowise", "portainer", "kuma", "tailscale", "187.126.",
          "/internal/control", ":9100", ":9200", ":9300", "investment advice")

_BANNED_RE = re.compile("|".join(rf"\b{re.escape(w)}\b" if w.isalnum() else re.escape(w) for w in BANNED), re.I)


def banned_in(text: str) -> list:
    """Banned words found in the text: plain words match whole words only ("kuma" is not in "Naveenkumar")."""
    return sorted({match.group(0).lower() for match in _BANNED_RE.finditer(text)})


# Longer aliases first so "red team" wins over nothing and "blueprints" over "blueprint".
ALIASES = (("red team", "trust"), ("upgrade agent", "radar"), ("blueprints", "blueprints"), ("blueprint", "blueprints"),
           ("architect", "blueprints"), ("trust", "trust"), ("radar", "radar"), ("tradfi", "tradfi"), ("web3", "web3"),
           ("chat", "chat"))
_ALIAS = "|".join(re.escape(alias) for alias, _ in ALIASES)
_ALIAS_RE = re.compile(rf"\b({_ALIAS})\b", re.I)
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


# Everyday words that are also project names: written in lower case they name the project only when the rest of the
# question shares a word with its brief ("how is trust tested?"), never on their own ("Can I trust you?").
EVERYDAY = frozenset({"trust", "radar", "chat"})


def find_project(message: str, current: str | None, briefs: dict | None = None) -> str | None:
    for match in _ALIAS_RE.finditer(message):
        word = match.group(1)
        project = dict(ALIASES)[word.lower()]
        if word.lower() not in EVERYDAY or not word.islower():
            return project
        rest = message[:match.start()] + message[match.end():]
        if briefs and relevance(project, rest, briefs):
            return project
    return current if current in PROJECTS else None


def route(message: str, current: str | None, section: str | None, briefs: dict) -> str | None:
    """The project a question is about: the one it names, else the page's current project when the question asks for
    a section or shares a meaningful word with that brief; None means a general question."""
    named = find_project(message, None, briefs)
    if named:
        return named
    if current in PROJECTS and (section or relevance(current, message, briefs)):
        return current
    return None


def facts(project: str, briefs: dict) -> str:
    """The whole brief in its detailed form: what the model may say about the project, and nothing else."""
    return "\n\n".join(f"## {HEADINGS[name]}\n\n{briefs[project].sections[name].detail}" for name in SECTIONS)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"(?m)^\s*\d+\.\s")


def invented_numbers(reply: str, source: str) -> list:
    """Numbers in the reply that the source does not hold (ordered-list markers are not facts)."""
    known = {n.rstrip(",.") for n in _NUMBER.findall(source)}
    found = [n.rstrip(",.") for n in _NUMBER.findall(_LIST_MARKER.sub("", reply))]
    return sorted({n for n in found if n not in known}, key=found.index)


_COMMON = frozenset("""what when where which while does have with this that from your about there their they them then
than these those will would could should into more most some also just like make made very been were being other each
every only over such much many here know tell explain describe please thanks thank good best work works""".split())


def _stem(word: str) -> str:
    """A light stem so tests, tested and testing meet: drops -ing, -ed or -s when at least 4 letters remain."""
    for ending in ("ing", "ed", "s"):
        if word.endswith(ending) and not word.endswith("ss") and len(word) - len(ending) >= 4:
            return word[:-len(ending)]
    return word


def _words(text: str) -> set:
    return {_stem(word) for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 3 and word not in _COMMON}


def relevance(project: str, message: str, briefs: dict) -> int:
    """How many meaningful words the question shares with the project's brief: 0 means it is not about the project."""
    brief = briefs[project]
    return len(_words(message) & _words(" ".join(s.short + " " + s.detail for s in brief.sections.values())))


def best_section(project: str, message: str, briefs: dict) -> str:
    """The section that shares most meaningful words with the question; the intro when none does."""
    brief, asked = briefs[project], _words(message)
    scores = {name: len(asked & _words(brief.sections[name].short + " " + brief.sections[name].detail))
              for name in SECTIONS}
    best = max(SECTIONS, key=lambda name: (scores[name], -SECTIONS.index(name)))
    return best if scores[best] else "intro"
