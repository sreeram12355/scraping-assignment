"""Local mock of both practice sites, used by tests (the real sites are not hit in CI).

HTML mirrors the real structure: books pages use *relative* links with the real quirk that
page 1 links to 'catalogue/x/index.html' while later pages link to 'x/index.html';
quotes pages use root-relative '/page/2/' links.

Deliberate problems injected:
  books : duplicate title (different case/whitespace), card without price, bad rating word,
          detail page that fails once with 500 (retry works), detail page that 404s
  quotes: duplicate quote (case/whitespace), quote without author, quote without tags,
          author page that 404s
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def book_card(slug, title, price="£10.00", rating="Three", prefix="", visible=None):
    price_html = f'<p class="price_color">{price}</p>' if price is not None else ""
    return f'''<article class="product_pod"><div class="image_container"></div>
<p class="star-rating {rating}"></p>
<h3><a href="{prefix}{slug}/index.html" title="{title}">{visible or title[:12] + "..."}</a></h3>
<div class="product_price">{price_html}<p class="instock availability"><i class="icon-ok"></i>
    In stock
</p></div></article>'''


def book_page(cards, next_href=None):
    nxt = f'<li class="next"><a href="{next_href}">next</a></li>' if next_href else ""
    return f"<html><body><ol class='row'>{''.join('<li>' + c + '</li>' for c in cards)}</ol><ul class='pager'>{nxt}</ul></body></html>"


def book_detail(title, category, description):
    desc = (f'<div id="product_description" class="sub-header"><h2>Product Description</h2></div><p>{description}</p>'
            if description else "")
    return f'''<html><body><ul class="breadcrumb"><li><a href="../../index.html">Home</a></li>
<li><a href="../category/books_1/index.html">Books</a></li>
<li><a href="../category/books/x/index.html">{category}</a></li><li class="active">{title}</li></ul>{desc}</body></html>'''


def quote_block(text, author, tags, author_href=None):
    author_html = f'<span>by <small class="author" itemprop="author">{author}</small><a href="{author_href}">(about)</a></span>' if author else ""
    tag_html = ('<div class="tags">Tags: ' + "".join(f'<a class="tag" href="/tag/{t}/">{t}</a>' for t in tags) + "</div>") if tags is not None else ""
    return f'<div class="quote"><span class="text" itemprop="text">{text}</span>{author_html}{tag_html}</div>'


def quote_page(blocks, next_href=None):
    nxt = f'<li class="next"><a href="{next_href}">Next</a></li>' if next_href else ""
    return f"<html><body>{''.join(blocks)}<ul class='pager'>{nxt}</ul></body></html>"


def author_page(born, where, bio):
    return (f'<html><body><span class="author-born-date">{born}</span><span class="author-born-location">{where}</span>'
            f'<div class="author-description">\n  {bio}\n</div></body></html>')


class Flaky:
    """Responds `status` for the first `fail_times` requests, then serves `body`."""
    def __init__(self, body, fail_times=1, status=500):
        self.body, self.remaining, self.status = body, fail_times, status

    def __call__(self):
        if self.remaining > 0:
            self.remaining -= 1
            return self.status, "error"
        return 200, self.body


def books_routes():
    c = "catalogue/"
    return {
        "/index.html": book_page([
            book_card("a-light_1", "A Light in the Attic", "£51.77", "Three", prefix=c),
            book_card("tipping_2", "Tipping the Velvet", "£53.74", "One", prefix=c),
            book_card("soumission_3", "Soumission", "£50.10", "One", prefix=c),
        ], "catalogue/page-2.html"),
        "/catalogue/page-2.html": book_page([
            book_card("sharp_4", "Sharp Objects", "£47.82", "Four"),
            book_card("dup_5", "  a LIGHT   in the attic ", "£51.77", "Three"),      # duplicate of #1
            book_card("noprice_6", "Book Without Price", None, "Two"),                # rejected: no price
        ], "page-3.html"),
        "/catalogue/page-3.html": book_page([
            book_card("badrating_7", "Weird Rating Book", "£12.00", "Nine"),          # rejected: bad rating
            book_card("last_8", "The Last Book", "£20.00", "Five"),
        ]),
        "/catalogue/a-light_1/index.html": book_detail("A Light in the Attic", "Poetry", "It's hard to imagine a world without A Light in the Attic."),
        "/catalogue/tipping_2/index.html": Flaky(book_detail("Tipping the Velvet", "Historical Fiction", "Erotic and absorbing."), 1, 500),
        "/catalogue/soumission_3/index.html": book_detail("Soumission", "Fiction", None),   # no description
        "/catalogue/sharp_4/index.html": book_detail("Sharp Objects", "Mystery", "WICKED above her hairline."),
        "/catalogue/dup_5/index.html": book_detail("dup", "Poetry", "dup"),
        "/catalogue/noprice_6/index.html": book_detail("x", "Fiction", "x"),
        # badrating_7 detail intentionally absent -> 404
        "/catalogue/last_8/index.html": book_detail("The Last Book", "Travel", "Final."),
    }


def quotes_routes():
    e, a = "/author/Albert-Einstein", "/author/Jane-Austen"
    return {
        "/": quote_page([
            quote_block("“The world as we have created it is a process of our thinking.”", "Albert Einstein", ["change", "deep-thoughts"], e),
            quote_block("“The person, be it gentleman or lady, who has not pleasure in a good novel, must be intolerably stupid.”", "Jane Austen", ["aliteracy", "books"], a),
        ], "/page/2/"),
        "/page/2/": quote_page([
            quote_block("“  THE WORLD AS WE HAVE CREATED IT is a process   of our thinking.  ”", "Albert Einstein", ["Change"], e),  # duplicate
            quote_block("“A quote without tags.”", "Albert Einstein", None, e),
            quote_block("“An orphan quote with no author.”", None, ["x"]),                                                             # rejected
        ]),
        e: author_page("March 14, 1879", "in Ulm, Germany", "In 1879, Albert Einstein was born in Ulm, Germany."),
        # Jane Austen author page intentionally absent -> 404
    }


def serve(routes: dict):
    """Start a background HTTP server; returns (server, base_url). Call server.shutdown() when done."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes.get(self.path.split("?")[0])
            if route is None:
                status, body = 404, "not found"
            elif callable(route):
                status, body = route()
            else:
                status, body = 200, route
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html")   # no charset on purpose, like the real site
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"
