from pathlib import Path

from ph2md.extractors.producthunt_page import parse_leaderboard_html


def test_parse_leaderboard_html_extracts_products_from_next_data():
    html = Path("tests/ph2md/fixtures/producthunt_monthly.html").read_text(encoding="utf-8")

    products = parse_leaderboard_html(html, year=2026, month=6, limit=2)

    assert len(products) == 2
    assert products[0].rank == 1
    assert products[0].name == "Fundraisly"
    assert products[0].slug == "fundraisly"
    assert products[0].tagline == "AI fundraising agent that finds investors and books meetings"
    assert products[0].producthunt_url == "https://www.producthunt.com/products/fundraisly"
    assert products[0].votes == 1462
    assert products[0].comments == 411
    assert products[0].categories == ["Venture Capital", "Artificial Intelligence"]
    assert products[0].thumbnail_url == "https://ph-files.imgix.net/fundraisly.png"
    assert products[1].producthunt_url == "https://www.producthunt.com/products/upstream"


def test_parse_leaderboard_html_extracts_simple_html_fallback():
    html = """
    <html><body>
      <article data-test="post-item">
        <span>1</span>
        <a href="/products/example">Example App</a>
        <p>A useful Product Hunt app</p>
        <span>321 votes</span>
        <span>45 comments</span>
      </article>
    </body></html>
    """

    products = parse_leaderboard_html(html, year=2026, month=6, limit=10)

    assert len(products) == 1
    assert products[0].rank == 1
    assert products[0].name == "Example App"
    assert products[0].tagline == "A useful Product Hunt app"
    assert products[0].votes == 321
    assert products[0].comments == 45


def test_parse_leaderboard_html_extracts_current_producthunt_section_cards():
    html = """
    <html><body>
      <section data-container="">
        <img alt="Fundraisly" src="https://ph-files.imgix.net/fundraisly.png?auto=compress" />
        <div>
          <span><a href="/products/fundraisly"><span data-target="true"></span>1. Fundraisly</a></span>
          <span>AI fundraising agent that finds investors and books meetings</span>
          <div>
            <a href="/topics/venture-capital">Venture Capital</a>
            <span>•</span>
            <a href="/topics/artificial-intelligence">Artificial Intelligence</a>
            <span>•</span>
            <a href="/topics/fundraising">Fundraising</a>
          </div>
        </div>
        <button><p>411</p></button>
        <button data-test="vote-button"><p>1,462</p></button>
      </section>
    </body></html>
    """

    products = parse_leaderboard_html(html, year=2026, month=6, limit=10)

    assert len(products) == 1
    assert products[0].rank == 1
    assert products[0].name == "Fundraisly"
    assert products[0].slug == "fundraisly"
    assert products[0].tagline == "AI fundraising agent that finds investors and books meetings"
    assert products[0].producthunt_url == "https://www.producthunt.com/products/fundraisly"
    assert products[0].categories == ["Venture Capital", "Artificial Intelligence", "Fundraising"]
    assert products[0].comments == 411
    assert products[0].votes == 1462
    assert products[0].thumbnail_url == "https://ph-files.imgix.net/fundraisly.png?auto=compress"


def test_parse_leaderboard_html_normalizes_duplicate_display_ranks_to_position():
    html = """
    <html><body>
      <section data-container="">
        <a href="/products/first">10. First</a>
        <span>First tagline</span>
        <button data-test="vote-button"><p>100</p></button>
      </section>
      <section data-container="">
        <a href="/products/second">10. Second</a>
        <span>Second tagline</span>
        <button data-test="vote-button"><p>90</p></button>
      </section>
    </body></html>
    """

    products = parse_leaderboard_html(html, year=2026, month=6, limit=10)

    assert [product.rank for product in products] == [1, 2]
    assert [product.name for product in products] == ["First", "Second"]


def test_parse_leaderboard_html_skips_unnumbered_promotions_between_ranked_cards():
    html = """
    <html><body>
      <section data-container=""><a href="/products/first">1. First</a><span>First tagline</span></section>
      <section data-container=""><a href="/products/promo">Promoted App</a><span>Promoted tagline</span></section>
      <section data-container=""><a href="/products/second">2. Second</a><span>Second tagline</span></section>
    </body></html>
    """

    products = parse_leaderboard_html(html, year=2026, month=9, limit=10)

    assert [(product.rank, product.name) for product in products] == [(1, "First"), (2, "Second")]


def test_next_data_keeps_distinct_launches_that_share_parent_product_url():
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"products":[
      {"rank":1,"name":"Kilo Code for JetBrains","url":"/products/kilocode"},
      {"rank":2,"name":"Kilo Code for iOS and Android","url":"/products/kilocode"},
      {"rank":2,"name":"Kilo Code for iOS and Android","url":"/products/kilocode"}
    ]}}
    </script>
    """

    products = parse_leaderboard_html(html, year=2026, month=9, limit=25)

    assert [(product.rank, product.name) for product in products] == [
        (1, "Kilo Code for JetBrains"),
        (2, "Kilo Code for iOS and Android"),
    ]


def test_next_data_keeps_separately_ranked_duplicate_for_integrity_check():
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {"products":[
      {"rank":1,"name":"Repeated","url":"/products/repeated"},
      {"rank":2,"name":"Repeated","url":"/products/repeated"}
    ]}
    </script>
    """

    products = parse_leaderboard_html(html, year=2026, month=9, limit=25)

    assert [item.rank for item in products] == [1, 2]
