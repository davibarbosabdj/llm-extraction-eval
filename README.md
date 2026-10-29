# llm-extraction-eval

Como saber se um extrator de informação com LLM é bom o bastante para rodar em produção?
Este projeto responde com um método: gabarito, métricas por campo, medida de alucinação,
comparação com linhas de base sem LLM e um portão de qualidade que decide o que passa sem
revisão humana.

O caso de uso é a leitura de **laudos de aptidão técnica**: dado o texto do laudo, extrair
o resultado (apto, inapto, apto com restrições), as datas de emissão e de validade, o
avaliador, o registro profissional e as restrições.

> **Todos os dados são sintéticos.** Nenhum laudo real, nome real ou dado de empresa foi
> usado. Os laudos são gerados por `src/llm_extraction_eval/synth.py`. **Não coloque laudos
> reais neste repositório**: são dados sensíveis.

## Estado do projeto

| Parte | Estado |
| --- | --- |
| Gerador de laudos sintéticos com gabarito (9 layouts e armadilhas) | pronto |
| Duas linhas de base sem LLM (regras ingênuas e regras contextuais) | pronto e avaliado |
| Métricas, intervalos de confiança, portão de qualidade e relatórios | pronto |
| Extrator com Azure OpenAI (prompts versionados, cache, retentativas) | pronto, **ainda não executado com um modelo real** |
| Testes (50), incluindo o pipeline com um cliente de LLM falso | passando |

Por isso **não há números de LLM neste repositório**. Os resultados abaixo são das linhas de
base. Veja "Como rodar com Azure OpenAI" para gerar os números do modelo.

## O que o método mede

Para cada documento e campo, o valor previsto é comparado ao gabarito depois de normalizado
(datas em vários formatos viram AAAA-MM-DD, títulos como "Dra." saem do nome, "Nenhuma" e
"—" contam como ausente). Há cinco desfechos:

| Desfecho | Significa |
| --- | --- |
| acerto | ambos têm valor e são iguais |
| ausente correto | ambos ausentes |
| **alucinação** | o gabarito é ausente, mas o extrator preencheu |
| omissão | o gabarito tem valor, mas o extrator deixou vazio |
| errado | ambos têm valor e são diferentes |

Daí saem acurácia, precisão, revocação e F1 por campo, taxa de alucinação, acerto do
documento inteiro (todos os campos certos), matriz de confusão do resultado, intervalo de
confiança de 95% por bootstrap, tokens, latência e custo (se você informar os preços).

O erro mais caro do problema é o **falso apto**: um laudo inapto lido como apto. Ele aparece
separado em todo relatório.

### Portão de qualidade

Em vez de confiar cegamente na resposta do modelo, o portão confere se ela é coerente com o
documento e manda o resto para refazer ou para revisão humana. Três verificações:

1. **Esquema**: resultado válido, datas que existem, validade depois da emissão, restrição
   preenchida quando o resultado é "apto com restrições".
2. **Evidência ancorada**: o modelo cita o trecho que sustenta o resultado, e o portão mede
   (de 0 a 1) o quanto esse trecho existe no documento. O limiar é a similaridade mínima
   aceita, o mesmo padrão de "aprovar a partir de cerca de 90 a 95%".
3. **Coerência**: o trecho combina com o resultado. "Inapto" precisa citar "inapto";
   "apto" precisa citar "apto" (a palavra, não o final de "inapto") ou a negação de inapto.

O relatório traz a curva do limiar: quanto do volume passa e quão certo é o resultado entre
os aceitos. **O portão mede coerência, não verdade.** Um laudo mal lido que cita uma frase
real e coerente ainda passa (veja os resultados do holdout).

### Os laudos sintéticos

Seis layouts conhecidos e três layouts novos, com armadilhas que derrubam extratores simples:

- resultado marcado numa **caixa de seleção** (`[X] Apto`, com as três opções no texto);
- **histórico** de avaliações anteriores com resultados diferentes do atual;
- **negação** ("não sendo o candidato considerado inapto");
- **boilerplate** que cita "inapto" sem ser o resultado;
- **datas distratoras** (nascimento, avaliação) além da emissão;
- **validade relativa** ("12 meses a contar da emissão"), que exige calcular a data;
- campos **ausentes** (sem validade, sem registro);
- **ruído de OCR** (acentos perdidos, `O` trocado por `0`, espaços extras).

Três conjuntos, com papéis diferentes:

| Conjunto | Laudos | Para quê |
| --- | --- | --- |
| `dev` | 80 | ajustar regras e prompts |
| `test` | 320 | medir uma vez, depois de congelar o que foi ajustado no `dev` |
| `holdout` | 120 | layouts inéditos (`formulario`, `carta`, `ficha`), com vocabulário diferente de propósito ("ressalvas", "expedido em", "vigência") |

## Resultados das linhas de base

Conjunto `test` (320 laudos), regras congeladas após o ajuste no `dev`:

| Extrator | Documento todo correto | IC 95% | Resultado correto | Falso apto |
| --- | --- | --- | --- | --- |
| `rules_naive` (primeira menção a apto/inapto, primeira e última data) | 4,7% | 2,5 a 7,2 | 50,6% | 21 de 71 |
| `rules_contextual` (rótulos, caixas de seleção, negação, avaliação atual) | 95,3% | 92,8 a 97,5 | 100,0% | 0 de 71 |

Acurácia por campo no `test`:

| Campo | `rules_naive` | `rules_contextual` |
| --- | --- | --- |
| resultado | 50,6% | 100,0% |
| data de emissão | 50,3% | 99,4% |
| data de validade | 57,2% | 99,1% |
| avaliador | 99,1% | 99,1% |
| registro | 98,4% | 98,4% |
| restrições | 82,5% | 98,1% |

As regras contextuais acertam 100% dos laudos em todos os layouts conhecidos, exceto no
**OCR (71,2%)**, onde `0` no lugar de `O` quebra nomes e datas.

Conjunto `holdout` (120 laudos em layouts inéditos):

| Extrator | Documento todo correto | Resultado correto | Falso apto |
| --- | --- | --- | --- |
| `rules_naive` | 0,0% | 89,2% | 0 de 22 |
| `rules_contextual` | 0,0% | 89,2% | 0 de 22 |

No `holdout`, as regras contextuais perdem quase tudo: o avaliador (0%, porque não há
"Dr." ou "Dra." no texto), a validade (47,5%) e a emissão (66,7%). Os 13 erros de resultado
são laudos "apto com ressalvas" lidos como "apto", porque a regra só conhece "restrições".
Esses 13 erros **passam no portão em 0,90**, já que a evidência citada é real e coerente.

### Como ler isso

- Regras escritas à mão funcionam muito bem em formatos conhecidos e custam milissegundos,
  mas **não generalizam**: 95% no `test` e 0% no `holdout` mostram isso.
- Um LLM só se justifica onde as regras falham: layouts inéditos, OCR ruim e texto livre.
  Para decidir, compare-o com `rules_contextual` no `holdout` e no OCR, não só no `test`.
- O `holdout` foi escrito de propósito com vocabulário diferente. O 0% mede fragilidade a
  mudança de formato, não a dificuldade de um laudo real qualquer.

## Limitações

- **Dados sintéticos.** Os números valem para esta distribuição e não preveem o desempenho em
  laudos reais, que têm mais variação de formato, linguagem e qualidade de digitalização.
- **O `test` compartilha layouts com o `dev`.** Ele mede generalização para conteúdo novo nos
  mesmos formatos, e isso favorece as regras. O `holdout` é o teste de formato novo.
- **Quem escreveu as regras escreveu o gerador.** Isso torna o `test` mais fácil do que seria
  com laudos de terceiros.
- A lista de textos tratados como "ausente" no normalizador (por exemplo "não há" e "—") foi
  ampliada ao criar o `holdout`. Ela vale para todos os extratores igualmente.
- O portão mede coerência com o documento, não verdade.
- Nenhum modelo real foi executado ainda.

## Estrutura

```
src/llm_extraction_eval/
  synth.py          gerador de laudos sintéticos, gabarito e holdout
  schema.py         campos e normalização de valores
  dates.py          datas em português (numéricas e por extenso)
  extractors/       rules.py (duas linhas de base), azure_openai.py (LLM), base.py
  metrics.py        desfechos, F1, alucinação, bootstrap, custo e latência
  gate.py           portão de qualidade e curva cobertura x acerto
  runner.py         executa o extrator, grava JSONL, retoma de onde parou
  report.py         relatório em Markdown e gráficos
  cli.py            comando llm-eval
prompts/            v1_basico.txt, v2_estruturado.txt
data/synthetic/     520 laudos e labels.jsonl (determinístico, seed 42)
results/            previsões, métricas, relatórios e gráficos das linhas de base
tests/              50 testes
```

## Como rodar

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

llm-eval generate                                   # recria data/synthetic (determinístico)
llm-eval run --extractor rules_contextual --split test
llm-eval compare --runs results/rules_naive_test results/rules_contextual_test --out results/comparison_test
pytest
```

Cada execução grava `results/<extrator>_<conjunto>/` com `predictions.jsonl`, `metrics.json`,
`report.md` e gráficos.

## Como rodar com Azure OpenAI

```bash
pip install -e ".[azure]"
export AZURE_OPENAI_ENDPOINT="https://<seu-recurso>.openai.azure.com"
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_DEPLOYMENT="<nome do deployment>"   # o nome do deployment, não do modelo
cp pricing.example.yaml pricing.yaml                      # preencha com os preços do seu deployment

# 1) teste barato: 10 laudos do dev
llm-eval run --extractor azure --prompt v2 --split dev --limit 10 --run-name azure_v2_dev10

# 2) dev completo com os dois prompts; escolha o melhor AQUI
llm-eval run --extractor azure --prompt v1 --split dev
llm-eval run --extractor azure --prompt v2 --split dev

# 3) só então test e holdout, uma vez cada, com o prompt escolhido
llm-eval run --extractor azure --prompt v2 --split test --workers 4
llm-eval run --extractor azure --prompt v2 --split holdout --workers 4
llm-eval compare --runs results/rules_contextual_test results/azure_openai_v2_test --out results/comparison_test_azure
```

- As respostas ficam em cache (`.cache/`), então repetir uma execução não paga duas vezes.
- Uma execução interrompida retoma de onde parou (use `--fresh` para recomeçar).
- Chaves ficam em variáveis de ambiente. `pricing.yaml` e `.env` estão no `.gitignore`.
- Sem `pricing.yaml` preenchido, o relatório diz que o custo não foi calculado em vez de estimar.
- A versão da API padrão está em `azure_openai.py` (`DEFAULT_API_VERSION`); confira a vigente
  na documentação do Azure OpenAI e ajuste com `AZURE_OPENAI_API_VERSION`.

## Próximos passos

1. Rodar o extrator com Azure OpenAI nos dois prompts e publicar a comparação com as regras,
   principalmente no OCR e no `holdout`.
2. Medir a estabilidade: repetir a mesma execução com temperatura maior e ver quanto a
   resposta varia entre rodadas.
3. Testar exemplos no prompt (few-shot) e comparar o ganho com o custo em tokens.
4. Calibrar o limiar do portão pelo custo de cada erro: um falso apto custa mais que mandar
   um laudo correto para revisão.
