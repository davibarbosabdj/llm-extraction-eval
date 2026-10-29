import json
from types import SimpleNamespace

import pytest

from llm_extraction_eval.extractors import AzureOpenAIExtractor, ContextualRules, NaiveRules
from llm_extraction_eval.extractors.azure_openai import load_prompt, parse_model_output
from llm_extraction_eval.schema import values_equal

FORMAL = """CLÍNICA TESTE
LAUDO DE APTIDÃO TÉCNICA

Candidato: Fulano de Tal
Data de nascimento: 01/02/1990
Data da avaliação: 10/03/2025
Data de emissão: 12/03/2025

Em caso de resultado inapto, o candidato poderá solicitar reavaliação em até 30 dias.

CONCLUSÃO
O(a) candidato(a) foi considerado(a) APTO COM RESTRIÇÕES para o exercício da função.
Restrições: uso obrigatório de lentes corretivas
Validade: 12 (doze) meses a contar da data de emissão

Dra. Maria Souza Lima
CRP 11/12345"""

NEGACAO = """Em 12/03/2025, o(a) candidato(a) Fulano, nascido(a) em 01/02/1990, foi submetido(a) à avaliação
realizada em 10/03/2025. Em avaliação anterior, realizada em 2023, havia sido considerado(a) inapto.
Considerando os resultados obtidos, conclui-se que não foram identificados impedimentos, não sendo o(a) candidato(a) considerado(a) inapto(a) para a função.
Validade do laudo: 12/03/2026.
Dr. Pedro Alves – CRP 11/22222"""

CHECKBOX = """LAUDO DE APTIDÃO TÉCNICA
Emitido em: 13/01/2025   (Avaliado em: 11/01/2025)
RESULTADO:
[ ] Inapto    [ ] Apto com restrições    [X] Apto
Assinado: Dr. Igor Xavier CRP 11/13893"""


def test_contextual_formal_com_boilerplate_e_validade_relativa():
    r = ContextualRules().extract("d1", FORMAL)
    f = r.fields
    assert f["resultado"] == "apto_com_restricoes"
    assert f["data_emissao"] == "2025-03-12"
    assert f["data_validade"] == "2026-03-12"
    assert values_equal("avaliador", f["avaliador"], "Maria Souza Lima")
    assert f["registro_profissional"] == "CRP 11/12345"
    assert values_equal("restricoes", f["restricoes"], "uso obrigatório de lentes corretivas")
    assert "APTO COM RESTRIÇÕES" in r.evidencia_resultado


def test_contextual_trata_negacao_e_ignora_historico():
    f = ContextualRules().extract("d2", NEGACAO).fields
    assert f["resultado"] == "apto"
    assert f["data_emissao"] == "2025-03-12"
    assert f["data_validade"] == "2026-03-12"


def test_contextual_le_checkbox():
    f = ContextualRules().extract("d3", CHECKBOX).fields
    assert f["resultado"] == "apto"
    assert f["data_emissao"] == "2025-01-13"
    assert f["data_validade"] is None


def test_naive_erra_onde_o_contextual_acerta():
    """Documenta por que a linha de base ingênua existe: ela cai nas armadilhas."""
    ingenuo = NaiveRules()
    assert ingenuo.extract("d1", FORMAL).fields["resultado"] == "inapto"  # pegou o boilerplate
    assert ingenuo.extract("d2", NEGACAO).fields["resultado"] == "inapto"  # pegou o histórico
    assert ingenuo.extract("d3", CHECKBOX).fields["resultado"] == "inapto"  # primeira opção, não a marcada
    assert ingenuo.extract("d1", FORMAL).fields["data_emissao"] == "1990-02-01"  # data de nascimento


# ------------------------------------------------------------------ parsing

def test_parse_model_output_json_limpo():
    campos, ev = parse_model_output(json.dumps({
        "resultado": "apto", "data_emissao": "2025-03-12", "data_validade": None,
        "avaliador": "Maria", "registro_profissional": "CRP 11/1", "restricoes": None,
        "evidencia_resultado": "considerado APTO"}))
    assert campos["resultado"] == "apto" and campos["data_validade"] is None
    assert ev == "considerado APTO"


def test_parse_model_output_tolera_cerca_de_codigo_e_texto():
    bruto = 'Claro!\n```json\n{"resultado": "inapto", "data_emissao": "2025-01-02"}\n```'
    campos, ev = parse_model_output(bruto)
    assert campos["resultado"] == "inapto" and campos["avaliador"] is None and ev is None


@pytest.mark.parametrize("ruim", ["", "sem json", "{quebrado", "[1, 2]"])
def test_parse_model_output_rejeita_lixo(ruim):
    with pytest.raises(ValueError):
        parse_model_output(ruim)


def test_prompts_carregam_e_tem_marcador_do_documento():
    for versao in ("v1", "v2"):
        sistema, usuario = load_prompt(versao)
        assert sistema and "{documento}" in usuario
    with pytest.raises(ValueError):
        load_prompt("v9")


# ------------------------------------------------------------------ Azure com cliente falso

class _Completions:
    def __init__(self, saidas):
        self.saidas = list(saidas)
        self.chamadas = []

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        item = self.saidas.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30))


def _cliente(saidas):
    comp = _Completions(saidas)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


BOM = json.dumps({"resultado": "apto", "data_emissao": "2025-01-13", "data_validade": None,
                  "avaliador": "Igor Xavier", "registro_profissional": "CRP 11/13893",
                  "restricoes": None, "evidencia_resultado": "[X] Apto"})


def test_azure_extrai_e_registra_uso(tmp_path):
    cliente, comp = _cliente([BOM])
    ex = AzureOpenAIExtractor(prompt_version="v2", deployment="meu-deploy", client=cliente, cache_dir=tmp_path)
    r = ex.extract("d3", CHECKBOX)
    assert r.error is None and r.fields["resultado"] == "apto"
    assert (r.prompt_tokens, r.completion_tokens) == (120, 30)
    chamada = comp.chamadas[0]
    assert chamada["model"] == "meu-deploy" and chamada["temperature"] == 0.0
    assert chamada["response_format"] == {"type": "json_object"}
    assert CHECKBOX in chamada["messages"][1]["content"]


def test_azure_usa_cache_e_nao_chama_de_novo(tmp_path):
    cliente, comp = _cliente([BOM])
    ex = AzureOpenAIExtractor(deployment="d", client=cliente, cache_dir=tmp_path)
    primeira = ex.extract("a", CHECKBOX)
    segunda = ex.extract("a", CHECKBOX)
    assert len(comp.chamadas) == 1
    assert not primeira.cached and segunda.cached
    assert segunda.fields == primeira.fields and segunda.prompt_tokens == 120


def test_azure_cache_muda_com_prompt_ou_deployment(tmp_path):
    cliente, comp = _cliente([BOM, BOM, BOM])
    AzureOpenAIExtractor(prompt_version="v1", deployment="d", client=cliente, cache_dir=tmp_path).extract("a", CHECKBOX)
    AzureOpenAIExtractor(prompt_version="v2", deployment="d", client=cliente, cache_dir=tmp_path).extract("a", CHECKBOX)
    AzureOpenAIExtractor(prompt_version="v2", deployment="outro", client=cliente, cache_dir=tmp_path).extract("a", CHECKBOX)
    assert len(comp.chamadas) == 3


def test_azure_retenta_apos_erro_transitorio(tmp_path):
    cliente, comp = _cliente([RuntimeError("429"), RuntimeError("503"), BOM])
    ex = AzureOpenAIExtractor(deployment="d", client=cliente, cache_dir=tmp_path, backoff_s=0)
    r = ex.extract("a", CHECKBOX)
    assert r.error is None and len(comp.chamadas) == 3


def test_azure_registra_erro_quando_esgota_tentativas(tmp_path):
    cliente, comp = _cliente([RuntimeError("falha")] * 3)
    ex = AzureOpenAIExtractor(deployment="d", client=cliente, cache_dir=tmp_path, backoff_s=0, max_retries=2)
    r = ex.extract("a", CHECKBOX)
    assert r.error and "RuntimeError" in r.error and len(comp.chamadas) == 3
    assert all(v is None for v in r.fields.values())
    assert not list(tmp_path.iterdir())  # falha não vai para o cache


def test_azure_saida_invalida_vira_erro_mas_guarda_o_texto_bruto(tmp_path):
    cliente, _ = _cliente(["desculpe, não consegui"])
    ex = AzureOpenAIExtractor(deployment="d", client=cliente, cache_dir=tmp_path)
    r = ex.extract("a", CHECKBOX)
    assert r.error.startswith("saida_invalida") and r.raw == "desculpe, não consegui"
