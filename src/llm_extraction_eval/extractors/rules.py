"""Duas linhas de base sem LLM, em degraus de sofisticação.

- `NaiveRules`: pega a primeira menção a "apto/inapto" e a primeira e a última data.
- `ContextualRules`: lê rótulos, caixas de seleção, negação e a avaliação atual.

Servem de régua. Um extrator com LLM só se justifica se ganhar das regras no que
elas erram, e a comparação com cada degrau mostra de onde vem o ganho.
"""

from __future__ import annotations

import re
import time

from ..dates import add_months, find_dates
from ..schema import FIELDS
from ..text import collapse_ws, fold
from .base import ExtractionResult

_RES_RE = re.compile(r"\b(inapt|apt)[oa]\b")
_RESTR_AFTER = re.compile(r"\s*(?:\(a\))?\s*,?\s*(?:com|c/)\s*restric")
_AVALIADOR_RE = re.compile(r"\bdra?\.\s*([^\n(,/|–—\-]+)", re.IGNORECASE)
_REGISTRO_RE = re.compile(r"\bcrp\W{0,3}(\d{1,2}\s*/\s*\d{3,6})")


def _linha_em(text: str, pos: int) -> str:
    ini = text.rfind("\n", 0, pos) + 1
    fim = text.find("\n", pos)
    return text[ini: fim if fim != -1 else len(text)].strip()


def _classe(folded: str, m: re.Match) -> str:
    """Classe de resultado a partir de uma menção apto/inapto."""
    if m.group(1) == "inapt":
        return "inapto"
    if _RESTR_AFTER.match(folded, m.end()):
        return "apto_com_restricoes"
    return "apto"


def _avaliador(text: str) -> str | None:
    m = _AVALIADOR_RE.search(text)
    if not m:
        return None
    nome = re.split(r"\bcrp\b", m.group(1), flags=re.IGNORECASE)[0]
    return collapse_ws(nome) or None


def _registro(folded: str) -> str | None:
    m = _REGISTRO_RE.search(folded)
    if not m:
        return None
    numero = re.sub(r"\s+", "", m.group(1))
    return f"CRP {numero}"


class NaiveRules:
    name = "rules_naive"

    def extract(self, doc_id: str, text: str) -> ExtractionResult:
        t0 = time.perf_counter()
        res = ExtractionResult(doc_id=doc_id, extractor=self.name)
        folded = fold(text)
        fields = {k: None for k in FIELDS}

        m = _RES_RE.search(folded)
        if m:
            fields["resultado"] = _classe(folded, m)
            res.evidencia_resultado = _linha_em(text, m.start())

        datas = find_dates(text)
        if datas:
            fields["data_emissao"] = datas[0][2].isoformat()
        if len(datas) > 1:
            fields["data_validade"] = datas[-1][2].isoformat()

        fields["avaliador"] = _avaliador(text)
        fields["registro_profissional"] = _registro(folded)
        res.fields = fields
        res.latency_s = time.perf_counter() - t0
        return res


# ------------------------------------------------------------------ contextual

_CHECK_RE = re.compile(
    r"(?:[\[\(]\s*x\s*[\]\)]|☒|☑)\s*(inapto|apto\s*(?:com|c/)\s*restric\w*|apto)"
)
_NEGACAO_RE = re.compile(
    r"nao\s+(?:sendo\s+)?(?:o\(a\)\s+candidato\(a\)\s+)?(?:foi\s+|e\s+|esta\s+)?"
    r"(?:considerad[oa]\(?a?\)?\s+)?inapt"
)
_PRIORIDADE = ("conclu", "parecer", "resultado", "considerad")
_NULOS = {"", "-", "--", "nenhuma", "nenhum", "nao consta"}


_FIM_FRASE = re.compile(r"\n|;|(?<!\.)\.(?=\s|$)")


def _frases(trecho: str):
    """Limites (início, fim) de cada frase. Não quebra nos pontilhados de layouts em tabela."""
    ini = 0
    for m in _FIM_FRASE.finditer(trecho):
        yield ini, m.start()
        ini = m.end()
    yield ini, len(trecho)


def _classe_na_frase(frase: str) -> str | None:
    """Classe do resultado dentro de uma frase (já dobrada), tratando negação."""
    m = _RES_RE.search(frase)
    if not m:
        return None
    if m.group(1) == "inapt":
        return "apto" if _NEGACAO_RE.search(frase) else "inapto"
    return "apto_com_restricoes" if _RESTR_AFTER.match(frase, m.end()) else "apto"


class ContextualRules:
    name = "rules_contextual"

    def extract(self, doc_id: str, text: str) -> ExtractionResult:
        t0 = time.perf_counter()
        res = ExtractionResult(doc_id=doc_id, extractor=self.name)
        folded = fold(text)
        fields = {k: None for k in FIELDS}

        fields["resultado"], res.evidencia_resultado = self._resultado(text, folded)
        emissao, validade = self._datas(text, folded)
        fields["data_emissao"] = emissao.isoformat() if emissao else None
        fields["data_validade"] = validade.isoformat() if validade else None
        fields["avaliador"] = _avaliador(text)
        fields["registro_profissional"] = _registro(folded)
        fields["restricoes"] = self._restricoes(text, folded)
        res.fields = fields
        res.latency_s = time.perf_counter() - t0
        return res

    # -- resultado
    def _resultado(self, text: str, folded: str) -> tuple[str | None, str | None]:
        m = _CHECK_RE.search(folded)
        if m:
            marcado = m.group(1)
            classe = "inapto" if marcado.startswith("inapto") else (
                "apto_com_restricoes" if "restric" in marcado else "apto")
            return classe, text[m.start(): m.end()].strip()

        inicio = folded.rfind("avaliacao atual")
        escopo = folded[inicio:] if inicio != -1 else folded
        offset = inicio if inicio != -1 else 0

        candidatas = []
        for ini, fim in _frases(escopo):
            frase = escopo[ini:fim]
            if "anterior" in frase or "historico" in frase:
                continue
            classe = _classe_na_frase(frase)
            if classe:
                candidatas.append((frase, classe, offset + ini, offset + fim))
        if not candidatas:
            return None, None
        prioritarias = [c for c in candidatas if any(p in c[0] for p in _PRIORIDADE)]
        frase, classe, ini, fim = (prioritarias or candidatas)[-1]
        return classe, text[ini:fim].strip()

    # -- datas
    def _datas(self, text: str, folded: str):
        rotuladas = []
        for ini, fim, d in find_dates(text):
            # Só a linha corrente, até 32 caracteres antes da data.
            contexto = folded[max(0, ini - 32): ini].split("\n")[-1]
            if "nasc" in contexto:
                rotulo = "nasc"
            elif "avalia" in contexto or "realizada em" in contexto:
                rotulo = "aval"
            elif "valid" in contexto:
                rotulo = "valid"
            elif "emiss" in contexto or "emitido" in contexto:
                rotulo = "emissao"
            else:
                rotulo = None
            rotuladas.append((rotulo, d, ini))

        emissao = next((d for r, d, _ in rotuladas if r == "emissao"), None)
        if emissao is None:
            emissao = next((d for r, d, _ in rotuladas if r is None), None)
        validade = next((d for r, d, _ in rotuladas if r == "valid"), None)
        if validade is None and emissao is not None:
            m = re.search(r"valid[oa]\s+por\s+(\d+)\s*(?:\([a-z ]+\)\s*)?meses", folded)
            m = m or re.search(r"validade\W+(\d+)\s*(?:\([a-z ]+\)\s*)?meses", folded)
            if m:
                validade = add_months(emissao, int(m.group(1)))
        return emissao, validade

    # -- restrições
    def _restricoes(self, text: str, folded: str) -> str | None:
        # [ \t] em vez de \s: o valor tem de estar na mesma linha do rótulo.
        for m in re.finditer(r"restric\w*[ \t]*[:.\-…]+[ \t]*([^\n]*)", folded):
            valor = text[m.start(1): m.end(1)].strip(" .")
            if fold(valor).strip(" .") not in _NULOS:
                return valor
        return None
