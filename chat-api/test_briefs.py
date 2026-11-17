# test_briefs.py - the project briefs: loading, routing a question, and the model's context.
import re
from pathlib import Path

import pytest

from briefs import CONTEXT_CHARS, banned_in, best_section, facts, invented_numbers, relevance, route, PROJECTS, find_project, load_briefs, _words

HEADINGS = {"intro": "Intro", "architecture": "Architecture", "strengths": "Strengths", "intelligence": "Intelligence"}


def write_brief(directory, project, body=None):
    body = body or {name: (f"{name.capitalize()} short.", f"{name.capitalize()} detail.") for name in HEADINGS}
    text = "".join(f"## {HEADINGS[name]}\n\n{short}\n\n<!-- more -->\n\n{detail}\n\n" for name, (short, detail) in body.items())
    (directory / f"{project}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def briefs(tmp_path):
    for project in PROJECTS:
        write_brief(tmp_path, project)
    return load_briefs(tmp_path)


@pytest.fixture
def briefs_long(tmp_path):
    words = "lorem ipsum dolor sit amet " * 60
    for project in PROJECTS:
        write_brief(tmp_path, project, {
            "intro": ("A checker for agent tools.", words),
            "architecture": ("Web app, rules engine, sandbox.", words),
            "strengths": ("Tested, cheap, fast.", words),
            "intelligence": ("A small model scores the attacks; the guard is code.", "The model scores the attacks. " + words),
        })
    return load_briefs(tmp_path)


def test_load_reads_four_sections_with_both_forms(briefs):
    section = briefs["trust"].sections["architecture"]
    assert section.short == "Architecture short." and section.detail == "Architecture detail."
    assert list(briefs["trust"].sections) == list(HEADINGS)


def test_missing_section_names_the_file(tmp_path):
    for project in PROJECTS:
        write_brief(tmp_path, project)
    (tmp_path / "trust.md").write_text("## Intro\n\nOnly this.\n\n<!-- more -->\n\nMore.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="trust.md"):
        load_briefs(tmp_path)


def test_missing_detail_form_names_the_file(tmp_path):
    for project in PROJECTS:
        write_brief(tmp_path, project)
    text = (tmp_path / "radar.md").read_text(encoding="utf-8").replace("<!-- more -->", "", 1)
    (tmp_path / "radar.md").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="radar.md"):
        load_briefs(tmp_path)


def test_full_brief_has_title_and_headings_in_order(briefs):
    text = briefs["trust"].full()
    assert text.startswith("# Trust")
    assert re.findall(r"^## (\w+)", text, re.M) == ["Intro", "Architecture", "Strengths", "Intelligence"]
    assert "Architecture detail." not in text


def test_section_gives_the_short_or_the_detailed_form(briefs):
    assert briefs["web3"].section("strengths", detail=False) == "## Strengths\n\nStrengths short."
    assert briefs["web3"].section("strengths", detail=True) == "## Strengths\n\nStrengths detail."


@pytest.mark.parametrize("message,expected", [
    ("How is Trust built?", "trust"), ("tell me about the red team", "trust"), ("What does the Architect do?", "blueprints"),
    ("explain TradFi", "tradfi"), ("WEB3 architecture", "web3"), ("How does the upgrade agent work?", "radar"),
    ("What is a trustworthy source?", None), ("What can you do?", None)])
def test_find_project_by_name_or_alias(message, expected):
    assert find_project(message, None) == expected


def test_follow_up_without_a_name_uses_the_current_project():
    assert find_project("how is it tested?", "radar") == "radar"
    assert find_project("how is it tested?", "nonsense") is None
    assert find_project("and how is Web3 tested?", "radar") == "web3"


def test_facts_hold_every_section_in_detail(briefs):
    text = facts("trust", briefs)
    for name in ("Intro", "Architecture", "Strengths", "Intelligence"):
        assert f"## {name}\n\n{name} detail." in text
    assert "short." not in text


def test_invented_numbers_finds_numbers_the_facts_do_not_hold():
    source = "It stopped 0 of 178 (0%) attacks. 700 tries cost $0.0919. Runs every 6 hours; 1,826 tests."
    assert invented_numbers("0 of 178 (0%) got through, for $0.0919, every 6 hours, 1,826 tests", source) == []
    assert invented_numbers("0 of 180 got through in 7 hours", source) == ["180", "7"]
    assert invented_numbers("1. First step\n2. Second step\n- 3 workers", source) == ["3"]   # list markers are not facts


def test_best_section_prefers_the_matching_section(briefs_long):
    assert best_section("trust", "which model scores the attacks?", briefs_long) == "intelligence"
    assert best_section("trust", "which model scores the attack?", briefs_long) == "intelligence"   # plural or not


def test_best_section_falls_back_to_the_intro(briefs_long):
    assert best_section("radar", "zzz", briefs_long) == "intro"


REAL = Path(__file__).parent / "briefs"


def test_every_project_has_a_complete_brief():
    assert set(load_briefs(REAL)) == set(PROJECTS)


def test_briefs_never_name_brands_hosts_or_private_tools():
    for path in REAL.glob("*.md"):
        assert banned_in(path.read_text(encoding="utf-8")) == [], path.name


def test_banned_check_matches_whole_words():
    assert banned_in("Naveenkumar built it") == []
    assert banned_in("uses Kuma and n8n") == ["kuma", "n8n"]
    assert banned_in("port :9200 and 187.126.1.1") == ["187.126.", ":9200"]


def test_short_forms_fit_the_model_context():
    for brief in load_briefs(REAL).values():
        for name, section in brief.sections.items():
            assert len(section.short) <= CONTEXT_CHARS // 2, (brief.project, name, len(section.short))


def test_finance_briefs_say_paper_mode():
    briefs = load_briefs(REAL)
    for project in ("tradfi", "web3"):
        assert "paper" in briefs[project].full().lower(), project


def test_relevance_ignores_common_words(briefs_long):
    assert relevance("trust", "What is the capital of Japan?", briefs_long) == 0
    assert relevance("trust", "which model scores the attacks?", briefs_long) > 0


LOADED = load_briefs(REAL)


@pytest.mark.parametrize("message,expected", [
    ("Can I trust you?", None), ("Let's chat", None), ("What is a weather radar?", None),
    ("how is trust tested?", "trust"), ("how does radar collect releases?", "radar"), ("Trust", "trust")])
def test_everyday_words_only_name_a_project_when_the_question_is_about_it(message, expected):
    assert find_project(message, None, LOADED) == expected


def test_words_match_across_common_endings():
    assert _words("testing tested tests guarded guards") == {"test", "guard"}


def test_route_keeps_the_current_project_only_for_a_related_question():
    assert route("how is it tested?", "radar", None, LOADED) == "radar"
    assert route("What is the capital of Japan?", "radar", None, LOADED) is None
    assert route("anything", "radar", "strengths", LOADED) == "radar"
    assert route("and how is Web3 tested?", "radar", None, LOADED) == "web3"


def test_every_card_question_reaches_its_project():
    html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    cards = re.findall(r'<button type="button" class="starter" data-project="(\w+)">([^<]+)</button>', html)
    assert len(cards) == 12
    for project, question in cards:
        assert route(question, project, None, LOADED) == project, question


def test_trust_brief_says_how_the_code_guard_works():
    text = facts("trust", LOADED)
    assert "strips the suspect text" in text and "ext_" in text and "untrusted content" in text
