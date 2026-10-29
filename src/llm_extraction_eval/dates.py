"""Leitura e escrita de datas em português (numéricas e por extenso)."""

from __future__ import annotations

import calendar
import datetime as dt
import re

from .text import fold

MESES_NOME = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NUM = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?!\d)")
_EXT = re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})(?!\d)")


def _make(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[int, int, dt.date]]:
    """Acha todas as datas do texto. Devolve (início, fim, data) ordenado por posição.

    Os índices valem para o texto original (a busca usa `fold`, que preserva o comprimento).
    """
    folded = fold(text)
    found: list[tuple[int, int, dt.date]] = []
    for m in _ISO.finditer(folded):
        d = _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append((m.start(), m.end(), d))
    for m in _NUM.finditer(folded):
        year = int(m.group(3))
        if year < 100:
            year += 2000
        d = _make(year, int(m.group(2)), int(m.group(1)))
        if d:
            found.append((m.start(), m.end(), d))
    for m in _EXT.finditer(folded):
        month = _MESES.get(m.group(2))
        if month:
            d = _make(int(m.group(3)), month, int(m.group(1)))
            if d:
                found.append((m.start(), m.end(), d))
    found.sort(key=lambda x: x[0])
    clean: list[tuple[int, int, dt.date]] = []
    last_end = -1
    for start, end, d in found:
        if start >= last_end:
            clean.append((start, end, d))
            last_end = end
    return clean


def parse_date(value: str | None) -> str | None:
    """Converte uma data escrita de vários jeitos para AAAA-MM-DD, ou None."""
    if value is None:
        return None
    dates = find_dates(str(value))
    return dates[0][2].isoformat() if dates else None


def add_months(d: dt.date, months: int) -> dt.date:
    """Soma meses a uma data, ajustando o dia ao fim do mês quando preciso."""
    year_shift, month0 = divmod(d.month - 1 + months, 12)
    year, month = d.year + year_shift, month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def format_date(d: dt.date, style: str) -> str:
    """Escreve a data no estilo pedido: num_slash, num_dash, num_slash2 ou extenso."""
    if style == "num_slash":
        return f"{d:%d/%m/%Y}"
    if style == "num_dash":
        return f"{d:%d-%m-%Y}"
    if style == "num_slash2":
        return f"{d:%d/%m/%y}"
    if style == "extenso":
        return f"{d.day} de {MESES_NOME[d.month - 1]} de {d.year}"
    raise ValueError(f"estilo de data desconhecido: {style}")
