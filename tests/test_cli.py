import json

from llm_extraction_eval.cli import main


def test_fluxo_completo(tmp_path):
    data, results = tmp_path / "data", tmp_path / "results"
    main(["generate", "--n", "50", "--n-holdout", "9", "--out", str(data)])
    assert len(list((data / "docs").glob("*.txt"))) == 59

    for ex in ("rules_naive", "rules_contextual"):
        main(["run", "--extractor", ex, "--split", "test", "--data", str(data), "--results", str(results)])
        run = results / f"{ex}_test"
        assert (run / "predictions.jsonl").exists() and (run / "report.md").exists()
        assert (run / "metrics.json").exists() and (run / "campos.png").exists()

    main(["run", "--extractor", "rules_contextual", "--split", "holdout", "--data", str(data),
          "--results", str(results)])
    m = json.loads((results / "rules_contextual_holdout" / "metrics.json").read_text())
    assert m["n_docs"] == 9

    main(["compare", "--runs", str(results / "rules_naive_test"), str(results / "rules_contextual_test"),
          "--out", str(results / "cmp")])
    assert (results / "cmp" / "comparison.md").exists() and (results / "cmp" / "comparacao.png").exists()


def test_run_retoma_sem_reexecutar(tmp_path, capsys):
    data, results = tmp_path / "data", tmp_path / "results"
    main(["generate", "--n", "20", "--n-holdout", "0", "--out", str(data)])
    args = ["run", "--extractor", "rules_naive", "--split", "test", "--data", str(data),
            "--results", str(results), "--no-eval"]
    main(args)
    capsys.readouterr()
    main(args)
    saida = capsys.readouterr().err
    assert "0 a executar" in saida
    linhas = (results / "rules_naive_test" / "predictions.jsonl").read_text().strip().splitlines()
    assert len(linhas) == 16  # 20 documentos, 4 deles em dev
