import pytest

from llm_extraction_eval.gate import evidence_similarity, gate_curve, gate_score, schema_problems
from llm_extraction_eval.metrics import bootstrap_ci, compute_metrics, field_outcome

TEXTO = ("LAUDO\nCONCLUSÃO\nO(a) candidato(a) foi considerado(a) INAPTO para o exercício da função.\n"
         "Data de emissão: 12/03/2025")


def test_field_outcome_cinco_desfechos():
    assert field_outcome("resultado", "apto", "APTO") == "tp"
    assert field_outcome("restricoes", None, None) == "tn"
    assert field_outcome("restricoes", None, "algo") == "alucinacao"
    assert field_outcome("restricoes", "algo", None) == "omissao"
    assert field_outcome("resultado", "apto", "inapto") == "errado"
    assert field_outcome("restricoes", "x", "Nenhuma") == "omissao"  # "Nenhuma" conta como ausente


def _label(doc_id, resultado, **extra):
    truth = {"resultado": resultado, "data_emissao": "2025-03-12", "data_validade": None,
             "avaliador": "Maria Souza", "registro_profissional": "CRP 11/1", "restricoes": None}
    truth.update(extra)
    return {"doc_id": doc_id, "template": "formal", "tags": ["formal"], "truth": truth}


def _pred(resultado, **extra):
    campos = {"resultado": resultado, "data_emissao": "2025-03-12", "data_validade": None,
              "avaliador": "Dra. Maria Souza", "registro_profissional": "CRP 11/1", "restricoes": None}
    campos.update(extra)
    return {"fields": campos, "evidencia_resultado": None}


def test_compute_metrics_contagens_e_falso_apto():
    labels = [_label("a", "apto"), _label("b", "inapto"), _label("c", "inapto"), _label("d", "apto")]
    preds = {
        "a": _pred("apto"),
        "b": _pred("apto"),                      # falso apto
        "c": _pred("inapto", restricoes="x"),    # alucinação em restrições
        "d": _pred("inapto"),                    # falso inapto
    }
    m = compute_metrics(labels, preds, n_boot=200)
    assert m["n_docs"] == 4
    assert m["resultado_acuracia"] == 0.5
    assert m["doc_exato"] == 0.25
    assert m["falso_apto"] == {"n": 1, "de": 2, "taxa": 0.5}
    assert m["falso_inapto"] == {"n": 1, "de": 2, "taxa": 0.5}
    assert m["campos"]["resultado"]["tp"] == 2 and m["campos"]["resultado"]["errado"] == 2
    assert m["campos"]["restricoes"]["alucinacao"] == 1 and m["campos"]["restricoes"]["tn"] == 3
    assert m["campos"]["avaliador"]["acuracia"] == 1.0
    assert m["matriz_resultado"]["inapto"]["apto"] == 1


def test_precisao_revocacao_f1():
    labels = [_label("a", "apto", restricoes="r1"), _label("b", "apto", restricoes="r2"),
              _label("c", "apto", restricoes="r3"), _label("d", "apto")]
    preds = {
        "a": _pred("apto", restricoes="r1"),     # tp
        "b": _pred("apto", restricoes="outra"),  # errado
        "c": _pred("apto", restricoes=None),     # omissão
        "d": _pred("apto", restricoes="inventada"),  # alucinação
    }
    c = compute_metrics(labels, preds, n_boot=50)["campos"]["restricoes"]
    assert (c["tp"], c["errado"], c["omissao"], c["alucinacao"]) == (1, 1, 1, 1)
    assert c["precisao"] == pytest.approx(1 / 3)   # tp / (tp + alucinação + errado)
    assert c["revocacao"] == pytest.approx(1 / 3)  # tp / (tp + omissão + errado)
    assert c["f1"] == pytest.approx(1 / 3)


def test_previsao_ausente_e_erro_de_execucao_contam_como_omissao():
    labels = [_label("a", "apto"), _label("b", "apto")]
    preds = {"a": {"fields": {k: None for k in _pred("apto")["fields"]}, "error": "Timeout"}}
    m = compute_metrics(labels, preds, n_boot=50)
    assert m["n_erro_execucao"] == 1 and m["n_sem_previsao"] == 1
    assert m["campos"]["resultado"]["omissao"] == 2 and m["doc_exato"] == 0.0


def test_bootstrap_ci_contem_a_media_e_encolhe_com_n():
    pouco = [1, 0] * 10
    muito = [1, 0] * 500
    lo1, hi1 = bootstrap_ci(pouco, seed=1)
    lo2, hi2 = bootstrap_ci(muito, seed=1)
    assert lo1 <= 0.5 <= hi1 and lo2 <= 0.5 <= hi2
    assert (hi2 - lo2) < (hi1 - lo1)
    assert bootstrap_ci([1] * 30) == (1.0, 1.0)


def test_custo_so_com_precos():
    labels = [_label("a", "apto")]
    p = _pred("apto")
    p.update(prompt_tokens=2000, completion_tokens=500, latency_s=0.5)
    m = compute_metrics(labels, {"a": p}, pricing={"input_per_1k": 0.01, "output_per_1k": 0.03, "currency": "USD"},
                        n_boot=20)
    assert m["uso"]["custo"] == pytest.approx(2 * 0.01 + 0.5 * 0.03)
    assert compute_metrics(labels, {"a": p}, pricing={"input_per_1k": None, "output_per_1k": None},
                           n_boot=20)["uso"]["custo"] is None


# ------------------------------------------------------------------ portão

def test_evidence_similarity():
    assert evidence_similarity("considerado(a) INAPTO para o exercício", TEXTO) == 1.0
    assert evidence_similarity("considerado(a) apto para o exercício", TEXTO) > 0.85       # troca pequena
    assert evidence_similarity("texto que não existe em lugar nenhum do laudo", TEXTO) < 0.6
    assert evidence_similarity(None, TEXTO) == 0.0
    assert evidence_similarity("", TEXTO) == 0.0


def test_schema_problems():
    ok = {"resultado": "inapto", "data_emissao": "2025-03-12", "data_validade": None, "restricoes": None}
    assert schema_problems(ok) == []
    assert "resultado_invalido" in schema_problems({**ok, "resultado": "talvez"})
    assert "emissao_ausente" in schema_problems({**ok, "data_emissao": None})
    assert "emissao_invalida" in schema_problems({**ok, "data_emissao": "ontem"})
    assert "validade_antes_da_emissao" in schema_problems({**ok, "data_validade": "2024-01-01"})
    assert "restricao_ausente" in schema_problems({**ok, "resultado": "apto_com_restricoes"})
    assert schema_problems({**ok, "resultado": "apto_com_restricoes", "restricoes": "lentes"}) == []


def test_gate_score_rejeita_evidencia_inventada_e_incoerente():
    campos = {"resultado": "inapto", "data_emissao": "2025-03-12", "data_validade": None, "restricoes": None}
    assert gate_score(TEXTO, campos, "foi considerado(a) INAPTO para o exercício da função") == 1.0
    assert gate_score(TEXTO, campos, "a candidata demonstrou plena capacidade INAPTO") < 0.8   # citação inventada
    assert gate_score(TEXTO, {**campos, "resultado": "apto"}, "Data de emissão: 12/03/2025") == 0.0  # incoerente
    assert gate_score(TEXTO, {**campos, "data_emissao": None}, "INAPTO") == 0.0                      # esquema
    assert gate_score(TEXTO, campos, None) == 0.0


def test_gate_nao_deixa_inapto_passar_como_apto():
    campos = {"resultado": "apto", "data_emissao": "2025-03-12", "data_validade": None, "restricoes": None}
    # "apto" citando uma frase de INAPTO: o "apt" de "inapto" não pode contar.
    assert gate_score(TEXTO, campos, "foi considerado(a) INAPTO para o exercício da função") == 0.0
    # A negação de inapto sustenta "apto".
    negada = "não sendo o(a) candidato(a) considerado(a) inapto(a) para a função"
    texto_negado = f"Conclusão: não foram identificados impedimentos, {negada}.\nData de emissão: 12/03/2025"
    assert gate_score(texto_negado, campos, negada) > 0.9
    # Mas "não atende... inapto" não é negação de inapto.
    ruim = "não atende aos requisitos e é considerado(a) inapto(a)"
    assert gate_score(f"{ruim}\nData de emissão: 12/03/2025", campos, ruim) == 0.0


def test_gate_curve():
    scores = [1.0, 1.0, 0.9, 0.4]
    ok = [True, True, False, False]
    curva = {c["limiar"]: c for c in gate_curve(scores, ok, [0.0, 0.5, 0.95])}
    assert curva[0.0]["cobertura"] == 1.0 and curva[0.0]["acerto_aceitos"] == 0.5
    assert curva[0.5]["cobertura"] == 0.75 and curva[0.5]["erros_barrados"] == 0.5
    assert curva[0.95]["acerto_aceitos"] == 1.0 and curva[0.95]["erros_barrados"] == 1.0
    assert gate_curve([0.1], [True], [0.9])[0]["acerto_aceitos"] is None
