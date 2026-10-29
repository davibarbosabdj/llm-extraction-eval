"""Utilitários de texto."""

from __future__ import annotations

import unicodedata


def strip_accents(s: str) -> str:
    """Remove acentos de uma string."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def fold(s: str) -> str:
    """Minúsculas e sem acentos, **preservando o comprimento**.

    Como cada caractere vira exatamente um caractere, os índices do texto dobrado
    valem também para o texto original. Isso permite buscar em `fold(texto)` e
    recortar o trecho correspondente no texto original.
    """
    out = []
    for ch in s:
        base = unicodedata.normalize("NFD", ch)[0]
        low = base.lower()
        out.append(low if len(low) == 1 else base)
    return "".join(out)


def collapse_ws(s: str) -> str:
    """Troca qualquer sequência de espaços e quebras de linha por um espaço."""
    return " ".join(s.split())
