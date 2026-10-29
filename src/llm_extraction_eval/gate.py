"""Portão de qualidade: decide se uma extração pode seguir sem revisão.

A ideia vem de um padrão comum em produção: em vez de confiar cegamente na resposta
do modelo, confere-se se ela é coerente com o documento e rejeita-se o que parece
estranho (o item rejeitado é refeito ou vai para revisão humana).

Este portão usa três verificações:
1. **Esquema**: valores válidos, datas que existem, validade depois da emissão,
   restrição preenchida quando o resultado é "apto com restrições".
2. **Evidência ancorada**: o trecho citado como evidência do resultado realmente
   existe no documento (similaridade de 0 a 1).
3. **Coerência**: o trecho citado combina com o resultado. "Inapto" precisa citar
   "inapto"; "apto" precisa citar "apto" (a palavra, não o final de "inapto") ou a
   negação de inapto ("não sendo considerado inapto"). O portão mede coerência, não
   verdade: um laudo mal lido que cita uma frase real e coerente ainda passa.

A nota final é 0 se alguma verificação de esquema ou coerência falha, e a
similaridade da evidência caso contrário. `gate_curve` mostra o que acontece em
cada limiar: quanto do volume passa e quão certo é o que passa.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .dates import parse_date
from .schema import RESULTADOS, normalize_value
from .text import collapse_ws, fold


def evidence_similarity(evidence: str | None, text: str) -> float:
    """Quão bem `evidence` aparece em `text` (1.0 = trecho idêntico). Tolera pequenos desvios."""
    if not evidence:
        return 0.0
    e = collapse_ws(fold(evidence))
    t = collapse_ws(fold(text))
    if not e:
        return 0.0
    if e in t:
        return 1.0
    n = len(e)
    melhor = 0.0
    for janela in sorted({max(1, int(n * 0.9)), n, int(n * 1.1) + 1}):
        passo = max(1, janela // 8)
        for i in range(0, max(1, len(t) - janela + 1), passo):
            r = SequenceMatcher(None, e, t[i: i + janela], autojunk=False).ratio()
            if r > melhor:
                melhor = r
                if melhor >= 0.999:
                    return melhor
    return melhor


def schema_problems(fields: dict) -> list[str]:
    """Problemas de esquema/consistência numa extração. Lista vazia = tudo certo."""
    problemas = []
    resultado = normalize_value("resultado", fields.get("resultado"))
    if resultado not in RESULTADOS:
        problemas.append("resultado_invalido")
    emissao = parse_date(fields.get("data_emissao"))
    validade = parse_date(fields.get("data_validade"))
    if normalize_value("data_emissao", fields.get("data_emissao")) is None:
        problemas.append("emissao_ausente")
    elif emissao is None:
        problemas.append("emissao_invalida")
    if normalize_value("data_validade", fields.get("data_validade")) is not None and validade is None:
        problemas.append("validade_invalida")
    if emissao and validade and validade < emissao:
        problemas.append("validade_antes_da_emissao")
    if resultado == "apto_com_restricoes" and not normalize_value("restricoes", fields.get("restricoes")):
        problemas.append("restricao_ausente")
    return problemas


_INAPTO_NA_EVIDENCIA = re.compile(r"\binapt")
_APTO_NA_EVIDENCIA = re.compile(r"\bapt")
# "não foi considerado inapto", "não sendo o(a) candidato(a) considerado(a) inapto".
_NEGA_INAPTO = re.compile(
    r"\bnao\s+(?:sendo\s+)?(?:o\(a\)\s+candidato\(a\)\s+)?(?:foi\s+|e\s+|esta\s+)?"
    r"(?:considerad[oa]\(?a?\)?\s+)?inapt"
)


def evidencia_coerente(resultado: str | None, evidencia: str | None) -> bool:
    """O trecho citado sustenta o resultado declarado?"""
    ev = fold(evidencia or "")
    if resultado == "inapto":
        return bool(_INAPTO_NA_EVIDENCIA.search(ev))
    if resultado in ("apto", "apto_com_restricoes"):
        return bool(_APTO_NA_EVIDENCIA.search(ev) or _NEGA_INAPTO.search(ev))
    return False


def gate_score(text: str, fields: dict, evidence: str | None) -> float:
    """Nota de 0 a 1. Só extrações sem problemas e com evidência ancorada chegam perto de 1."""
    if schema_problems(fields):
        return 0.0
    resultado = normalize_value("resultado", fields.get("resultado"))
    if not evidencia_coerente(resultado, evidence):
        return 0.0
    return evidence_similarity(evidence, text)


def gate_curve(scores: list[float], resultado_ok: list[bool], thresholds: list[float]) -> list[dict]:
    """Para cada limiar: cobertura (fração aceita), acerto do resultado entre os aceitos e erros barrados."""
    n = len(scores)
    erros_total = sum(1 for ok in resultado_ok if not ok)
    curva = []
    for t in thresholds:
        aceitos = [i for i in range(n) if scores[i] >= t]
        certos = sum(1 for i in aceitos if resultado_ok[i])
        erros_aceitos = len(aceitos) - certos
        curva.append({
            "limiar": round(t, 4),
            "cobertura": len(aceitos) / n if n else 0.0,
            "acerto_aceitos": certos / len(aceitos) if aceitos else None,
            "erros_aceitos": erros_aceitos,
            "erros_barrados": (erros_total - erros_aceitos) / erros_total if erros_total else None,
        })
    return curva
