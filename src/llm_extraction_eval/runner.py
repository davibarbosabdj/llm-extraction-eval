"""Executa um extrator sobre os documentos e grava as previsões em JSONL (com retomada)."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .extractors.base import ExtractionResult, Extractor
from .synth import Doc


def load_predictions(path: str | Path) -> dict[str, dict]:
    preds: dict[str, dict] = {}
    p = Path(path)
    if not p.exists():
        return preds
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                preds[rec["doc_id"]] = rec
    return preds


def run_extraction(extractor: Extractor, docs: list[Doc], out_path: str | Path,
                   workers: int = 1, resume: bool = True, verbose: bool = True) -> dict[str, dict]:
    """Roda `extractor` em `docs`, acrescentando cada resultado a `out_path`.

    Com `resume=True`, documentos que já estão no arquivo são pulados. Isso evita
    pagar duas vezes por chamadas a um serviço externo se a execução for interrompida.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    feitos = load_predictions(out) if resume else {}
    if not resume and out.exists():
        out.unlink()
    pendentes = [d for d in docs if d.doc_id not in feitos]
    if verbose:
        print(f"[{extractor.name}] {len(docs)} documentos, {len(feitos)} já feitos, {len(pendentes)} a executar",
              file=sys.stderr)

    def trabalhar(doc: Doc) -> ExtractionResult:
        try:
            return extractor.extract(doc.doc_id, doc.text)
        except Exception as exc:  # um documento ruim não derruba a execução inteira
            return ExtractionResult(doc_id=doc.doc_id, extractor=extractor.name,
                                    error=f"{type(exc).__name__}: {exc}")

    with out.open("a", encoding="utf-8") as f:
        if workers <= 1:
            resultados = (trabalhar(d) for d in pendentes)
            for i, r in enumerate(resultados, 1):
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
                f.flush()
                feitos[r.doc_id] = r.to_dict()
                if verbose and i % 50 == 0:
                    print(f"  {i}/{len(pendentes)}", file=sys.stderr)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futuros = [pool.submit(trabalhar, d) for d in pendentes]
                for i, fut in enumerate(as_completed(futuros), 1):
                    r = fut.result()
                    f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
                    f.flush()
                    feitos[r.doc_id] = r.to_dict()
                    if verbose and i % 50 == 0:
                        print(f"  {i}/{len(pendentes)}", file=sys.stderr)
    return feitos
