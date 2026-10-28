"""The public documentation the chat answers from: Markdown pages cut into passages, searched by words.

Search is BM25 over the passages, in pure Python: the corpus is a few hundred passages of our
own pages, so nothing heavier is needed, and the result is the same on every machine (the tests
check which page answers each question of the eval set). A visitor may write in Portuguese or
Spanish while the pages are in English, so a short list of their common words maps to English
search words before the search.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_PASSAGE = 1400
WORD = re.compile(r"[a-z0-9][a-z0-9.+-]*[a-z0-9]|[a-z0-9]", re.I)
HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

STOP = set(
    """a an and are as at be by can do does for from has have how i if in is it its me my of on or
    our so that the their them then there these this to we what when where which who why will
    with you your any all one o os as um uma de do da dos das em no na para com que se e é el la
    los las un una""".split()
)

# Visitors' words in Portuguese and Spanish, to the English words of the pages.
TRANSLATE = {
    "preço": "price free licence",
    "preco": "price free licence",
    "precio": "price free licence",
    "custa": "price free",
    "cuesta": "price free",
    "gratis": "free licence",
    "grátis": "free licence",
    "gratuito": "free licence",
    "licença": "licence license apache",
    "licencia": "licence license apache",
    "segurança": "security secure",
    "seguro": "secure security",
    "seguridad": "security secure",
    "instalar": "install installation",
    "instalação": "install installation",
    "instalacion": "install installation",
    "instalación": "install installation",
    "requisitos": "requirements server memory",
    "servidor": "server",
    "memória": "memory",
    "memoria": "memory",
    "disco": "disk",
    "nuvem": "cloud hosted",
    "nube": "cloud hosted",
    "dados": "data",
    "datos": "data",
    "alarmes": "alarms alarm",
    "alarmas": "alarms alarm",
    "malhas": "loops control loop",
    "malha": "loop control",
    "controle": "control",
    "lazos": "loops control loop",
    "válvula": "valve",
    "valvula": "valve",
    "modelos": "models model",
    "simulador": "simulator",
    "planta": "plant",
    "historiador": "historian",
    "painéis": "dashboards",
    "paineis": "dashboards",
    "tendências": "trends",
    "documentos": "documents",
    "relatórios": "reports",
    "relatorios": "reports",
    "usuários": "people users sign-in",
    "usuarios": "people users sign-in",
    "login": "sign-in",
    "senha": "password",
    "suporte": "support",
    "soporte": "support",
    "contato": "contact",
    "contacto": "contact",
    "aplicativo": "app",
    "aplicativos": "apps",
    "criar": "create build",
    "crear": "create build",
    "escrever": "write",
    "ia": "ai assistant language model",
    "llm": "llm language model assistant",
    "modelo": "model",
    "linguagem": "language",
    "offline": "offline",
    "escrita": "write writes",
    "escreve": "write writes",
    "sozinho": "own",
    "código": "code source",
    "codigo": "code source",
    "aberto": "open source",
    "abierto": "open source",
    "português": "portuguese language translation",
    "idioma": "language",
    "windows": "windows",
    "demonstração": "demo",
    "demonstracao": "demo",
    "demo": "demo",
    "tempo": "time minutes",
    "rápido": "fast minutes",
    "assinatura": "signature signed verify",
    "assinado": "signed signature",
    "firma": "signature signed verify",
    "verificar": "verify check",
    "adulterado": "tampered signature verify",
    "contribuir": "contribute contributing pull request",
    "contribuição": "contribute contributing",
    "método": "method",
    "metodo": "method",
    "exportar": "export",
    "atualização": "update upgrade",
    "atualizar": "update upgrade",
    "actualización": "update upgrade",
    "perder": "lose",
}


def words(text: str) -> list[str]:
    """Lower-case search words, with a plural's final s dropped and stop words left out."""
    out = []
    for raw in WORD.findall(text.lower()):
        if raw in STOP:
            continue
        if raw in TRANSLATE:
            out.extend(TRANSLATE[raw].split())
            continue
        if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        out.append(raw)
    return out


@dataclass(frozen=True)
class Passage:
    source: str  # path in the repository, e.g. docs/install.md
    title: str  # the page's title
    heading: str  # the section's heading path, "Install PlantCraft > What you need"
    text: str

    @property
    def label(self) -> str:
        return f"{self.title} › {self.heading}" if self.heading else self.title


def _clean(markdown: str) -> str:
    """Markdown without HTML tags, front images and repeated blank lines."""
    text = re.sub(r"<[^>]+>", "", markdown)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def passages_of(source: str, markdown: str) -> list[Passage]:
    """One page cut at its headings; a long section is cut again at its paragraphs."""
    title = source
    stack: list[str] = []
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_code = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else HEADING.match(line)
        if match:
            level, text = len(match.group(1)), match.group(2).strip()
            if level == 1:
                title, stack = text, []
                sections.append(("", []))
                continue
            stack = stack[: level - 2] + [text]
            sections.append((" › ".join(stack), []))
            continue
        sections[-1][1].append(line)
    out: list[Passage] = []
    for heading, lines in sections:
        body = _clean("\n".join(lines))
        if not body:
            continue
        chunk = ""
        for para in body.split("\n\n"):
            if chunk and len(chunk) + len(para) > MAX_PASSAGE:
                out.append(Passage(source, title, heading, chunk.strip()[: MAX_PASSAGE * 2]))
                chunk = ""
            chunk += para + "\n\n"
        if chunk.strip():
            out.append(Passage(source, title, heading, chunk.strip()[: MAX_PASSAGE * 2]))
    return out


class Knowledge:
    """The passages and their BM25 index. `core` passages go with every question."""

    K1 = 1.4
    B = 0.75

    def __init__(self, core: list[Passage], searched: list[Passage]):
        self.core = core
        self.searched = searched
        self._docs = [words(f"{p.title} {p.heading} {p.heading} {p.text}") for p in searched]
        self._tf = [Counter(d) for d in self._docs]
        self._avg = sum(len(d) for d in self._docs) / max(1, len(self._docs))
        df: Counter[str] = Counter()
        for d in self._tf:
            df.update(d.keys())
        n = len(self._docs)
        self._idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    @classmethod
    def from_repository(cls, root: Path, sources: Path | None = None) -> "Knowledge":
        listing = tomllib.loads((sources or root / "site/knowledge/sources.toml").read_text())

        def read(paths: list[str]) -> list[Passage]:
            out: list[Passage] = []
            for path in paths:
                out.extend(passages_of(path, (root / path).read_text(encoding="utf-8")))
            return out

        return cls(read(listing["core"]), read(listing["searched"]))

    @classmethod
    def load(cls, path: Path) -> "Knowledge":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Passage(**p) for p in data["core"]], [Passage(**p) for p in data["searched"]])

    def dump(self, path: Path) -> None:
        data = {
            "core": [asdict(p) for p in self.core],
            "searched": [asdict(p) for p in self.searched],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")

    def search(self, query: str, k: int = 6) -> list[Passage]:
        """The k passages that best match the query, best first; none when nothing matches."""
        terms = [w for w in words(query) if w in self._idf]
        if not terms:
            return []
        scores: list[tuple[float, int]] = []
        for i, tf in enumerate(self._tf):
            length = len(self._docs[i])
            score = 0.0
            for w in terms:
                f = tf.get(w, 0)
                if f:
                    norm = f + self.K1 * (1 - self.B + self.B * length / self._avg)
                    score += self._idf[w] * f * (self.K1 + 1) / norm
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return [self.searched[i] for _, i in scores[:k]]

    def sources(self) -> list[str]:
        return sorted({p.source for p in self.core + self.searched})


def plain_links(text: str) -> str:
    """Markdown links as their text, so the model does not copy repository-relative paths."""
    return LINK.sub(lambda m: m.group(1), text)
