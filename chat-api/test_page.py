# test_page.py - the Chat page: theme tokens, contrast, budgets, markup and structure.
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "chat.js").read_text(encoding="utf-8")
MOTION = "@media (prefers-reduced-motion: no-preference)"
COLOURS = ["bg", "surface", "surface-2", "ink", "ink-2", "muted", "rule", "rule-2", "field", "accent", "accent-ink",
           "accent-soft", "bad", "bad-soft"]
TEXT_ON = ["ink", "ink-2", "muted", "accent", "bad"]


def block(selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"missing block {selector}"
    return dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", m.group(1)))


def modes():
    return block(":root"), block(':root[data-theme="dark"]')


def luminance(hex_colour):
    h = hex_colour.strip().lstrip("#")
    assert len(h) == 6, f"text colours must be opaque #RRGGBB, got {hex_colour}"
    def channel(c):
        v = int(c, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_both_modes_define_every_colour_token():
    light, dark = modes()
    assert not [t for t in COLOURS + ["sans", "shadow-1", "shadow-2"] if t not in light]
    assert not [t for t in COLOURS + ["shadow-1", "shadow-2"] if t not in dark]


def test_text_meets_wcag_aa_in_both_modes():
    for mode in modes():
        for token in TEXT_ON:
            for ground in ("bg", "surface", "surface-2"):
                ratio = contrast(mode[token], mode[ground])
                assert ratio >= 4.5, f"--{token} on --{ground} is {ratio:.2f}:1"
        assert contrast(mode["accent-ink"], mode["accent"]) >= 4.5, "button and bubble text on accent"
        assert contrast(mode["bad"], mode["bad-soft"]) >= 4.5, "error text on its bubble"


def test_pack_stays_within_its_budgets_and_is_self_hosted():
    fonts = sum(p.stat().st_size for p in (STATIC / "fonts").glob("*.woff2"))
    assert fonts <= 120_000, f"fonts {fonts} bytes"
    assert (STATIC / "style.css").stat().st_size <= 40_000
    assert CSS.count("@font-face") == CSS.count("font-display: swap")
    assert not re.search(r"url\((?!\"?fonts/)", CSS), "assets must be self-hosted"


def test_motion_only_without_reduced_motion():
    head, *rest = CSS.split(MOTION)
    assert len(rest) <= 1, "keep all signature motion in one no-preference block"
    assert "animation" not in head and "@keyframes" not in head


def test_page_opens_light_with_its_pack_and_mark():
    assert '<html lang="en" data-default-theme="light">' in HTML
    head = HTML[:HTML.index("</head>")]
    assert head.index('src="theme.js?v=2"') < head.index('href="style.css?v=')
    assert 'href="fonts/dm-sans-latin.woff2" as="font"' in head
    assert 'rel="icon" type="image/svg+xml" href="icon.svg?v=2"' in head
    assert "instrument-sans" not in HTML + CSS


def test_no_inline_code_and_every_local_asset_exists():
    assert not re.search(r"\sstyle\s*=", HTML), "inline style attribute"
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", HTML), "inline script"
    for ref in re.findall(r'(?:src|href)="([^"#?]+)', HTML):
        if not ref.startswith(("http", "/", "mailto:")):
            assert (STATIC / ref).is_file(), f"missing {ref}"


HARNESS = """
const attrs = {}; let cookie = %(cookie)s; const store = %(store)s;
global.document = { documentElement: { getAttribute: k => attrs[k] ?? null, setAttribute: (k, v) => { attrs[k] = v; } },
                    get cookie() { return cookie; }, set cookie(v) { cookie = v; }, addEventListener() {} };
global.location = { hostname: "chat.naveenlabs.tech" };
global.localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
global.window = { matchMedia: () => ({ matches: %(system_dark)s }) };
if (%(default)s) attrs["data-default-theme"] = %(default)s;
require(%(script)s);
console.log(attrs["data-theme"]);
"""


def theme(default=None, cookie="", store=None, system_dark=False):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    code = HARNESS % {"cookie": json.dumps(cookie), "store": json.dumps(store or {}), "system_dark": json.dumps(system_dark),
                      "default": json.dumps(default) if default else "null", "script": json.dumps(str(STATIC / "theme.js"))}
    return subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout.strip()


def test_chat_opens_light_unless_the_visitor_chose():
    assert theme(default="light", system_dark=True) == "light"
    assert theme(default="light", cookie="theme=dark") == "dark"
    assert theme(default="light", store={"theme": "dark"}) == "dark"
    assert theme(system_dark=True) == "dark"            # no signature: the system setting, as before


def test_home_is_greeting_composer_projects_conversation():
    order = [HTML.index(s) for s in ('<h1', 'id="chat-form"', 'id="starters"', 'id="chat-window"')]
    assert order == sorted(order)
    cards = re.findall(r'<div class="project project-(\w+)" data-project="\1">(.*?)</div>', HTML, re.S)
    assert [k for k, _ in cards] == ["trust", "radar", "blueprints", "tradfi", "web3", "chat"]
    assert all(body.count('class="starter"') == 2 and "built?" in body for _, body in cards)
    assert all(f'data-project="{k}"' in body for k, body in cards)
    assert all("data-section=" not in body for _, body in cards)          # the card's own question goes to the model
    assert 'role="log"' in HTML and 'aria-live="polite"' in HTML


def test_cards_fold_away_and_come_back():
    assert 'id="show-projects"' in HTML and "show-projects" in JS and ".hidden" in JS


def test_answers_are_rendered_from_a_markdown_subset_with_dom_nodes():
    assert "function render(" in JS
    for tag in ("h2", "h3", "ul", "li", "strong", "code", "p"):
        assert f'createElement("{tag}")' in JS, tag


def test_answers_stream_and_send_the_current_project():
    assert "getReader()" in JS and "currentProject" in JS and "project: currentProject" in JS


def test_more_buttons_ask_for_the_detailed_section():
    assert "More on the" in JS and "detail: true" in JS
    for section in ("architecture", "strengths", "intelligence"):
        assert f'"{section}"' in JS, section


def test_the_greeting_says_what_chat_knows():
    assert "Ask about any of the six projects, or anything else." in HTML


def test_every_icon_used_is_in_the_sprite_and_within_budget():
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    used = set(re.findall(r'icons\.svg#([\w-]+)', HTML))
    assert {"i-trust", "i-radar", "i-blueprints", "i-tradfi", "i-web3", "i-chat", "i-send"} <= used
    assert all(f'id="{icon}"' in sprite for icon in used)
    assert (STATIC / "icons.svg").stat().st_size <= 15_000


def test_send_button_has_a_name_and_the_input_a_label():
    assert 'id="chat-send" aria-label="Send"' in HTML and '<label class="visually-hidden" for="chat-input">' in HTML


def test_footer_note_is_honest_about_the_small_model():
    foot = HTML[HTML.index("<footer"):]
    assert "A small model running on our own server. It can be wrong; nothing you type is stored." in foot


def rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"missing rule {selector}"
    return m.group(1)


def test_composer_stays_at_the_top():
    assert "position: sticky" in rule(".composer") and re.search(r"(^|;)\s*top: \d", rule(".composer"))


def test_long_words_wrap_inside_bubbles():
    assert "overflow-wrap: anywhere" in rule(".msg")


def test_replies_are_rendered_as_text_only():
    assert "innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS


def test_typing_indicator_replaces_the_thinking_text():
    assert "Thinking" not in JS and 'className = "typing"' in JS and "Chat is typing" in JS
    motion = CSS.split(MOTION)[1]
    assert ".typing i" in motion and "@keyframes" in motion


def test_an_empty_answer_never_leaves_a_blank():
    assert "No answer came back" in JS and "errorShown" in JS


def test_project_answers_offer_the_checked_brief():
    assert "Show the checked brief" in JS and "brief: true" in JS and "done.grounded" in JS


def test_the_wait_is_explained_while_the_model_reads():
    assert "can take up to a minute" in JS


def test_screen_readers_hear_the_answer_once_it_is_complete():
    assert 'setAttribute("aria-busy", "true")' in JS and 'removeAttribute("aria-busy")' in JS


def test_buttons_are_disabled_while_an_answer_is_coming():
    assert 'querySelectorAll(".starter, .more-btn")' in JS and "setBusy(true)" in JS and "setBusy(false)" in JS


def test_only_typed_questions_return_focus_to_the_input():
    assert "if (!from) input.focus()" in JS and "preventScroll: true" in JS


def test_once_a_chat_starts_history_is_on_top_and_the_composer_below():
    assert 'classList.add("chatting")' in JS
    assert "display: none" in rule(".chatting .greeting")
    assert "order:" in rule(".chatting .conversation") and "order:" in rule(".chatting .composer")
    order = lambda sel: int(re.search(r"order:\s*(\d+)", rule(sel)).group(1))
    assert order(".chatting .conversation") < order(".chatting .composer")
    assert "bottom:" in rule(".chatting .composer") and "top: auto" in rule(".chatting .composer")
    assert "scroll-margin-bottom" in rule(".chatting .conversation > *")   # new messages never hide under the box
    assert 'bubble.scrollIntoView({ block: "nearest" })' in JS                  # and a growing answer stays above it
