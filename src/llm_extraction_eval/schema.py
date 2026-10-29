"""Campos extraídos e regras de normalização para comparar valores."""

from __future__ import annotations

import re
from typing import Any

from .dates import parse_date
from .text import collapse_ws, fold

FIELDS = (
    "resultado",
    "data_emissao",
    "data_validade",
    "avaliador",
    "registro_profissional",
    "restricoes",
)
DATE_FIELDS = ("data_emissao", "data_validade")
RESULTADOS = ("apto", "inapto", "apto_com_restricoes")

# Textos que significam "campo ausente".
_NULL_WORDS = {
    "", "null", "none", "nan", "n/a", "na", "-", "--", "nenhuma", "nenhum",
    "nao consta", "nao informado", "sem restricoes", "sem restricao", "sem ressalvas",
    "nao ha", "nao ha restricoes", "nao definido", "—", "–", "inexistente",
}
_TITLES = {"dr", "dra", "doutor", "doutora", "psic", "psicologo", "psicologa", "sr", "sra"}


def normalize_resultado(value: str) -> str:
    s = re.sub(r"[^a-z/ ]", "", fold(value).replace("_", " "))
    s = collapse_ws(s)
    if re.search(r"\binapt", s):
        return "inapto"
    if re.search(r"\bapt", s):
        return "apto_com_restricoes" if "restric" in s else "apto"
    return s.replace(" ", "_")


def normalize_value(field: str, value: Any) -> str | None:
    """Leva o valor a uma forma canônica para comparação. None significa 'ausente'."""
    if value is None:
        return None
    s = str(value).strip()
    if fold(s).strip(" .") in _NULL_WORDS:
        return None
    if field == "resultado":
        return normalize_resultado(s)
    if field in DATE_FIELDS:
        return parse_date(s) or collapse_ws(fold(s))
    if field == "avaliador":
        tokens = re.sub(r"[^a-z ]", " ", fold(s)).split()
        tokens = [t for t in tokens if t not in _TITLES]
        return " ".join(tokens) or None
    if field == "registro_profissional":
        digits = re.sub(r"[^0-9/]", "", fold(s).replace("crp", ""))
        return digits or None
    if field == "restricoes":
        return collapse_ws(re.sub(r"[^a-z0-9 ]", " ", fold(s))) or None
    return collapse_ws(fold(s)) or None


def values_equal(field: str, a: Any, b: Any) -> bool:
    return normalize_value(field, a) == normalize_value(field, b)
