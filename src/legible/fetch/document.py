"""Pure views of retained content; never fetch or discard the original body."""
from dataclasses import dataclass
from html.parser import HTMLParser
import re


@dataclass(frozen=True)
class TextBlock:
    kind: str
    text: str


@dataclass(frozen=True)
class Document:
    text: str
    blocks: tuple[TextBlock, ...]


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
        self.stack = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template'}:
            self.hidden += 1
        if not self.hidden and tag in {'title', 'h1', 'h2', 'h3', 'h4', 'p', 'li', 'tr', 'pre'}:
            self.stack.append((tag, []))

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            for _, parts in self.stack:
                parts.append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template'} and self.hidden:
            self.hidden -= 1
            return
        if not self.hidden and self.stack and self.stack[-1][0] == tag:
            kind, parts = self.stack.pop()
            text = ''.join(parts) if kind == 'pre' else ' '.join(parts)
            self.blocks.append(TextBlock(kind, text.strip()))


def extract_document(raw, media):
    if media in {'text/html', 'application/xhtml+xml'}:
        parser = _DocumentParser()
        parser.feed(raw)
        parser.close()
        return Document(' '.join(' '.join(parser.parts).split()), tuple(parser.blocks))
    if media in {'text/plain', 'text/markdown', 'application/json', 'application/yaml', 'text/yaml', 'application/x-yaml'}:
        return Document(' '.join(raw.split()), tuple(TextBlock('paragraph', p) for p in raw.split('\n\n') if p.strip()))
    return None


BLOCK_MESSAGE = re.compile(r'^(?:403\s*[-:]?\s*)?(?:access denied|verify you are human|captcha|enable javascript|sign in to continue)\b', re.I)


def is_blocked_document(document):
    """A response-level challenge is different from documentation of a 403."""
    headings = [b.text.strip() for b in document.blocks if b.kind in {'title', 'h1'}]
    if any(BLOCK_MESSAGE.search(text) for text in headings):
        return True
    return (len(document.text.split()) < 80 and bool(BLOCK_MESSAGE.search(document.text))
            and not any(b.kind in {'pre', 'tr'} for b in document.blocks))
