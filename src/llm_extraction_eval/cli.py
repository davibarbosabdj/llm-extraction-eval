"""Linha de comando: generate, run, evaluate, compare."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .extractors import AzureOpenAIExtractor, ContextualRules, NaiveRules
from .metrics import compute_metrics
from .report import write_comparison, write_report
from .runner import load_predictions, run_extraction
from .synth import generate_dataset, generate_holdout, load_dataset, save_dataset

EXTRATORES = ("rules_naive", "rules_contextual", "azure")


def _carregar_pricing(path: str | None) -> dict | None:
    p = Path(path) if path else Path("pricing.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def _build_extractor(args):
    if args.extractor == "rules_naive":
        return NaiveRules()
    if args.extractor == "rules_contextual":
        return ContextualRules()
    return AzureOpenAIExtractor(prompt_version=args.prompt, deployment=args.deployment, cache_dir=args.cache_dir)


def cmd_generate(args) -> None:
    docs = generate_dataset(args.n, args.seed)
    holdout = generate_holdout(args.n_holdout, args.seed + 1) if args.n_holdout else []
    save_dataset(docs + holdout, args.out)
    dev = sum(d.split == "dev" for d in docs)
    print(f"{len(docs) + len(holdout)} laudos sintéticos em {args.out} "
          f"({dev} dev, {len(docs) - dev} test, {len(holdout)} holdout)")


def cmd_run(args) -> None:
    docs = load_dataset(args.data, args.split)
    if args.limit:
        docs = docs[: args.limit]
    extractor = _build_extractor(args)
    run_name = args.run_name or f"{extractor.name}_{args.split}"
    out_dir = Path(args.results) / run_name
    run_extraction(extractor, docs, out_dir / "predictions.jsonl", workers=args.workers, resume=not args.fresh)
    print(f"previsões em {out_dir / 'predictions.jsonl'}")
    if not args.no_eval:
        _avaliar(args.data, args.split, out_dir, run_name, args.pricing, limit=args.limit)


def _avaliar(data: str, split: str, run_dir: Path, run_name: str, pricing_path: str | None, limit: int | None = None):
    docs = load_dataset(data, split)
    if limit:
        docs = docs[:limit]
    labels = [{"doc_id": d.doc_id, "template": d.template, "tags": d.tags, "truth": d.truth} for d in docs]
    texts = {d.doc_id: d.text for d in docs}
    preds = load_predictions(run_dir / "predictions.jsonl")
    preds = {k: v for k, v in preds.items() if k in texts}
    metrics = compute_metrics(labels, preds, texts=texts, pricing=_carregar_pricing(pricing_path))
    nota = (f"Conjunto: `{split}` ({len(labels)} laudos sintéticos). Os dados são fictícios e gerados por "
            f"`synth.py`; os números valem para essa distribuição e não preveem o desempenho em laudos reais.")
    path = write_report(metrics, run_name, run_dir, extra_note=nota)
    print(f"relatório em {path}")
    print(f"  documento exato: {100 * metrics['doc_exato']:.1f}%  |  resultado correto: "
          f"{100 * metrics['resultado_acuracia']:.1f}%  |  falso apto: {metrics['falso_apto']['n']}"
          f"/{metrics['falso_apto']['de']}")


def cmd_evaluate(args) -> None:
    run_dir = Path(args.run)
    _avaliar(args.data, args.split, run_dir, run_dir.name, args.pricing, limit=args.limit)


def cmd_compare(args) -> None:
    runs = {}
    for r in args.runs:
        mpath = Path(r) / "metrics.json"
        if not mpath.exists():
            sys.exit(f"{mpath} não existe. Rode `evaluate` nessa execução antes.")
        runs[Path(r).name] = json.loads(mpath.read_text(encoding="utf-8"))
    print(f"comparação em {write_comparison(runs, args.out)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="llm-eval", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="gera laudos sintéticos com gabarito")
    g.add_argument("--n", type=int, default=400)
    g.add_argument("--n-holdout", type=int, default=120, help="laudos com layouts inéditos")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", default="data/synthetic")
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("run", help="executa um extrator e avalia")
    r.add_argument("--extractor", choices=EXTRATORES, required=True)
    r.add_argument("--split", choices=("dev", "test", "holdout"), default="dev")
    r.add_argument("--data", default="data/synthetic")
    r.add_argument("--results", default="results")
    r.add_argument("--run-name")
    r.add_argument("--prompt", default="v2", help="versão do prompt (só para azure)")
    r.add_argument("--deployment", help="nome do deployment (ou AZURE_OPENAI_DEPLOYMENT)")
    r.add_argument("--cache-dir", default=".cache")
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--limit", type=int, help="usa só os N primeiros documentos (bom para testar custo)")
    r.add_argument("--fresh", action="store_true", help="ignora previsões já gravadas")
    r.add_argument("--no-eval", action="store_true")
    r.add_argument("--pricing", help="caminho do pricing.yaml")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("evaluate", help="recalcula métricas e relatório de uma execução")
    e.add_argument("--run", required=True, help="pasta da execução (com predictions.jsonl)")
    e.add_argument("--split", choices=("dev", "test", "holdout"), default="test")
    e.add_argument("--data", default="data/synthetic")
    e.add_argument("--pricing")
    e.add_argument("--limit", type=int, help="avalia só os N primeiros (use o mesmo valor da execução)")
    e.set_defaults(func=cmd_evaluate)

    c = sub.add_parser("compare", help="compara execuções avaliadas")
    c.add_argument("--runs", nargs="+", required=True)
    c.add_argument("--out", default="results/comparison")
    c.set_defaults(func=cmd_compare)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
