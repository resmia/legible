from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class PageSignals:
    has_title: bool = False
    h1_count: int = 0
    has_language: bool = False
    has_meta_description: bool = False
    images_missing_alt: int = 0


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.signals = PageSignals()

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "html":
            if attrs_dict.get("lang"):
                self.signals.has_language = True

        if tag == "title":
            self.signals.has_title = True

        if tag == "h1":
            self.signals.h1_count += 1

        if tag == "meta":
            if attrs_dict.get("name", "").lower() == "description":
                if attrs_dict.get("content"):
                    self.signals.has_meta_description = True

        if tag == "img":
            if "alt" not in attrs_dict:
                self.signals.images_missing_alt += 1


def inspect_page(html: str) -> PageSignals:
    parser = PageParser()
    parser.feed(html)
    return parser.signals