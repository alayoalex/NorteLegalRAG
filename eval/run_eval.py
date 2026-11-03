"""Evalúa el sistema por su API HTTP: sube la muestra, espera la ingesta y hace las preguntas.

    cd backend && EVAL_LLM=fake EVAL_EMBEDDINGS=fake uv run python ../eval/run_eval.py --label fake

Cada ejecución usa un tenant propio (`eval-<label>`), así que no mezcla datos con otros usos. Mide
el sistema tal y como lo ve un usuario, con los proveedores que tenga configurados la API. La API no
los expone: `EVAL_LLM` y `EVAL_EMBEDDINGS` solo los anotan en el informe. Escribe
`eval/results/<label>.json` (detalle por pregunta) y `eval/results/<label>.md` (resumen).

Métricas (solo las preguntas con respuesta esperada cuentan para la recuperación):
- hit@1, hit@8 y MRR: algún fragmento devuelto en `sources` se solapa con el texto de referencia.
- Cita correcta: la respuesta tiene al menos una cita que se solapa con el texto de referencia.
- Abstención: en las preguntas sin respuesta, el sistema devuelve `no_context` (no inventa).
- Inyección: ninguna cadena prohibida aparece en la respuesta ni en las citas.
"""

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import httpx2

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
RESULTS = ROOT / "eval" / "results"
INGEST_TIMEOUT_S = 900
QUERY_TIMEOUT_S = 70  # Por encima del presupuesto de 55 s de la API.


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="nombre de la ejecución, p. ej. voyage-4")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--limit", type=int, default=None, help="solo las N primeras preguntas")
    args = parser.parse_args()

    questions = [
        json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines()
    ]
    edge_cases: dict[str, str] = json.loads((ROOT / "eval" / "edge_cases.json").read_text())
    client = httpx2.Client(
        base_url=args.base_url,
        headers={"X-Tenant-ID": f"eval-{args.label}"},
        timeout=QUERY_TIMEOUT_S,
    )

    ingestion = _ingest(client, edge_cases)
    rows = [_ask(client, q) for q in questions[: args.limit]]
    summary = _summarize(rows, ingestion)
    summary["label"] = args.label

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.label}.json").write_text(
        json.dumps(
            {"summary": summary, "ingestion": ingestion, "rows": rows}, ensure_ascii=False, indent=1
        )
    )
    (RESULTS / f"{args.label}.md").write_text(_markdown(summary))
    print(_markdown(summary))


def _ingest(client: httpx2.Client, edge_cases: dict[str, str]) -> dict[str, Any]:
    """Sube cada archivo de la muestra y espera a que todas las versiones terminen."""
    files = sorted(p for p in SAMPLES.rglob("*") if p.is_file() and p.name != "ATTRIBUTION.md")
    outcomes: dict[str, str] = {}
    pending: dict[str, str] = {}
    started = time.monotonic()
    for path in files:
        response = client.post("/api/v1/documents", files={"file": (path.name, path.read_bytes())})
        if response.status_code == 202:
            pending[path.name] = response.json()["document_id"]
        else:
            outcomes[path.name] = f"rejected:{response.json().get('code')}"

    while pending and time.monotonic() - started < INGEST_TIMEOUT_S:
        time.sleep(2)
        for name, document_id in list(pending.items()):
            version = client.get(f"/api/v1/documents/{document_id}").json()["latest_version"]
            if version["status"] == "ready":
                outcomes[name] = "ready"
            elif version["status"] == "failed":
                outcomes[name] = f"failed:{version['error_code']}"
            else:
                continue
            del pending[name]
    outcomes.update({name: "timeout" for name in pending})

    checks = {name: outcomes.get(name) == expected for name, expected in edge_cases.items()}
    return {
        "seconds": round(time.monotonic() - started, 1),
        "outcomes": outcomes,
        "edge_cases_ok": sum(checks.values()),
        "edge_cases_total": len(checks),
        "edge_case_failures": [name for name, ok in checks.items() if not ok],
    }


def _ask(client: httpx2.Client, question: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    response = client.post("/api/v1/query", json={"question": question["question"]})
    latency = time.monotonic() - started
    row: dict[str, Any] = {
        "id": question["id"],
        "set": question["set"],
        "expected": question["expected"],
        "latency_s": round(latency, 2),
    }
    if response.status_code != 200:
        return {**row, "status": f"http_{response.status_code}", "reason": None}
    body = response.json()
    name = Path(question["document"]).name if question["document"] else None
    spans = [tuple(span) for span in question["spans"]]

    def matches(item: dict[str, Any]) -> bool:
        return item["document_name"] == name and any(
            item["char_start"] < end and start < item["char_end"] for start, end in spans
        )

    rank = next((i for i, source in enumerate(body["sources"], start=1) if matches(source)), None)
    texts = [body["answer"] or "", *(citation["quote"] for citation in body["citations"])]
    forbidden = [
        f for f in question.get("forbidden", []) if any(f.casefold() in t.casefold() for t in texts)
    ]
    return {
        **row,
        "status": body["status"],
        "reason": body["reason"],
        "retrieval_mode": body["retrieval_mode"],
        "rank": rank,
        "citation_ok": any(matches(citation) for citation in body["citations"]),
        "citations": len(body["citations"]),
        "forbidden_found": forbidden,
    }


def _summarize(rows: list[dict[str, Any]], ingestion: dict[str, Any]) -> dict[str, Any]:
    health = _health()
    answerable = [r for r in rows if r["expected"] == "answer"]
    unanswerable = [r for r in rows if r["expected"] == "no_context"]
    by_set: dict[str, dict[str, Any]] = {}
    for name in sorted({r["set"] for r in rows}):
        subset = [r for r in rows if r["set"] == name]
        by_set[name] = {"n": len(subset), **_scores(subset)}
    latencies = sorted(r["latency_s"] for r in rows)
    return {
        "providers": health,
        "questions": len(rows),
        "overall": {
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
            **_scores(rows),
        },
        "by_set": by_set,
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "latency_p95_s": round(latencies[int(0.95 * (len(latencies) - 1))], 2)
        if latencies
        else None,
        "errors": sum(1 for r in rows if str(r["status"]).startswith("http_")),
        "injection_violations": sum(1 for r in rows if r.get("forbidden_found")),
        "ingestion_seconds": ingestion["seconds"],
        "edge_cases": f"{ingestion['edge_cases_ok']}/{ingestion['edge_cases_total']}",
    }


def _scores(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    answerable = [r for r in rows if r["expected"] == "answer"]
    unanswerable = [r for r in rows if r["expected"] == "no_context"]
    ranks = [r.get("rank") for r in answerable]
    return {
        "hit@1": _rate([rank == 1 for rank in ranks]),
        "hit@8": _rate([rank is not None for rank in ranks]),
        "mrr": round(sum(1 / rank for rank in ranks if rank) / len(ranks), 3) if ranks else None,
        "answered": _rate([r["status"] == "answered" for r in answerable]),
        "citation_ok": _rate([bool(r.get("citation_ok")) for r in answerable]),
        "abstention": _rate([r["status"] == "no_context" for r in unanswerable]),
    }


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _health() -> dict[str, str]:
    """Los proveedores no se exponen por la API: se pasan por entorno al lanzar la evaluación."""
    return {
        "llm": os.environ.get("EVAL_LLM", "desconocido"),
        "embeddings": os.environ.get("EVAL_EMBEDDINGS", "desconocido"),
    }


def _markdown(summary: dict[str, Any]) -> str:
    providers = summary["providers"]
    lines = [
        f"# Evaluación `{summary['label']}`",
        "",
        f"LLM: `{providers['llm']}` · embeddings: `{providers['embeddings']}` · "
        f"{summary['questions']} preguntas · ingesta {summary['ingestion_seconds']} s · "
        f"casos límite {summary['edge_cases']} · "
        f"latencia p50 {summary['latency_p50_s']} s, p95 {summary['latency_p95_s']} s · "
        f"errores HTTP {summary['errors']} · "
        f"violaciones de inyección {summary['injection_violations']}",
        "",
        "| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, scores in [("**total**", summary["overall"]), *summary["by_set"].items()]:
        n = scores.get("n", summary["questions"])
        cells = [
            _cell(scores[key])
            for key in ("hit@1", "hit@8", "mrr", "answered", "citation_ok", "abstention")
        ]
        lines.append(f"| {name} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _cell(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    main()
