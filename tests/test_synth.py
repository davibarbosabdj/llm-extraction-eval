import re

from llm_extraction_eval.dates import find_dates
from llm_extraction_eval.schema import RESULTADOS, normalize_value
from llm_extraction_eval.synth import (TEMPLATES, TEMPLATES_NOVOS, generate_dataset, generate_holdout,
                                       load_dataset, save_dataset)
from llm_extraction_eval.text import fold


def test_geracao_e_deterministica():
    a = generate_dataset(60, seed=7)
    b = generate_dataset(60, seed=7)
    assert [(d.doc_id, d.text) for d in a] == [(d.doc_id, d.text) for d in b]
    c = generate_dataset(60, seed=8)
    assert [d.text for d in a] != [d.text for d in c]


def test_holdout_nao_altera_dev_e_test():
    antes = {d.doc_id: d.text for d in generate_dataset(60, seed=7)}
    generate_holdout(30, seed=8)
    depois = {d.doc_id: d.text for d in generate_dataset(60, seed=7)}
    assert antes == depois


def test_splits_e_layouts():
    docs = generate_dataset(120, seed=1)
    assert {d.split for d in docs} == {"dev", "test"}
    assert sum(d.split == "dev" for d in docs) == 24
    assert {d.template for d in docs} == set(TEMPLATES)
    novos = generate_holdout(30, seed=2)
    assert {d.template for d in novos} == set(TEMPLATES_NOVOS)
    assert all(d.split == "holdout" and "layout_novo" in d.tags for d in novos)


def test_gabarito_e_consistente():
    for d in generate_dataset(200, seed=3) + generate_holdout(60, seed=4):
        t = d.truth
        assert t["resultado"] in RESULTADOS
        if t["data_validade"]:
            assert t["data_validade"] > t["data_emissao"]
        if t["resultado"] == "apto_com_restricoes":
            assert t["restricoes"]
        else:
            assert t["restricoes"] is None
        assert ("sem_validade" in d.tags) == (t["data_validade"] is None)
        assert ("sem_registro" in d.tags) == (t["registro_profissional"] is None)


def test_texto_contem_o_que_o_gabarito_diz():
    """Fora do OCR (que degrada o texto de propósito), emissão, avaliador e restrição devem estar no texto."""
    for d in generate_dataset(200, seed=5) + generate_holdout(60, seed=6):
        if d.template == "ocr":
            continue
        datas = {x.isoformat() for _, _, x in find_dates(d.text)}
        assert d.truth["data_emissao"] in datas, d.doc_id
        assert fold(d.truth["avaliador"]) in fold(d.text), d.doc_id
        if d.truth["restricoes"]:
            assert fold(d.truth["restricoes"]) in fold(d.text), d.doc_id
        if d.truth["registro_profissional"]:
            assert d.truth["registro_profissional"] in d.text, d.doc_id


def test_checkbox_marca_a_opcao_do_gabarito():
    docs = [d for d in generate_dataset(200, seed=9) if d.template == "checkbox"]
    assert docs
    for d in docs:
        m = re.search(r"[\[\(]\s*[xX]\s*[\]\)]\s*(Inapto|Apto com restrições|Apto)", d.text)
        assert m, d.doc_id
        assert normalize_value("resultado", m.group(1)) == d.truth["resultado"]


def test_historico_tem_resultado_anterior_diferente_do_atual_no_texto():
    for d in generate_dataset(120, seed=10):
        if d.template == "historico":
            assert "HISTÓRICO DE AVALIAÇÕES" in d.text and "AVALIAÇÃO ATUAL" in d.text


def test_salvar_e_carregar(tmp_path):
    docs = generate_dataset(30, seed=11) + generate_holdout(6, seed=12)
    save_dataset(docs, tmp_path)
    todos = load_dataset(tmp_path)
    assert len(todos) == 36
    assert {d.doc_id: d.text for d in todos} == {d.doc_id: d.text for d in docs}
    assert all(d.split == "holdout" for d in load_dataset(tmp_path, "holdout"))
    assert len(load_dataset(tmp_path, "dev")) == 6
