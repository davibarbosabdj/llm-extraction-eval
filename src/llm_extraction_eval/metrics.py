"""Métricas de avaliação de extração.

Para cada documento e campo, comparamos o valor previsto `p` com o gabarito `t`
(depois de normalizar). Há cinco desfechos:

- **tp**: ambos existem e são iguais.
- **tn**: ambos ausentes (o extrator acertou ao não preencher).
- **alucinação**: o gabarito é ausente, mas o extrator preencheu.
- **omissão**: o gabarito existe, mas o extrator deixou vazio.
- **errado**: ambos existem e são diferentes.

Precisão = tp / (tp + alucinação + errado). Revocação = tp / (tp + omissão + errado).
Um valor errado conta contra as duas, porque o extrator afirmou algo falso e também
deixou de afirmar o certo.
"""

from __future__ import annotations

import numpy as np

from .gate import gate_curve, gate_score
from .schema import FIELDS, RESULTADOS, normalize_value

LIMIARES_PADRAO = [round(x, 2) for x in np.arange(0.0, 1.0001, 0.05)]


def bootstrap_ci(valores, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """Intervalo de confiança percentil por bootstrap para a média de `valores` (0/1)."""
    x = np.asarray(valores, dtype=float)
    if len(x) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    medias = x[idx].mean(axis=1)
    return float(np.percentile(medias, 100 * alpha / 2)), float(np.percentile(medias, 100 * (1 - alpha / 2)))


def field_outcome(field: str, truth, pred) -> str:
    t, p = normalize_value(field, truth), normalize_value(field, pred)
    if t is None and p is None:
        return "tn"
    if t is None:
        return "alucinacao"
    if p is None:
        return "omissao"
    return "tp" if t == p else "errado"


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or (p + r) == 0:
        return None
    return 2 * p * r / (p + r)


def _percentil(valores: list[float], q: float) -> float:
    return float(np.percentile(valores, q)) if valores else 0.0


def compute_metrics(labels: list[dict], preds: dict[str, dict], texts: dict[str, str] | None = None,
                    pricing: dict | None = None, n_boot: int = 2000, seed: int = 0,
                    limiares: list[float] | None = None, max_erros: int = 60) -> dict:
    """Calcula todas as métricas. `labels` vem de labels.jsonl; `preds`, de predictions.jsonl."""
    n = len(labels)
    desfechos = {f: [] for f in FIELDS}
    doc_exato, resultado_ok = [], []
    erros_exemplos = []
    n_erro_execucao = n_sem_previsao = 0
    matriz = {t: {p: 0 for p in (*RESULTADOS, "outro")} for t in RESULTADOS}
    por_grupo: dict[str, dict] = {}
    falso_apto = falso_apto_de = 0
    falso_inapto = falso_inapto_de = 0
    scores = []

    for lab in labels:
        pred = preds.get(lab["doc_id"])
        if pred is None:
            n_sem_previsao += 1
            campos = {f: None for f in FIELDS}
            evidencia = None
        else:
            if pred.get("error"):
                n_erro_execucao += 1
            campos = pred.get("fields") or {f: None for f in FIELDS}
            evidencia = pred.get("evidencia_resultado")

        verdadeiro = lab["truth"]
        acertos = []
        for f in FIELDS:
            d = field_outcome(f, verdadeiro.get(f), campos.get(f))
            desfechos[f].append(d)
            acertos.append(d in ("tp", "tn"))
            if d not in ("tp", "tn") and len(erros_exemplos) < max_erros:
                erros_exemplos.append({"doc_id": lab["doc_id"], "campo": f, "desfecho": d,
                                       "gabarito": verdadeiro.get(f), "previsto": campos.get(f),
                                       "template": lab["template"], "tags": lab["tags"]})
        exato = all(acertos)
        r_ok = acertos[FIELDS.index("resultado")]
        doc_exato.append(exato)
        resultado_ok.append(r_ok)

        t_res = normalize_value("resultado", verdadeiro["resultado"])
        p_res = normalize_value("resultado", campos.get("resultado"))
        matriz[t_res][p_res if p_res in RESULTADOS else "outro"] += 1
        if t_res == "inapto":
            falso_apto_de += 1
            falso_apto += p_res in ("apto", "apto_com_restricoes")
        else:
            falso_inapto_de += 1
            falso_inapto += p_res == "inapto"

        for grupo in (f"template:{lab['template']}", *[f"tag:{t}" for t in lab["tags"] if t != lab["template"]]):
            g = por_grupo.setdefault(grupo, {"exato": [], "resultado": []})
            g["exato"].append(exato)
            g["resultado"].append(r_ok)

        if texts is not None and pred is not None:
            scores.append(gate_score(texts[lab["doc_id"]], campos, evidencia))
        else:
            scores.append(0.0)

    campos_metricas = {}
    for f in FIELDS:
        c = {k: desfechos[f].count(k) for k in ("tp", "tn", "alucinacao", "omissao", "errado")}
        acc_vec = [d in ("tp", "tn") for d in desfechos[f]]
        prec = _safe_div(c["tp"], c["tp"] + c["alucinacao"] + c["errado"])
        rev = _safe_div(c["tp"], c["tp"] + c["omissao"] + c["errado"])
        com_valor = c["tp"] + c["omissao"] + c["errado"]
        sem_valor = c["tn"] + c["alucinacao"]
        campos_metricas[f] = {
            **c,
            "acuracia": float(np.mean(acc_vec)),
            "acuracia_ic95": bootstrap_ci(acc_vec, n_boot, seed),
            "precisao": prec, "revocacao": rev, "f1": _f1(prec, rev),
            "taxa_alucinacao": _safe_div(c["alucinacao"], sem_valor),
            "taxa_omissao": _safe_div(c["omissao"], com_valor),
        }

    grupos = {
        g: {"n": len(v["exato"]), "doc_exato": float(np.mean(v["exato"])),
            "resultado": float(np.mean(v["resultado"]))}
        for g, v in sorted(por_grupo.items())
    }

    prompt_tokens = sum((p or {}).get("prompt_tokens", 0) for p in preds.values())
    completion_tokens = sum((p or {}).get("completion_tokens", 0) for p in preds.values())
    latencias = [p["latency_s"] for p in preds.values() if p.get("latency_s") and not p.get("cached")]
    custo = None
    if pricing and pricing.get("input_per_1k") is not None and pricing.get("output_per_1k") is not None:
        custo = (prompt_tokens / 1000 * pricing["input_per_1k"]
                 + completion_tokens / 1000 * pricing["output_per_1k"])

    gate = None
    if texts is not None:
        curva = gate_curve(scores, resultado_ok, limiares or LIMIARES_PADRAO)
        gate = {"curva": curva,
                "em_090": next((c for c in curva if abs(c["limiar"] - 0.90) < 1e-9), None),
                "em_095": next((c for c in curva if abs(c["limiar"] - 0.95) < 1e-9), None)}

    return {
        "n_docs": n,
        "n_sem_previsao": n_sem_previsao,
        "n_erro_execucao": n_erro_execucao,
        "doc_exato": float(np.mean(doc_exato)),
        "doc_exato_ic95": bootstrap_ci(doc_exato, n_boot, seed),
        "resultado_acuracia": float(np.mean(resultado_ok)),
        "resultado_acuracia_ic95": bootstrap_ci(resultado_ok, n_boot, seed),
        "falso_apto": {"n": int(falso_apto), "de": falso_apto_de, "taxa": _safe_div(falso_apto, falso_apto_de)},
        "falso_inapto": {"n": int(falso_inapto), "de": falso_inapto_de, "taxa": _safe_div(falso_inapto, falso_inapto_de)},
        "matriz_resultado": matriz,
        "campos": campos_metricas,
        "grupos": grupos,
        "uso": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latencia_media_s": float(np.mean(latencias)) if latencias else 0.0,
            "latencia_p95_s": _percentil(latencias, 95),
            "docs_em_cache": sum(1 for p in preds.values() if p.get("cached")),
            "custo": custo,
            "moeda": (pricing or {}).get("currency"),
        },
        "gate": gate,
        "erros_exemplos": erros_exemplos,
    }
