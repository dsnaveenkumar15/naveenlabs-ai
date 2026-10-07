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
    assert head.index('src="theme.js?v=2"') < head.index('href="style.css?v=5"')
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
