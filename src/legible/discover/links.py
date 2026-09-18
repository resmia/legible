"""Published link structure for bounded discovery; no network activity."""
from dataclasses import dataclass
from html.parser import HTMLParser
import re


@dataclass(frozen=True)
class PublishedLink:
    href: str
    label: str
    context: str = ''
    navigation: bool = False


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.visible = []
        self.hidden = 0
        self.navigation = 0
        self.href = None
        self.label = []
        self.heading = ''
        self.heading_parts = []
        self.in_heading = False
        self.block = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template'}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {'nav', 'footer'}:
            self.navigation += 1
        if tag in {'p', 'li', 'tr', 'section'}:
            self.block = []
        if tag in {'h1', 'h2', 'h3', 'h4', 'title'}:
            self.in_heading = True
            self.heading_parts = []
        if tag == 'a':
            self.block = []
            self.href = dict(attrs).get('href')
            self.label = []

    def handle_data(self, text):
        if self.hidden:
            return
        self.visible.append(text)
        self.block.append(text)
        if self.href:
            self.label.append(text)
        if self.in_heading:
            self.heading_parts.append(text)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template'} and self.hidden:
            self.hidden -= 1
            return
        if self.hidden:
            return
        if tag == 'a' and self.href:
            self.links.append(PublishedLink(self.href, ' '.join(self.label),
                self.heading + ' ' + ' '.join(self.block)[-160:], bool(self.navigation)))
            self.href = None
        if tag in {'p', 'li', 'tr'} and self.links:
            # Attach the containing paragraph/list row, not unrelated page prose.
            last = self.links[-1]
            context = ' '.join(self.block)
            if last.label in context:
                self.links[-1] = PublishedLink(last.href, last.label, context[:500], last.navigation)
        if tag in {'h1', 'h2', 'h3', 'h4', 'title'}:
            self.heading = ' '.join(self.heading_parts)
            self.in_heading = False
        if tag in {'nav', 'footer'}:
            self.navigation = max(0, self.navigation - 1)


def published_links(text, media):
    if media in {'text/html', 'application/xhtml+xml'}:
        parser = Links()
        parser.feed(text)
        parser.close()
        links = parser.links
        visible = '\n'.join(parser.visible)
    elif media in {'text/plain', 'text/markdown'}:
        visible = text
        links = []
        for line in text.splitlines():
            for match in re.finditer(r'\[([^]\n]+)\]\(([^)\s]+)\)', line):
                links.append(PublishedLink(match[2], match[1], line[:500]))
    else:
        return []
    # Plain published locations need explicit integration context on their line.
    for line in visible.splitlines():
        if re.search(r'canonical|machine.readable|API (?:base|contract)|llms|OpenAPI|Swagger', line, re.I):
            for match in re.finditer(r'https?://[^\s<>"`]+|/[\w./-]*llms(?:-full)?\.txt', line):
                links.append(PublishedLink(match[0].rstrip('.,;):'), 'Published integration location', line[:500]))
    return links
