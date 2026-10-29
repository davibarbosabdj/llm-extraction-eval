"""Gerador de laudos de aptidão técnica **sintéticos** com gabarito.

Nenhum dado real é usado. Nomes, clínicas, empresas e registros são inventados e
combinados ao acaso. Cada laudo nasce de um gabarito (os valores corretos), e o
texto é escrito a partir dele em um de seis layouts. Alguns layouts trazem
armadilhas que costumam derrubar extratores simples: o resultado marcado numa
caixa de seleção, histórico de avaliações anteriores, negação ("não sendo
considerado inapto"), datas que não são a de emissão, boilerplate que cita
"inapto" e ruído de OCR.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from dataclasses import dataclass
from pathlib import Path

from .dates import add_months, format_date
from .schema import RESULTADOS

TEMPLATES = ("formal", "narrativo", "tabela", "checkbox", "historico", "ocr")

_NOMES_F = ["Ana", "Beatriz", "Carla", "Daniela", "Elisa", "Fernanda", "Gabriela", "Helena",
            "Isabela", "Juliana", "Karina", "Larissa", "Mariana", "Natália", "Patrícia", "Renata"]
_NOMES_M = ["André", "Bruno", "Carlos", "Diego", "Eduardo", "Fábio", "Gustavo", "Henrique",
            "Igor", "João", "Leonardo", "Marcelo", "Nelson", "Otávio", "Rafael", "Thiago"]
_SOBRENOMES = ["Almeida", "Barros", "Cavalcante", "Dantas", "Esteves", "Farias", "Guedes", "Holanda",
               "Lima", "Macedo", "Nogueira", "Oliveira", "Pinheiro", "Queiroz", "Rocha", "Sampaio",
               "Teixeira", "Uchoa", "Vasconcelos", "Xavier"]
_CLINICAS = ["Clínica Vitale Psicologia", "Centro de Avaliação Horizonte", "Instituto Núcleo Saúde Ocupacional",
             "Espaço Equilíbrio Psicologia", "Clínica Prisma Avaliações", "Centro Psicológico Aurora"]
_EMPRESAS = ["Alfa Segurança Patrimonial", "Guardião Vigilância Ltda", "Escudo Serviços de Segurança",
             "Bastião Vigilância e Transporte", "Atalaia Segurança Privada"]
_RESTRICOES = [
    "uso obrigatório de lentes corretivas",
    "restrição ao trabalho em turno noturno",
    "restrição ao porte de arma de fogo",
    "necessidade de reavaliação em 6 meses",
    "restrição a postos de contato direto com o público",
]
_MESES_EXT = {6: "seis", 12: "doze", 24: "vinte e quatro"}
_RES_ROTULO = {"apto": "Apto", "inapto": "Inapto", "apto_com_restricoes": "Apto com restrições"}


@dataclass
class Doc:
    doc_id: str
    template: str
    tags: list[str]
    split: str
    text: str
    truth: dict


# ---------------------------------------------------------------- contexto

def _nome(rng: random.Random, genero: str) -> str:
    primeiros = _NOMES_F if genero == "f" else _NOMES_M
    s1, s2 = rng.sample(_SOBRENOMES, 2)
    return f"{rng.choice(primeiros)} {s1} {s2}"


def _contexto(rng: random.Random) -> dict:
    resultado = rng.choices(RESULTADOS, weights=[0.60, 0.22, 0.18])[0]
    emissao = dt.date(2023, 1, 2) + dt.timedelta(days=rng.randint(0, 1300))
    meses = rng.choice([6, 12, 12, 24])
    tem_validade = rng.random() > (0.55 if resultado == "inapto" else 0.07)
    genero_av = rng.choice("fm")
    tem_registro = rng.random() > 0.06
    restricao = rng.choice(_RESTRICOES) if resultado == "apto_com_restricoes" else None
    avaliador = _nome(rng, genero_av)
    registro = f"CRP 11/{rng.randint(10000, 39999)}"
    truth = {
        "resultado": resultado,
        "data_emissao": emissao.isoformat(),
        "data_validade": add_months(emissao, meses).isoformat() if tem_validade else None,
        "avaliador": avaliador,
        "registro_profissional": registro if tem_registro else None,
        "restricoes": restricao,
    }
    return {
        "truth": truth,
        "emissao": emissao,
        "avaliacao": emissao - dt.timedelta(days=rng.randint(1, 6)),
        "nascimento": dt.date(rng.randint(1965, 2003), rng.randint(1, 12), rng.randint(1, 28)),
        "meses": meses,
        "tem_validade": tem_validade,
        "candidato": _nome(rng, rng.choice("fm")),
        "clinica": rng.choice(_CLINICAS),
        "empresa": rng.choice(_EMPRESAS),
        "titulo_av": "Dra." if genero_av == "f" else "Dr.",
        "avaliador": avaliador,
        "registro": registro,
        "tem_registro": tem_registro,
        "restricao": restricao,
        "estilo_data": rng.choices(["num_slash", "num_dash", "extenso", "num_slash2"], weights=[5, 2, 2, 1])[0],
    }


def _data(c: dict, chave: str) -> str:
    return format_date(c[chave], c["estilo_data"])


def _validade_data(c: dict) -> dt.date:
    return add_months(c["emissao"], c["meses"])


def _outro_resultado(rng: random.Random, atual: str) -> str:
    return rng.choice([r for r in RESULTADOS if r != atual])


def _res_texto(resultado: str, estilo: str = "upper") -> str:
    texto = _RES_ROTULO[resultado]
    if estilo == "upper":
        return texto.upper()
    if estilo == "abrev":
        return texto.replace("com", "c/").upper()
    return texto


def _linha_validade(c: dict, rng: random.Random, rotulo: str, tags: list[str], vazio: str | None) -> str | None:
    """Linha de validade: data absoluta, prazo relativo, ou ausência."""
    if not c["tem_validade"]:
        return f"{rotulo}: {vazio}" if vazio else None
    if rng.random() < 0.25:
        tags.append("validade_relativa")
        return f"{rotulo}: {c['meses']} ({_MESES_EXT[c['meses']]}) meses a contar da data de emissão"
    return f"{rotulo}: {format_date(_validade_data(c), c['estilo_data'])}"


def _boilerplate(rng: random.Random, tags: list[str]) -> list[str]:
    if rng.random() < 0.3:
        tags.append("boilerplate")
        return ["Em caso de resultado inapto, o candidato poderá solicitar reavaliação em até 30 dias.", ""]
    return []


def _assinatura(c: dict, sep: str = "\n") -> str:
    partes = f"{c['titulo_av']} {c['avaliador']}"
    if c["tem_registro"]:
        partes += f"{sep}{c['registro']}"
    return partes


# ---------------------------------------------------------------- layouts

def _formal(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    linhas = [
        c["clinica"].upper(),
        "LAUDO DE APTIDÃO TÉCNICA PARA EXERCÍCIO DA FUNÇÃO DE VIGILANTE",
        "",
        f"Candidato: {c['candidato']}",
        f"Data de nascimento: {_data(c, 'nascimento')}",
        f"Data da avaliação: {_data(c, 'avaliacao')}",
        f"Data de emissão: {_data(c, 'emissao')}",
        "",
        "Metodologia: entrevista, testes psicológicos e observação comportamental.",
        "",
        *_boilerplate(rng, tags),
        "CONCLUSÃO",
        f"O(a) candidato(a) foi considerado(a) {_res_texto(r)} para o exercício da função.",
        f"Restrições: {c['restricao'] or 'Nenhuma'}",
    ]
    validade = _linha_validade(c, rng, "Validade", tags, "não consta")
    if validade:
        linhas.append(validade)
    linhas += ["", _assinatura(c)]
    return "\n".join(linhas)


def _narrativo(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    d_em, d_av, d_nasc = _data(c, "emissao"), _data(c, "avaliacao"), _data(c, "nascimento")
    paragrafo = (
        f"Em {d_em}, no âmbito do processo seletivo da empresa {c['empresa']}, o(a) candidato(a) "
        f"{c['candidato']}, nascido(a) em {d_nasc}, foi submetido(a) à avaliação psicológica realizada em {d_av}."
    )
    if rng.random() < 0.35:
        tags.append("historico")
        anterior = _outro_resultado(rng, r)
        ano = c["emissao"].year - rng.randint(1, 2)
        rotulo = _res_texto(anterior, "title").lower()
        paragrafo += f" Em avaliação anterior, realizada em {ano}, havia sido considerado(a) {rotulo}."
    if r == "apto":
        if rng.random() < 0.4:
            tags.append("negacao")
            conclusao = ("conclui-se que não foram identificados impedimentos, "
                         "não sendo o(a) candidato(a) considerado(a) inapto(a) para a função pretendida")
        else:
            conclusao = "conclui-se que o(a) candidato(a) está apto(a) para a função pretendida"
    elif r == "inapto":
        if rng.random() < 0.4:
            tags.append("negacao")
            conclusao = ("embora tenha apresentado bom desempenho em raciocínio, o(a) candidato(a) "
                         "não atende aos requisitos e é considerado(a) inapto(a) para a função pretendida")
        else:
            conclusao = "conclui-se que o(a) candidato(a) está inapto(a) para a função pretendida"
    else:
        conclusao = "conclui-se que o(a) candidato(a) está apto(a), com restrições, para a função pretendida"
    partes = [paragrafo, "", f"Considerando os resultados obtidos nos instrumentos aplicados, {conclusao}."]
    if c["restricao"]:
        partes.append(f"Restrição: {c['restricao']}.")
    if c["tem_validade"]:
        if rng.random() < 0.5:
            tags.append("validade_relativa")
            partes.append(f"O presente laudo é válido por {c['meses']} ({_MESES_EXT[c['meses']]}) meses "
                          "a contar da data de emissão.")
        else:
            partes.append(f"Validade do laudo: {format_date(_validade_data(c), c['estilo_data'])}.")
    partes += ["", f"{_assinatura(c, sep=' – ')}"]
    return f"{c['clinica']}\nLaudo psicológico de aptidão técnica\n\n" + "\n".join(partes)


def _tabela(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    linhas = [
        f"{c['clinica'].upper()} | LAUDO DE APTIDÃO TÉCNICA",
        "-" * 52,
        f"NOME .......... {c['candidato']}",
        f"DT. NASC. ..... {_data(c, 'nascimento')}",
        f"DT. AVALIAÇÃO . {_data(c, 'avaliacao')}",
        f"EMITIDO EM .... {_data(c, 'emissao')}",
        *_boilerplate(rng, tags),
        f"PARECER ....... {_res_texto(r, rng.choice(['upper', 'abrev']))}",
        f"RESTRIÇÕES .... {c['restricao'] or '-'}",
    ]
    validade = _linha_validade(c, rng, "VÁLIDO ATÉ", tags, "-")
    if validade:
        if "validade_relativa" in tags:
            validade = f"VALIDADE ...... {c['meses']} meses a partir da emissão"
        else:
            validade = validade.replace("VÁLIDO ATÉ:", "VÁLIDO ATÉ ....")
        linhas.append(validade)
    ass = f"RESP. TÉCNICO . {c['titulo_av']} {c['avaliador']}"
    if c["tem_registro"]:
        ass += f" / {c['registro']}"
    linhas.append(ass)
    return "\n".join(linhas)


def _checkbox(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    opcoes = list(RESULTADOS)
    rng.shuffle(opcoes)
    abre, fecha, marca = rng.choice([("[", "]", "X"), ("(", ")", "x")])
    caixas = "    ".join(
        f"{abre}{marca if o == r else ' '}{fecha} {_RES_ROTULO[o]}" for o in opcoes
    )
    linhas = [
        f"LAUDO DE APTIDÃO TÉCNICA — {c['clinica']}",
        f"Candidato: {c['candidato']}",
        f"Emitido em: {_data(c, 'emissao')}   (Avaliado em: {_data(c, 'avaliacao')})",
        "",
        "RESULTADO:",
        caixas,
    ]
    if c["restricao"]:
        linhas.append(f"Restrição: {c['restricao']}")
    validade = _linha_validade(c, rng, "Validade", tags, None)
    if validade:
        linhas.append(validade)
    linhas += ["", f"Assinado: {_assinatura(c, sep=' ')}"]
    return "\n".join(linhas)


def _historico(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    n = rng.randint(1, 3)
    anteriores = [_outro_resultado(rng, r)] + [rng.choice(RESULTADOS) for _ in range(n - 1)]
    datas = sorted(c["emissao"] - dt.timedelta(days=rng.randint(200, 1200)) for _ in range(n))
    linhas = [
        "LAUDO DE APTIDÃO TÉCNICA",
        f"Candidato: {c['candidato']}",
        f"Data de emissão: {_data(c, 'emissao')}",
        "",
        "HISTÓRICO DE AVALIAÇÕES",
    ]
    for d, res in zip(datas, anteriores):
        linhas.append(f" - {format_date(d, c['estilo_data'])}: {_res_texto(res)}")
    linhas += [
        "",
        f"AVALIAÇÃO ATUAL ({_data(c, 'avaliacao')})",
        f"Resultado: {_res_texto(r)}",
        f"Restrições: {c['restricao'] or 'Nenhuma'}",
    ]
    validade = _linha_validade(c, rng, "Validade", tags, None)
    if validade:
        linhas.append(validade)
    linhas += ["", f"Responsável: {_assinatura(c, sep=' - ')}"]
    return "\n".join(linhas)


def _ocr_ruido(texto: str, rng: random.Random, nivel: float = 0.02) -> str:
    """Simula um laudo escaneado: caixa alta, acentos perdidos, trocas O/0 e 1/l, espaços e quebras."""
    if rng.random() < 0.5:
        texto = texto.upper()
    sem_acento = {"Á": "A", "À": "A", "Â": "A", "Ã": "A", "É": "E", "Ê": "E", "Í": "I", "Ó": "O",
                  "Ô": "O", "Õ": "O", "Ú": "U", "Ç": "C", "á": "a", "à": "a", "â": "a", "ã": "a",
                  "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ç": "c"}
    saida = []
    for ch in texto:
        if ch in sem_acento and rng.random() < 0.35:
            saida.append(sem_acento[ch])
        elif ch == "O" and rng.random() < nivel:
            saida.append("0")
        elif ch == "0" and rng.random() < nivel:
            saida.append("O")
        elif ch == "1" and rng.random() < nivel:
            saida.append("l")
        elif ch == " " and rng.random() < nivel:
            saida.append("  ")
        elif ch == "\n" and rng.random() < 0.04:
            saida.append(" ")
        else:
            saida.append(ch)
    return "".join(saida)


def _ocr(c: dict, rng: random.Random, tags: list[str]) -> str:
    base = _formal(c, rng, tags) if rng.random() < 0.5 else _tabela(c, rng, tags)
    return _ocr_ruido(base, rng)


_LAYOUTS = {
    "formal": _formal, "narrativo": _narrativo, "tabela": _tabela,
    "checkbox": _checkbox, "historico": _historico, "ocr": _ocr,
}


# ------------------------------------------------- layouts novos (holdout)
# Escritos depois de congelar as regras, com vocabulário e estrutura diferentes
# ("ressalvas", "laudo expedido em", "vigência", cabeçalhos numerados, carta sem
# título profissional). Servem para medir generalização a formatos inéditos.

TEMPLATES_NOVOS = ("formulario", "carta", "ficha")


def _res_ressalvas(resultado: str) -> str:
    return {"apto": "APTO", "inapto": "INAPTO", "apto_com_restricoes": "APTO COM RESSALVAS"}[resultado]


def _formulario(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    if c["tem_validade"]:
        if rng.random() < 0.5:
            tags.append("validade_relativa")
            validade = f"Prazo de validade: {c['meses']} meses a partir da data de expedição do laudo"
        else:
            validade = f"Validade até: {format_date(_validade_data(c), c['estilo_data'])}"
    else:
        validade = "Prazo de validade: não definido"
    registro = f"Psicólogo(a) – {c['registro']}" if c["tem_registro"] else "Psicólogo(a)"
    return "\n".join([
        "FORMULÁRIO DE AVALIAÇÃO PSICOLÓGICA – FAP-02",
        c["clinica"],
        "",
        "1. IDENTIFICAÇÃO",
        f"   1.1 Examinando: {c['candidato']}",
        f"   1.2 Nascimento: {_data(c, 'nascimento')}",
        "2. DATAS",
        f"   2.1 Aplicação dos testes: {_data(c, 'avaliacao')}",
        f"   2.2 Laudo expedido em: {_data(c, 'emissao')}",
        "3. PARECER FINAL",
        f"   Situação do examinando: {_res_ressalvas(r)}",
        f"   Ressalvas: {c['restricao'] or 'não há'}",
        "4. VALIDADE",
        f"   {validade}",
        "5. RESPONSÁVEL TÉCNICO",
        f"   {c['avaliador']}",
        f"   {registro}",
    ])


def _carta(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    if r == "apto":
        frase = "foi considerado(a) apto(a) para a função de vigilante"
    elif r == "inapto":
        frase = "foi considerado(a) inapto(a) para a função de vigilante"
    else:
        frase = (f"foi considerado(a) apto(a) com ressalvas para a função de vigilante, "
                 f"com a seguinte ressalva: {c['restricao']}")
    corpo = [
        f"Fortaleza, {_data(c, 'emissao')}.",
        "",
        f"À {c['empresa']}",
        f"Assunto: resultado de avaliação psicológica – {c['candidato']}",
        "",
        "Prezados,",
        "",
        f"Informamos que, em avaliação realizada em {_data(c, 'avaliacao')}, o(a) candidato(a) {frase}.",
    ]
    if c["tem_validade"]:
        if rng.random() < 0.5:
            tags.append("validade_relativa")
            corpo.append(f"Este parecer tem prazo de validade de {c['meses']} meses.")
        else:
            corpo.append(f"Este parecer é válido até {format_date(_validade_data(c), c['estilo_data'])}.")
    corpo += ["", "Atenciosamente,", c["avaliador"]]
    corpo.append(f"Psicólogo(a) – {c['registro']}" if c["tem_registro"] else "Psicólogo(a)")
    return "\n".join(corpo)


def _ficha(c: dict, rng: random.Random, tags: list[str]) -> str:
    r = c["truth"]["resultado"]
    rotulo = {"apto": "APTO(A)", "inapto": "INAPTO(A)", "apto_com_restricoes": "APTO(A) COM RESTRIÇÕES"}[r]
    if c["tem_validade"]:
        if rng.random() < 0.5:
            tags.append("validade_relativa")
            vigencia = f"{c['meses']} meses a contar da data do laudo"
        else:
            vigencia = f"até {format_date(_validade_data(c), c['estilo_data'])}"
    else:
        vigencia = "—"
    prof = f"Psic. {c['avaliador']}" + (f" ({c['registro']})" if c["tem_registro"] else "")
    return "\n".join([
        "| Campo | Valor |",
        "|---|---|",
        f"| Identificação | {c['candidato']} |",
        f"| Data do laudo | {_data(c, 'emissao')} |",
        f"| Data da avaliação | {_data(c, 'avaliacao')} |",
        f"| Conclusão | Candidato(a) considerado(a) {rotulo} |",
        f"| Restrições | {c['restricao'] or '—'} |",
        f"| Vigência | {vigencia} |",
        f"| Profissional | {prof} |",
    ])


_LAYOUTS_NOVOS = {"formulario": _formulario, "carta": _carta, "ficha": _ficha}


def generate_holdout(n: int = 120, seed: int = 43) -> list[Doc]:
    """Laudos com layouts inéditos. Usa um gerador de números aleatórios próprio, então
    adicionar ou remover o holdout não altera os laudos de dev e test."""
    rng = random.Random(seed)
    docs = []
    for i in range(n):
        c = _contexto(rng)
        template = TEMPLATES_NOVOS[i % len(TEMPLATES_NOVOS)]
        tags = [template, "layout_novo"]
        texto = _LAYOUTS_NOVOS[template](c, rng, tags)
        if c["truth"]["data_validade"] is None:
            tags.append("sem_validade")
        if c["truth"]["registro_profissional"] is None:
            tags.append("sem_registro")
        docs.append(Doc(f"laudo_h{i:04d}", template, sorted(set(tags)), "holdout", texto, c["truth"]))
    return docs


# ---------------------------------------------------------------- dataset

def generate_dataset(n: int = 400, seed: int = 42) -> list[Doc]:
    """Gera `n` laudos. Um a cada cinco vai para 'dev' (ajuste de regras e prompts); o resto é 'test'."""
    rng = random.Random(seed)
    docs: list[Doc] = []
    for i in range(n):
        c = _contexto(rng)
        template = TEMPLATES[i % len(TEMPLATES)]
        tags = [template]
        texto = _LAYOUTS[template](c, rng, tags)
        if c["truth"]["data_validade"] is None:
            tags.append("sem_validade")
        if c["truth"]["registro_profissional"] is None:
            tags.append("sem_registro")
        docs.append(Doc(
            doc_id=f"laudo_{i:04d}",
            template=template,
            tags=sorted(set(tags)),
            split="dev" if i % 5 == 0 else "test",
            text=texto,
            truth=c["truth"],
        ))
    # Embaralha a ordem de apresentação para o template não seguir o índice.
    rng.shuffle(docs)
    return docs


def save_dataset(docs: list[Doc], out_dir: str | Path) -> None:
    out = Path(out_dir)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    with (out / "labels.jsonl").open("w", encoding="utf-8") as f:
        for d in sorted(docs, key=lambda d: d.doc_id):
            (out / "docs" / f"{d.doc_id}.txt").write_text(d.text, encoding="utf-8")
            f.write(json.dumps(
                {"doc_id": d.doc_id, "template": d.template, "tags": d.tags,
                 "split": d.split, "truth": d.truth}, ensure_ascii=False) + "\n")


def load_dataset(data_dir: str | Path, split: str | None = None) -> list[Doc]:
    base = Path(data_dir)
    docs = []
    with (base / "labels.jsonl").open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if split and rec["split"] != split:
                continue
            text = (base / "docs" / f"{rec['doc_id']}.txt").read_text(encoding="utf-8")
            docs.append(Doc(rec["doc_id"], rec["template"], rec["tags"], rec["split"], text, rec["truth"]))
    return docs
