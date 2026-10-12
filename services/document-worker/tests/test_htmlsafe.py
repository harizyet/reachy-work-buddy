"""The HTML MinerU renders is untrusted document text: it is rebuilt from an allowlist (htmlsafe.py) before it leaves the worker."""

import re

import pytest
from document_worker import htmlsafe

HOSTILE = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)" onclick="alert(2)">click</a>',
    '<a href="https://evil.example/steal">out</a>',
    '<iframe src="https://evil.example"></iframe>',
    '<meta http-equiv="refresh" content="0;url=https://evil.example">',
    '<link rel="stylesheet" href="https://evil.example/x.css">',
    '<base href="https://evil.example/">',
    '<form action="https://evil.example"><input name=a><button>go</button></form>',
    "<object data=x></object><embed src=x>",
    '<svg onload="alert(1)"><script>alert(2)</script></svg>',
    '<math><mi xlink:href="javascript:alert(1)">x</mi></math>',
    '<p style="background:url(https://evil.example/a.png)" onmouseover="alert(1)">hi</p>',
    '<div class="a" onclick="alert(1)" id="x" data-block-index="3">ok</div>',
    '<style>@import url("https://evil.example/x.css");</style>',
    "<!-- <script>alert(1)</script> -->",
    "<scr<script>ipt>alert(1)</scr</script>ipt>",
    '<video src="https://evil.example/v"></video><audio src=x></audio>',
    "<template><script>alert(1)</script></template><noscript><img src=x></noscript>",
]


@pytest.mark.parametrize("markup", HOSTILE)
def test_nothing_that_can_run_or_fetch_survives(markup):
    out = htmlsafe.sanitize_fragment(markup).lower()
    for needle in ("<script", "<iframe", "<img", "<form", "<input", "<object", "<embed", "<meta", "<link", "<base", "<svg", "<math", "<video", "<audio", "<style", "<button"):
        assert needle not in out, (markup, out)
    assert not re.search(r"\bon[a-z]+\s*=", out) and "javascript:" not in out and "href" not in out and "src=" not in out and "style=" not in out and "http" not in out.replace("&lt;", ""), (markup, out)


def test_text_is_kept_and_escaped_and_structure_survives():
    out = htmlsafe.sanitize_fragment('<article class="docvortex-document"><h2 class="docvortex-heading">2 &lt; 3 &amp; <b>x</b></h2><table><tbody><tr><td colspan="2" onclick="x()">a &lt;script&gt;</td></tr></tbody></table><a href="//e">link text</a></article>')
    assert out == ('<article class="docvortex-document"><h2 class="docvortex-heading">2 &lt; 3 &amp; <b>x</b></h2><table><tbody><tr><td colspan="2">a &lt;script&gt;</td></tr></tbody></table>'
                   '<span class="docvortex-link-text">link text</span></article>')
    assert htmlsafe.sanitize_fragment('<div data-block-index="3" data-page-idx="0" data-evil="<x>">t</div>') == '<div data-block-index="3" data-page-idx="0">t</div>'
    assert htmlsafe.sanitize_fragment("<p>a<br/>b<hr></p>") == "<p>a<br>b<hr></p>"


def test_unbalanced_and_nested_drops_do_not_leak_what_follows():
    out = htmlsafe.sanitize_fragment("<script>one<script>two</script>three</script>after")  # the parser ends a script at the first closing tag; what follows is plain, escaped text
    assert "<script" not in out and "one" not in out and "two" not in out
    out = htmlsafe.sanitize_fragment("<iframe><p>inside</p></iframe><p>outside</p>")
    assert "inside" not in out and "<p>outside</p>" in out


def test_css_loses_everything_that_fetches_or_executes():
    css = '@import url("https://evil.example/x.css");.a{background:url(https://evil.example/a.png);width:expression(alert(1));behavior:url(x.htc);-moz-binding:url(x)}.b{color:#123}</style><script>x</script>'
    out = htmlsafe.sanitize_css(css)
    for needle in ("@import", "url(", "expression(", "behavior", "-moz-binding", "</style", "http"):
        assert needle not in out.lower(), (needle, out)
    assert ".b{color:#123}" in out
    full = htmlsafe.document(css, "<p>x</p>")
    assert full.startswith("<style>") and full.count("<style>") == 1 and "<script" not in full.lower()
