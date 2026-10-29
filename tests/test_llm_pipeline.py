"""Pipeline completo com um "LLM" de mentira: runner, cache, métricas e portão juntos.

O cliente falso responde com a saída das regras contextuais e corrompe alguns documentos
de propósito: evidência inventada, resultado trocado e resposta que não é JSON. O que se
verifica é o encanamento: o portão barra o que deve barrar, o cache evita chamadas
repetidas e um erro de execução não derruba a avaliação. Nenhum número daqui descreve o
desempenho de um LLM real.
"""

import json
from types import SimpleNamespace

from llm_extraction_eval.extractors import AzureOpenAIExtractor, ContextualRules
from llm_extraction_eval.metrics import compute_metrics
from llm_extraction_eval.runner import run_extraction
from llm_extraction_eval.synth import generate_dataset

LIMPO, EVIDENCIA_INVENTADA, RESULTADO_TROCADO, NAO_E_JSON = range(4)


class ClienteRoteirizado:
    """Imita `client.chat.completions.create` e conta as chamadas."""

    def __init__(self, resposta):
        self._resposta = resposta
        self.chamadas = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.chamadas += 1
        conteudo = self._resposta(kwargs["messages"][1]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


def _montar(tmp_path):
    # Sem OCR, para que o "LLM" limpo (as regras) acerte tudo e o teste isole o efeito das corrupções.
    docs = [d for d in generate_dataset(120, seed=3) if d.split == "test" and d.template != "ocr"][:40]
    modo = {d.doc_id: i % 4 for i, d in enumerate(docs)}
    por_texto = {d.text: d for d in docs}
    regras = ContextualRules()

    def resposta(prompt: str) -> str:
        doc = next(d for texto, d in por_texto.items() if texto in prompt)
        base = regras.extract(doc.doc_id, doc.text)
        campos, evidencia = dict(base.fields), base.evidencia_resultado
        m = modo[doc.doc_id]
        if m == EVIDENCIA_INVENTADA:
            evidencia = "a candidata demonstrou plena capacidade para o exercício da função"
        elif m == RESULTADO_TROCADO:
            campos["resultado"] = "apto" if campos["resultado"] == "inapto" else "inapto"
        elif m == NAO_E_JSON:
            return "desculpe, não consegui ler o laudo"
        return json.dumps({**campos, "evidencia_resultado": evidencia}, ensure_ascii=False)

    cliente = ClienteRoteirizado(resposta)
    extrator = AzureOpenAIExtractor(deployment="falso", client=cliente, cache_dir=tmp_path / "cache")
    labels = [{"doc_id": d.doc_id, "template": d.template, "tags": d.tags, "truth": d.truth} for d in docs]
    return docs, modo, cliente, extrator, labels


def test_portao_barra_o_que_deve_e_so_deixa_passar_acertos(tmp_path):
    docs, modo, cliente, extrator, labels = _montar(tmp_path)
    preds = run_extraction(extrator, docs, tmp_path / "pred.jsonl", verbose=False)
    contagem = {m: sum(v == m for v in modo.values()) for m in range(4)}

    m = compute_metrics(labels, preds, texts={d.doc_id: d.text for d in docs}, n_boot=100)
    assert m["n_docs"] == 40 and m["n_sem_previsao"] == 0
    assert m["n_erro_execucao"] == contagem[NAO_E_JSON]            # resposta fora do padrão vira erro, não exceção
    assert m["campos"]["resultado"]["errado"] == contagem[RESULTADO_TROCADO]
    assert m["uso"]["prompt_tokens"] == 100 * 40                    # o uso é registrado mesmo nas respostas ruins

    portao = m["gate"]["em_090"]
    assert portao["erros_aceitos"] == 0                             # nenhum resultado errado passou
    assert portao["cobertura"] == contagem[LIMPO] / 40              # só passam os documentos limpos
    assert portao["acerto_aceitos"] == 1.0


def test_segunda_execucao_vem_do_cache_sem_novas_chamadas(tmp_path):
    docs, _, cliente, extrator, _ = _montar(tmp_path)
    run_extraction(extrator, docs, tmp_path / "a.jsonl", verbose=False)
    chamadas = cliente.chamadas
    assert chamadas == 40
    de_novo = run_extraction(extrator, docs, tmp_path / "b.jsonl", verbose=False)
    assert cliente.chamadas == chamadas
    assert all(p["cached"] for p in de_novo.values())
