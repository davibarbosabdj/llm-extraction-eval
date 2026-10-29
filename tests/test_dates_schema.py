import datetime as dt

from llm_extraction_eval.dates import add_months, find_dates, format_date, parse_date
from llm_extraction_eval.schema import normalize_value, values_equal
from llm_extraction_eval.text import fold


def test_fold_preserva_comprimento_e_remove_acentos():
    s = "Conclusão: APTO – Ação Çedilha"
    assert len(fold(s)) == len(s)
    assert fold(s) == "conclusao: apto – acao cedilha"


def test_parse_date_formatos():
    assert parse_date("12/03/2025") == "2025-03-12"
    assert parse_date("12-03-2025") == "2025-03-12"
    assert parse_date("12/03/25") == "2025-03-12"
    assert parse_date("5 de março de 2025") == "2025-03-05"
    assert parse_date("5 de MARCO de 2025") == "2025-03-05"
    assert parse_date("2025-03-12") == "2025-03-12"
    assert parse_date("sem data") is None
    assert parse_date(None) is None
    assert parse_date("31/02/2025") is None  # data inexistente


def test_find_dates_indices_valem_para_o_original():
    texto = "Emitido em 5 de março de 2025 e válido até 05/03/2026."
    achadas = find_dates(texto)
    assert [d.isoformat() for _, _, d in achadas] == ["2025-03-05", "2026-03-05"]
    ini, fim, _ = achadas[0]
    assert texto[ini:fim] == "5 de março de 2025"


def test_find_dates_nao_duplica_iso():
    assert len(find_dates("2025-03-12")) == 1


def test_add_months_fim_de_mes_e_bissexto():
    assert add_months(dt.date(2025, 1, 31), 1) == dt.date(2025, 2, 28)
    assert add_months(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)
    assert add_months(dt.date(2025, 3, 12), 12) == dt.date(2026, 3, 12)
    assert add_months(dt.date(2025, 11, 15), 6) == dt.date(2026, 5, 15)


def test_format_date_roundtrip():
    d = dt.date(2025, 3, 5)
    for estilo in ("num_slash", "num_dash", "extenso", "num_slash2"):
        assert parse_date(format_date(d, estilo)) == d.isoformat()


def test_normalize_resultado():
    for bruto in ("APTO C/ RESTRIÇÕES", "apto com restrições", "Apto(a) com restrições", "apto_com_restricoes"):
        assert normalize_value("resultado", bruto) == "apto_com_restricoes"
    for bruto in ("APTO", "Apto(a)", "apto"):
        assert normalize_value("resultado", bruto) == "apto"
    for bruto in ("INAPTO", "inapto(a)", "Inapto"):
        assert normalize_value("resultado", bruto) == "inapto"


def test_normalize_ausentes():
    for campo in ("restricoes", "data_validade", "registro_profissional"):
        for nulo in (None, "", "null", "-", "—", "Nenhuma", "não consta"):
            assert normalize_value(campo, nulo) is None
    assert normalize_value("restricoes", "não há") is None


def test_normalize_avaliador_e_registro():
    assert values_equal("avaliador", "Dra. Maria Souza", "MARIA SOUZA")
    assert values_equal("avaliador", "Psic. João Lima", "joao lima")
    assert not values_equal("avaliador", "Maria Souza", "Maria Sousa")
    assert values_equal("registro_profissional", "CRP 11/12345", "11/12345")
    assert values_equal("registro_profissional", "CRP-11/12345", "CRP 11/12345")
    assert not values_equal("registro_profissional", "CRP 11/12345", "CRP 11/12346")


def test_normalize_datas_e_restricoes():
    assert values_equal("data_emissao", "2025-03-12", "12/03/2025")
    assert not values_equal("data_emissao", "2025-03-12", "2025-03-13")
    assert values_equal("restricoes", "Uso obrigatório de lentes corretivas.", "uso obrigatorio de lentes corretivas")
