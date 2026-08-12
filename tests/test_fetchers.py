import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.fetchers import (
    _html_description,
    _html_title,
    clean_text,
    parse_github_payload,
    parse_hn_payload,
    parse_reddit_payload,
    parse_rss_text,
)


class FetchersTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean_text("<p>Hello <b>world</b></p>", 100), "Hello world")
        self.assertEqual(clean_text("a" * 500, 300), "a" * 300)

    def test_html_title_and_description(self):
        html = (
            '<html><head><title>My Blog</title>'
            '<meta name="description" content="About things"></head></html>'
        )
        self.assertEqual(_html_title(html), "My Blog")
        self.assertEqual(_html_description(html), "About things")

    def test_parse_hn(self):
        items = parse_hn_payload({
            "hits": [{
                "objectID": "123",
                "title": "A story",
                "url": "https://example.com",
                "story_text": "<p>text</p>",
                "points": 10,
            }]
        })
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "hacker-news")
        self.assertEqual(items[0].url, "https://example.com")
        self.assertTrue(items[0].url_hash)

    def test_parse_github(self):
        items = parse_github_payload({"items": [{
            "full_name": "user/repo",
            "html_url": "https://github.com/user/repo",
            "description": "desc",
            "stargazers_count": 99,
        }]})
        self.assertEqual(items[0].source, "github")
        self.assertEqual(items[0].title, "user/repo")

    def test_parse_reddit(self):
        items = parse_reddit_payload({
            "data": {"children": [{"data": {
                "title": "Post",
                "permalink": "/r/programming/comments/1/",
                "url": "https://example.com/post",
                "selftext": "body",
                "subreddit": "programming",
            }}]}
        })
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "reddit/programming")

    def test_parse_rss(self):
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>T</title>
          <item><title>One</title><link>https://example.com/1</link><description><![CDATA[<p>desc</p>]]></description></item>
        </channel></rss>"""
        items = parse_rss_text(rss)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "One")
        self.assertEqual(items[0].summary, "desc")

    def test_parse_atom(self):
        atom = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Two</title><link href="https://example.com/2"/>
            <summary>summary</summary></entry>
        </feed>"""
        items = parse_rss_text(atom)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Two")


if __name__ == "__main__":
    unittest.main()