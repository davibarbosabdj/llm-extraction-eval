"""Relatório em Markdown e gráficos a partir das métricas."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .schema import FIELDS, RESULTADOS  # noqa: E402

COR = {"base": "#4C78A8", "alt": "#F58518", "ruim": "#E45756", "ok": "#54A24B", "cinza": "#9AA0A6"}
_NOME_CAMPO = {
    "resultado": "resultado", "data_emissao": "data de emissão", "data_validade": "data de validade",
    "avaliador": "avaliador", "registro_profissional": "registro", "restricoes": "restrições",
}


def _pct(x, casas: int = 1) -> str:
    return "—" if x is None else f"{100 * x:.{casas}f}%"


def _ic(par) -> str:
    return f"[{100 * par[0]:.1f}; {100 * par[1]:.1f}]"


def _tabela(cabecalho: list[str], linhas: list[list[str]]) -> str:
    out = ["| " + " | ".join(cabecalho) + " |", "| " + " | ".join("---" for _ in cabecalho) + " |"]
    out += ["| " + " | ".join(str(c) for c in l) + " |" for l in linhas]
    return "\n".join(out)


def write_report(metrics: dict, run_name: str, out_dir: str | Path, extra_note: str = "") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    _plot_fields(metrics, run_name, out / "campos.png")
    _plot_groups(metrics, run_name, out / "grupos.png")
    if metrics.get("gate"):
        _plot_gate(metrics, run_name, out / "portao.png")

    m = metrics
    L = [f"# Relatório de avaliação: {run_name}", ""]
    if extra_note:
        L += [extra_note, ""]
    L += [
        f"- Documentos avaliados: **{m['n_docs']}**",
        f"- Documentos com todos os campos corretos: **{_pct(m['doc_exato'])}** (IC 95%: {_ic(m['doc_exato_ic95'])})",
        f"- Resultado (apto/inapto/com restrições) correto: **{_pct(m['resultado_acuracia'])}** "
        f"(IC 95%: {_ic(m['resultado_acuracia_ic95'])})",
        f"- **Falso apto** (laudo inapto lido como apto): {m['falso_apto']['n']} de {m['falso_apto']['de']} "
        f"({_pct(m['falso_apto']['taxa'])})",
        f"- Falso inapto (laudo apto lido como inapto): {m['falso_inapto']['n']} de {m['falso_inapto']['de']} "
        f"({_pct(m['falso_inapto']['taxa'])})",
        f"- Execuções com erro: {m['n_erro_execucao']}; documentos sem previsão: {m['n_sem_previsao']}",
        "",
        "O erro mais caro neste problema é o **falso apto**: um laudo inapto liberado como apto.",
        "",
        "## Desempenho por campo",
        "",
    ]
    linhas = []
    for f in FIELDS:
        c = m["campos"][f]
        linhas.append([_NOME_CAMPO[f], _pct(c["acuracia"]), _ic(c["acuracia_ic95"]), _pct(c["precisao"]),
                       _pct(c["revocacao"]), _pct(c["f1"]), _pct(c["taxa_alucinacao"]), _pct(c["taxa_omissao"]),
                       c["errado"]])
    L.append(_tabela(["campo", "acurácia", "IC 95%", "precisão", "revocação", "F1", "alucinação", "omissão",
                      "valores errados"], linhas))
    L += ["", "![campos](campos.png)", "", "## Matriz de confusão do resultado", "",
          "Linhas: gabarito. Colunas: previsto.", ""]
    cols = [*RESULTADOS, "outro"]
    L.append(_tabela(["gabarito \\ previsto", *cols],
                     [[t, *[m["matriz_resultado"][t][p] for p in cols]] for t in RESULTADOS]))
    L += ["", "## Onde o extrator erra", "",
          "Acerto do documento inteiro (todos os campos) e do resultado, por layout e por armadilha. "
          "Uma armadilha só tem sentido comparada aos outros grupos; os grupos se sobrepõem.", ""]
    grupos = m["grupos"]
    L.append(_tabela(["grupo", "n", "documento exato", "resultado correto"],
                     [[g, v["n"], _pct(v["doc_exato"]), _pct(v["resultado"])] for g, v in grupos.items()]))
    L += ["", "![grupos](grupos.png)", ""]

    if m.get("gate"):
        L += ["## Portão de qualidade", "",
              "O portão aceita uma extração quando o esquema é válido e o trecho citado como evidência existe no "
              "documento com similaridade acima do limiar. A tabela mostra o que passa em cada limiar e quão certo "
              "é o resultado entre os aceitos.", ""]
        linhas = []
        for c in m["gate"]["curva"]:
            if c["limiar"] in (0.0, 0.5, 0.8, 0.9, 0.95, 1.0):
                linhas.append([f"{c['limiar']:.2f}", _pct(c["cobertura"]), _pct(c["acerto_aceitos"]),
                               c["erros_aceitos"], _pct(c["erros_barrados"])])
        L.append(_tabela(["limiar", "cobertura (aceitos)", "resultado correto entre aceitos",
                          "erros que passaram", "erros barrados"], linhas))
        L += ["", "![portao](portao.png)", ""]

    u = m["uso"]
    L += ["## Custo e latência", ""]
    L.append(f"- Tokens de entrada: {u['prompt_tokens']:,}; de saída: {u['completion_tokens']:,}")
    L.append(f"- Latência média por documento: {u['latencia_media_s'] * 1000:.1f} ms; p95: "
             f"{u['latencia_p95_s'] * 1000:.1f} ms")
    if u["docs_em_cache"]:
        L.append(f"- Documentos servidos do cache (sem custo e sem latência medida): {u['docs_em_cache']}")
    L.append(f"- Custo estimado: {u['custo']:.4f} {u['moeda'] or ''}" if u["custo"] is not None
             else "- Custo: não calculado (preencha `pricing.yaml` com os preços do seu deployment)")

    L += ["", "## Exemplos de erro", ""]
    if m["erros_exemplos"]:
        L.append(_tabela(["documento", "campo", "desfecho", "gabarito", "previsto", "layout"],
                         [[e["doc_id"], e["campo"], e["desfecho"], e["gabarito"], e["previsto"], e["template"]]
                          for e in m["erros_exemplos"][:25]]))
    else:
        L.append("Nenhum erro.")
    path = out / "report.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


def _plot_fields(m: dict, run_name: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    nomes = [_NOME_CAMPO[f] for f in FIELDS]
    acc = [100 * m["campos"][f]["acuracia"] for f in FIELDS]
    lo = [100 * m["campos"][f]["acuracia"] - 100 * m["campos"][f]["acuracia_ic95"][0] for f in FIELDS]
    hi = [100 * m["campos"][f]["acuracia_ic95"][1] - 100 * m["campos"][f]["acuracia"] for f in FIELDS]
    ax.barh(nomes, acc, xerr=[lo, hi], color=COR["base"], capsize=3)
    ax.set_xlim(0, 100)
    ax.set_xlabel("acurácia (%) com IC 95%")
    ax.set_title(f"Acurácia por campo: {run_name}")
    ax.invert_yaxis()
    for i, v in enumerate(acc):
        ax.text(min(v + 1.5, 93), i, f"{v:.0f}%", va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _plot_groups(m: dict, run_name: str, path: Path) -> None:
    grupos = [(g, v) for g, v in m["grupos"].items()]
    grupos.sort(key=lambda x: x[1]["doc_exato"])
    fig, ax = plt.subplots(figsize=(7.5, max(3.5, 0.32 * len(grupos) + 1)))
    ax.barh([g for g, _ in grupos], [100 * v["doc_exato"] for _, v in grupos], color=COR["base"])
    ax.set_xlim(0, 100)
    ax.set_xlabel("documentos com todos os campos corretos (%)")
    ax.set_title(f"Acerto por layout e armadilha: {run_name}")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _plot_gate(m: dict, run_name: str, path: Path) -> None:
    curva = [c for c in m["gate"]["curva"] if c["acerto_aceitos"] is not None]
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot([100 * c["cobertura"] for c in curva], [100 * c["acerto_aceitos"] for c in curva],
            marker="o", ms=3, color=COR["base"])
    ax.set_xlabel("cobertura: % dos documentos aceitos pelo portão")
    ax.set_ylabel("resultado correto entre aceitos (%)")
    ax.set_title(f"Cobertura x acerto: {run_name}")
    ax.set_ylim(0, 102)
    ax.set_xlim(0, 102)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def write_comparison(runs: dict[str, dict], out_dir: str | Path) -> Path:
    """Compara várias execuções lado a lado (tabela e gráfico)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    L = ["# Comparação de extratores", ""]
    cab = ["extrator", "documento exato", "IC 95%", "resultado correto", "falso apto", "latência média"]
    linhas = []
    for nome, m in runs.items():
        linhas.append([nome, _pct(m["doc_exato"]), _ic(m["doc_exato_ic95"]), _pct(m["resultado_acuracia"]),
                       f"{m['falso_apto']['n']}/{m['falso_apto']['de']}",
                       f"{m['uso']['latencia_media_s'] * 1000:.1f} ms"])
    L.append(_tabela(cab, linhas))
    L += ["", "## Acurácia por campo", ""]
    L.append(_tabela(["campo", *runs.keys()],
                     [[_NOME_CAMPO[f], *[_pct(m["campos"][f]["acuracia"]) for m in runs.values()]] for f in FIELDS]))
    L += ["", "![comparacao](comparacao.png)", ""]
    (out / "comparison.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    fig, ax = plt.subplots(figsize=(8, 4.2))
    largura = 0.8 / max(1, len(runs))
    cores = [COR["cinza"], COR["alt"], COR["base"], COR["ok"], COR["ruim"]]
    for k, (nome, m) in enumerate(runs.items()):
        xs = [i + k * largura for i in range(len(FIELDS))]
        ax.bar(xs, [100 * m["campos"][f]["acuracia"] for f in FIELDS], width=largura, label=nome,
               color=cores[k % len(cores)])
    ax.set_xticks([i + largura * (len(runs) - 1) / 2 for i in range(len(FIELDS))])
    ax.set_xticklabels([_NOME_CAMPO[f] for f in FIELDS], rotation=20, ha="right")
    ax.set_ylabel("acurácia (%)")
    ax.set_ylim(0, 118)
    ax.legend(fontsize=8, loc="upper center", ncol=len(runs))
    ax.set_title("Acurácia por campo e extrator")
    fig.tight_layout()
    fig.savefig(out / "comparacao.png", dpi=140)
    plt.close(fig)
    return out / "comparison.md"
