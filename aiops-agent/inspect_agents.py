"""Phase 3 CLI: prepare redacted inputs, or run real read-only LLM investigation."""
import argparse
import json
from pathlib import Path
from agents import AgentError, AgentRunner, initial_context, run_investigation
from audit_log import AuditLog
from config import LLMConfig
from loader import load_scenario


class PreparationOnly:
    mode = "prepare_only"

    def complete(self, *args, **kwargs):
        raise AgentError("Preparation mode cannot generate outputs or call a provider")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_folder")
    parser.add_argument("--output", default="phase3_report.json")
    parser.add_argument("--prepare-only", action="store_true", help="Save actual redacted initial input without an API call")
    args = parser.parse_args()
    output = Path(args.output)
    if output.resolve().is_relative_to(Path(args.scenario_folder).resolve()):
        parser.error("Report output must be outside the scenario directory")
    store = load_scenario(args.scenario_folder)
    audit = AuditLog()
    try:
        config = LLMConfig.from_env()
        if args.prepare_only:
            runner = AgentRunner(store, audit, config, PreparationOnly())
            messages, size = runner.messages("hypothesis_agent", initial_context(store))
            report = {"phase": 3, "mode": "prepare_only", "scenario_id": store.scenario_id,
                      "provider": config.provider, "model_configured": bool(config.model),
                      "status": "prepared_not_executed", "prompt_bytes": size,
                      "agent_inputs": {"hypothesis_agent": messages}, "validated_outputs": [],
                      "warning": "No LLM called. No hypotheses, confidence or recovery outcomes generated."}
        else:
            runner = AgentRunner(store, audit, config)
            report = run_investigation(store, audit, runner)
    except (AgentError, ValueError) as exc:
        report = {"phase": 3, "scenario_id": store.scenario_id, "mode": "live",
                  "status": "unavailable", "error": str(exc), "root_cause": None}
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"scenario_id": store.scenario_id, "status": report["status"],
                      "mode": report["mode"], "error": report.get("error"),
                      "requests": report.get("requests", 0), "report": str(output.resolve())}, indent=2))
    if report["status"] in {"unavailable", "agent_unavailable", "budget_exhausted"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
