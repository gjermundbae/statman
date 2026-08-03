"""Article -> notat.md.

Notatet er arbeidsformen: det som ligger i sakspakken og leses av den som
gjorde analysen. Det rendres herfra og ikke for hånd, så teksten på den
publiserte siden er den samme teksten — ikke en variant av den.
"""

from __future__ import annotations

from pathlib import Path

from statman import catalog as catalog_mod
from statman.publish.article import (
    Article,
    Figure,
    Findings,
    Prose,
    Stats,
    Table,
)


def render(article: Article) -> str:
    """Hele notatet som én streng, med avsluttende linjeskift."""
    lines: list[str] = [f"# {article.title}", ""]
    if article.lead:
        lines += [article.lead, ""]

    for section in article.sections:
        lines += [f"## {section.title}", ""]
        for block in section.blocks:
            lines += _block(block)

    if article.caveats:
        lines += ["## Forbehold", ""]
        for key in article.caveats:
            lines += [catalog_mod.metric(key).note(), ""]

    if article.files:
        lines += ["## Filer", ""]
        for name, beskrivelse in article.files:
            lines.append(f"- `{name}` — {beskrivelse}")
        lines.append("")

    if article.provenance:
        lines += ["## Kvittering", ""]
        bredde = max(len(k) for k in article.provenance)
        lines.append("```")
        for etikett, verdi in article.provenance.items():
            lines.append(f"{etikett.ljust(bredde)}  {verdi}")
        lines += ["```", ""]

    return "\n".join(lines).rstrip("\n") + "\n"


def write(article: Article, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(article), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
def _block(block: object) -> list[str]:
    if isinstance(block, Prose):
        return [block.text, ""]

    if isinstance(block, Findings):
        return [*(f"- {item}" for item in block.items), ""]

    if isinstance(block, Stats):
        return [
            *(
                f"- **{stat.value}** — {stat.label}"
                + (f" ({stat.note})" if stat.note else "")
                for stat in block.items
            ),
            "",
        ]

    if isinstance(block, Figure):
        tekst = block.caption or block.alt
        lines = [f"![{block.alt}]({block.file})", ""]
        if tekst:
            kilde = f" {block.source}" if block.source else ""
            lines += [f"*{tekst}*{kilde}", ""]
        return lines

    if isinstance(block, Table):
        justering = ["--:" if a == "right" else "---" for a in block.alignment()]
        lines = [
            "| " + " | ".join(block.columns) + " |",
            "|" + "|".join(justering) + "|",
            *("| " + " | ".join(row) + " |" for row in block.rows),
            "",
        ]
        if block.caption:
            lines += [f"*{block.caption}*", ""]
        return lines

    raise TypeError(f"Vet ikke hvordan {type(block).__name__} skrives som markdown")
