"""Extrator com Azure OpenAI.

Configuração por variáveis de ambiente :

    AZURE_OPENAI_ENDPOINT      https://<seu-recurso>.openai.azure.com
    AZURE_OPENAI_API_KEY       chave do recurso
    AZURE_OPENAI_DEPLOYMENT    nome do *deployment* (não o nome do modelo)
    AZURE_OPENAI_API_VERSION   opcional; confira a versão vigente na documentação

O cliente pode ser injetado (`client=`), o que permite testar o parsing, o cache e
as retentativas sem rede e sem custo.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from ..schema import FIELDS
from .base import ExtractionResult

def _achar_pasta_de_prompts() -> Path:
    """`prompts/` na raiz do repositório (instalação com `pip install -e .`) ou na pasta atual."""
    candidatos = [Path(__file__).resolve().parents[3] / "prompts", Path.cwd() / "prompts"]
    return next((p for p in candidatos if p.exists()), candidatos[0])


PROMPTS_DIR = _achar_pasta_de_prompts()
_PROMPT_FILES = {"v1": "v1_basico.txt", "v2": "v2_estruturado.txt"}
_SEPARADOR = "=== USUARIO ==="
DEFAULT_API_VERSION = "2024-10-21"


def load_prompt(version: str, prompts_dir: Path = PROMPTS_DIR) -> tuple[str, str]:
    """Devolve (mensagem de sistema, modelo da mensagem do usuário com {documento})."""
    if version not in _PROMPT_FILES:
        raise ValueError(f"versão de prompt desconhecida: {version}. Opções: {sorted(_PROMPT_FILES)}")
    conteudo = (prompts_dir / _PROMPT_FILES[version]).read_text(encoding="utf-8")
    sistema, usuario = conteudo.split(_SEPARADOR, 1)
    return sistema.strip(), usuario.strip()


def parse_model_output(content: str) -> tuple[dict, str | None]:
    """Lê o JSON devolvido pelo modelo. Tolera cercas de código e texto ao redor.

    Devolve (campos, evidência). Levanta ValueError se não houver JSON utilizável.
    """
    texto = content.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE)
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        ini, fim = texto.find("{"), texto.rfind("}")
        if ini == -1 or fim <= ini:
            raise ValueError("resposta sem objeto JSON")
        try:
            dados = json.loads(texto[ini: fim + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido: {exc}") from exc
    if not isinstance(dados, dict):
        raise ValueError("JSON não é um objeto")
    campos = {k: dados.get(k) for k in FIELDS}
    for k, v in campos.items():
        if v is not None and not isinstance(v, (str, int, float)):
            campos[k] = json.dumps(v, ensure_ascii=False)
    evidencia = dados.get("evidencia_resultado")
    return campos, evidencia if isinstance(evidencia, str) else None


class AzureOpenAIExtractor:
    def __init__(self, prompt_version: str = "v2", deployment: str | None = None, client=None,
                 cache_dir: str | Path | None = ".cache", temperature: float = 0.0,
                 max_retries: int = 4, backoff_s: float = 2.0, max_tokens: int = 400):
        self.prompt_version = prompt_version
        self.deployment = deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        self.name = f"azure_openai_{prompt_version}"
        self.temperature = temperature
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.max_tokens = max_tokens
        self._client = client
        self._system, self._user_tpl = load_prompt(prompt_version)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cliente
    def _get_client(self):
        if self._client is None:
            try:
                from openai import AzureOpenAI
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError('Instale o extra: pip install -e ".[azure]"') from exc
            faltando = [v for v in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY") if not os.environ.get(v)]
            if faltando or not self.deployment:
                raise RuntimeError("Defina AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY e AZURE_OPENAI_DEPLOYMENT")
            self._client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION),
            )
        return self._client

    # -- cache
    def _cache_path(self, text: str) -> Path | None:
        if not self.cache_dir:
            return None
        chave = json.dumps([self.deployment, self.prompt_version, self.temperature, self._system,
                            self._user_tpl, text], ensure_ascii=False)
        return self.cache_dir / (hashlib.sha256(chave.encode("utf-8")).hexdigest() + ".json")

    # -- extração
    def extract(self, doc_id: str, text: str) -> ExtractionResult:
        res = ExtractionResult(doc_id=doc_id, extractor=self.name)
        cache = self._cache_path(text)
        if cache and cache.exists():
            salvo = json.loads(cache.read_text(encoding="utf-8"))
            content, usage = salvo["content"], salvo["usage"]
            res.cached = True
        else:
            t0 = time.perf_counter()
            try:
                content, usage = self._chamar(text)
            except Exception as exc:
                res.latency_s = time.perf_counter() - t0
                res.error = f"{type(exc).__name__}: {exc}"
                return res
            res.latency_s = time.perf_counter() - t0
            if cache:
                cache.write_text(json.dumps({"content": content, "usage": usage}, ensure_ascii=False),
                                 encoding="utf-8")
        res.raw = content
        res.prompt_tokens = usage.get("prompt_tokens", 0)
        res.completion_tokens = usage.get("completion_tokens", 0)
        try:
            res.fields, res.evidencia_resultado = parse_model_output(content)
        except ValueError as exc:
            res.error = f"saida_invalida: {exc}"
        return res

    def _chamar(self, text: str) -> tuple[str, dict]:
        client = self._get_client()
        mensagens = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": self._user_tpl.replace("{documento}", text)},
        ]
        ultimo_erro: Exception | None = None
        for tentativa in range(self.max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=self.deployment, messages=mensagens, temperature=self.temperature,
                    max_tokens=self.max_tokens, response_format={"type": "json_object"},
                )
                uso = getattr(resp, "usage", None)
                usage = {
                    "prompt_tokens": getattr(uso, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(uso, "completion_tokens", 0) or 0,
                }
                return resp.choices[0].message.content or "", usage
            except Exception as exc:  # limite de taxa, erro transitório de rede etc.
                ultimo_erro = exc
                if tentativa < self.max_retries:
                    time.sleep(self.backoff_s * (2 ** tentativa))
        raise ultimo_erro  # type: ignore[misc]
