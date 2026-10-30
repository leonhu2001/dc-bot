from services.news.garena_delta import parse_garena_news_html


def test_parse_garena_news_html_accepts_only_official_article_paths():
    html = """
    <html><body>
      <a href="/zh_tw/news/system/KDX2U2">
        <span>2026/08/05</span>
        <h3>8 月 6 日 | 寶藏月即將開啟！</h3>
        <p>2600 點限時三角券免費領！</p>
        <span>閱讀更多</span>
      </a>
      <a href="https://deltaforce.garena.com/zh_tw/news/announcement/56GKRH">
        <time>2026/08/06</time>
        <strong>Delta Force 安全團隊外掛封禁公告</strong>
        閱讀更多
      </a>
      <a href="https://evil.example/news/system/NOPE">2026/08/07 惡意來源</a>
      <a href="https://deltaforce.garena.com/zh_tw/news/all">新聞列表</a>
    </body></html>
    """

    articles = parse_garena_news_html(html)

    assert [article.article_id for article in articles] == ["56GKRH", "KDX2U2"]
    assert articles[0].category_label == "公告"
    assert articles[1].category_label == "版本資訊"
    assert articles[1].excerpt == "2600 點限時三角券免費領！"
    assert articles[1].published_on.isoformat() == "2026-08-05"


def test_parse_garena_news_html_deduplicates_urls_and_survives_missing_date():
    html = """
      <a href="/zh_tw/news/event/ABC123"><h2>聯名活動</h2>閱讀更多</a>
      <a href="/zh_tw/news/event/ABC123"><h2>聯名活動重複</h2></a>
    """

    articles = parse_garena_news_html(html)

    assert len(articles) == 1
    assert articles[0].title == "聯名活動"
    assert articles[0].published_on is None
    assert articles[0].category_label == "活動"
