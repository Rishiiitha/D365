# Autonomous incident investigation prototype

The six-phase workflow is implemented: evidence ingestion → timeline/anomalies →
competing hypotheses → read-only investigation → deterministic confidence → impact
assessment → recovery recommendation → exact-action human approval → simulated state
change → sustained verification → failed-fix replanning → report and evaluation.
Groq is the selected provider. All environment changes are simulated; no production
control API, shell command, or arbitrary code tool is exposed to the agents.

## Run the complete workflow

Set `GROQ_API_KEY` and `GROQ_MODEL` in `aiops-agent/.env`. The configured model for this
workspace is `openai/gpt-oss-120b`; model availability was checked with Groq. Process
environment variables override `.env`. Keys are never included in reports or prompts.

From the repository root:

```powershell
python -m pip install -r aiops-agent/requirements.txt
$env:PYTHONPATH = (Resolve-Path aiops-agent).Path
python -m unittest discover -s aiops-agent/tests -v
python aiops-agent/run_incident.py data_bulk --output aiops-agent/report.json
```

The default run performs read-only investigation and prepares a dry-run recovery plan.
If confidence is insufficient it reports that result and escalates rather than
inventing a root cause or action. To review and explicitly approve simulated actions:

```powershell
python aiops-agent/run_incident.py data_bulk --interactive --output aiops-agent/report.json
```

The CLI displays the exact action, target, parameters, expected effect, risk, blast
radius, rollback plan and verification conditions. Enter the displayed `APPROVE ...`
phrase to authorize that one unchanged action. A changed action or second action needs
separate approval; tokens are single-use. EOF or any other response declines. No
automatic approval flag exists. The default `dry_run=True` never mutates state.

`report.json` includes source availability, timeline, metric/log signals, trace error
rates, dependency paths, hypotheses, supporting/contradicting/neutral evidence, score
breakdowns, tool calls/results, impact, recovery/approval/execution/verification,
replanning, redacted model transcripts, audit trail, durations and evidence references.
The intermediate `inspect_*` scripts below remain available for phase-specific QA.

## Confidence, recovery and evaluation

`confidence_engine.py` deduplicates hypothesis/evidence pairs and calculates
`reliability × relevance × timing × dependency × direction` per record. LLM relevance
is bounded to 0..1, while source reliability, timestamp checks and graph relevance
are enforced in Python. Direction is +1/+0.5/0/-0.5/-1. Source reliability is documented
in `RELIABILITY`; direct/indirect/unrelated/unknown dependency weights are 1/.65/.1/.4.
Unknown timing gets .5; later positive evidence gets 0 for establishing earlier cause.
Late alleged causal changes and strong relevant contradictions are explicitly retained
and block a conclusion until resolved. LLM priors never contribute to scores.

The score is `max(0, signed mass)/(2 + positive mass + contradiction mass)`, a normalized
heuristic, not a calibrated probability. Neutral evidence cannot increase it. Default
confirmation requires score >= .65, lead >= .15 and at least two material supporting
records, without unresolved critical contradictions. Missing telemetry and partial
graphs remain explicit uncertainties. Defaults can be changed with CLI
`--confidence-threshold`, `--confidence-margin`, `--baseline-minutes`,
`--observation-minutes` and `--min-baseline-samples`. Fixed baseline assumptions and
correlated observations remain limitations; thresholds are not calibrated to production.

The timeline estimates onset from the first three consecutive strong adverse
error/latency observations when available, keeping isolated earlier errors separately.
Without such a run it uses a clearly marked weak estimate or unknown onset.

`approval_gate.py` owns the simulated versions/config/replicas/restart counters and
execution history. Registered action types are `rollback_deployment`, `revert_config`,
`restart_service`, and `scale_service`. JSON schemas, observed targets, cited evidence,
exact action digests and one-use approvals guard execution. Reapplying an unchanged
state is recorded as no state change, not successful repair.

`verifier.py` opens verification data only after checking the exact approved execution
against simulated state. It selects `after_rollback`, `after_flag_disable` (config
revert to false/off/disabled), or `no_action`; unsupported mappings do not fabricate
observations. It requires at least three comparable observations, checks all supplied
affected baselines, detects deterioration and distinguishes recovered, partially
recovered, not recovered, and insufficient verification data. Higher-worse recovery
improvement is `(incident-post)/(incident-baseline)` only with a nonzero denominator.
Failure reopens investigation with a state-result evidence summary, never raw harness
observations. Rankings are recalculated, and another action needs another approval.

For an unambiguous harness, each verification branch can include:

```json
{
  "action": {"target": "an-observed-service", "parameters": {"version": "an-observed-version"}},
  "start": "2026-01-01T00:00:00Z",
  "interval_seconds": 60,
  "points": [
    {"service": "an-observed-service", "latency_ms": 12},
    {"service": "an-observed-service", "latency_ms": 11},
    {"service": "an-observed-service", "latency_ms": 12}
  ]
}
```

Nested `points[].<service>.<metric>` and service-labelled metric/value rows are also
accepted. Unlabelled flat observations are not attributed to invented services.
Legacy branches without exact action bindings can establish at most partial recovery;
missing dependent-service observations also prevent a full recovery claim. Supplied
scenario files are never rewritten to satisfy these checks.

Evaluate produced reports for every discovered scenario:

```powershell
python aiops-agent/evaluate.py
# Produce fresh read-only reports via Groq before scoring each scenario:
python aiops-agent/evaluate.py --live
```

Evaluation discovers scenario folders beside the project or under `scenarios/`.
`data_bulk` is one of six intended scenarios; only folders actually present are counted.
Only `evaluate.py` reads `key_evidence.json`, after the runtime report is produced.
The runtime never imports evaluation. Comparable ground truth uses `root_cause_type`,
`expected_root_cause` or `root_cause` (taxonomy string or object with `type`), and
`key_evidence_ids`, `key_evidence` or `evidence_ids` lists. Unsupported ground-truth
schemas produce unavailable scores, never inferred answers. Evidence coverage uses
records actually investigated/classified, not every ID merely present in the timeline.

`evaluation.json` reports root-cause accuracy where comparable, key-evidence coverage,
duration, false conclusions, simulated recovery observation duration, structural claim
traceability, missing sources, actual failed-fix history and controlled behavior checks.
Traceability validates citations, not semantic truth. Controlled tests inject late
contradictions, verify rank changes, exercise failed fixes and independent approvals,
and check missing sources. They are explicitly separate from dataset accuracy.

Groq may enforce small token-per-minute limits. Requests are bounded and paced using
its response reset headers; HTTP 413/429 errors remain explicit. Context excerpts
retain evidence IDs, contradictions and sampling/omission counts, while full evidence
and score breakdowns stay local. Each investigation is bounded by `MAX_STEPS`, request
and output-token budgets; the complete workflow also caps recovery attempts at two.

Each directory passed to the CLI is an independent scenario. `../data_bulk` is one of
six scenarios; the other five can be supplied later without code changes. Data stays
in its original location. Evidence IDs are local to each scenario and stable for
unchanged files in deterministic filename/record order. References retain original
IDs, record indices, and metric series/point indices. Unknown fields are retained.

From the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path aiops-agent).Path
python -m unittest discover -s aiops-agent/tests -v
python aiops-agent/inspect_scenario.py data_bulk --output aiops-agent/phase1_report.json
python aiops-agent/inspect_tools.py data_bulk --output aiops-agent/phase2_report.json
```

Python 3.11+. Phases 1–2 need no third-party dependencies; Phase 3 requires
`jsonschema` and `python-dotenv` from `requirements.txt`.

The initial 15 minutes of each metric series form the configurable baseline, with
at least 10 valid samples. Population standard deviation yields warning deviations
at absolute z >= 2 and strong deviations at absolute z >= 3. Constant baselines use
an explicit zero-variance deviation marker with null z-score. Direction-unknown
metrics remain uncertain. Baseline health is an assumption, not a confirmed fact.
Log patterns normalize numeric values and common variable IDs. Complete five-minute
windows are compared to baseline counts normalized to the same duration; smoothing
epsilon is 1, minimum current count is 5, and spike ratio threshold is 3.

The timeline's incident start is only the earliest observed signal estimate, never
an established causal onset. Trace request rates represent observed requests only;
no production request counts are inferred from unrelated logs or metric rates.

`key_evidence` and `verification_metrics` files are excluded before parsing for every
supported extension. No harness contents enter the store or report. The local report
contains provenance and normalized log patterns; treat it as sensitive telemetry.
Phase 3 redacts agent-bound telemetry recursively before transmission. Phases 1–2
send no telemetry to any provider.

## Phase 2 interfaces

`dependency_engine.py` constructs caller-to-dependency edges from trace parent IDs
and preserves each branching span tree. Same-service spans remain in request paths
but do not create service self-dependencies. Missing parents, ambiguous duplicate
span IDs, and cyclic ancestry are reported instead of inventing edges. Explicit
dependency records accept `caller`/`callee` strings or `service`/`depends_on` (a string
or list); unsupported shapes remain evidence but generate a graph issue.

Graph coverage is always partial: even an explicit file does not establish complete
telemetry. Upstream reachability gives potential blast radius, with direct and indirect
dependents separated by distance. It does not establish that each dependent failed.
Every relationship and request path cites stored evidence IDs.

`tools.py` provides nine plain Python functions and a strict registry. Agent-facing
calls must use `InvestigationTools(store, audit).call(name, arguments)` so arguments,
results, errors, and returned evidence IDs are audited. No shell or arbitrary code
execution is registered. Unexpected tool exceptions are returned as errors with no
supporting evidence.

Time ranges use `{ "start": "...timezone...", "end": "...timezone..." }`, with an
inclusive start and exclusive end. Omitted filters search all available observations.
Log patterns and search terms are case-insensitive literal substrings, not regular
expressions. Log queries can match service, node, or pod; trace service filters inspect
nested spans. `limit` defaults to 100 (maximum 500); `offset` and `next_offset` support
bounded pages. Results include total matches, evidence IDs for returned records,
source status, and any partial-source or missing-timestamp uncertainty. Returned
records are copies, so callers cannot mutate stored evidence through tool results.

Missing or invalid sources return `unavailable` with `SOURCE_UNAVAILABLE`; valid
sources with no matches return `empty`. `get_dependencies` can succeed using traces
when explicit dependencies are absent. A graph that does not contain a queried
service returns `empty`, never an invented relationship.

`AuditLog()` stores immutable snapshots of events in memory. `AuditLog(path)` also
appends JSONL and resumes sequence IDs from an existing log. The Phase 2 inspection
report includes the complete audit trail, tool inputs/outputs, graph, and provenance.
Keep reports/audit files outside scenario directories. No provider receives telemetry
in Phases 1–2.

## Phase 3 agents and Groq configuration

`agents.py` implements four independent roles with prompts in `prompts/`:

| Role | Responsibility |
| --- | --- |
| `hypothesis_agent` | Evidence-backed competing predictions from the seven-type taxonomy |
| `orchestrator` | Select a registered read-only check, reconsider hypotheses, or stop |
| `evidence_evaluator` | Classify every new-evidence/hypothesis pair, including contradictions |
| `remediation_agent` | Propose evidence-backed exact simulated actions; never execute them |

`playbooks.json` contains type-specific confirming/contradicting patterns, required
signals, tools, metrics, log/trace patterns, red herrings, risks, actions and verification
conditions. Hypothesis generation sees all seven; evaluation and remediation see
the types relevant to their current hypotheses. Guidance is not scenario ground truth.

`agent_schemas.py` supplies JSON Schema contracts validated locally with jsonschema.
Provider JSON-object mode does not replace local validation. Schema-invalid JSON,
unknown/unpresented evidence IDs, duplicate IDs, incomplete evaluator matrices,
unregistered tools and unsupported tool arguments are rejected. Invalid outputs get
exactly one correction attempt. HTTP failures/refusals stop with an explicit error.
Schemas validate structure and citation existence; they cannot prove a free-text
interpretation true. Deterministic timing/dependency weighting follows in Phase 4.

Groq uses its documented [OpenAI-compatible endpoint](https://console.groq.com/docs/openai)
and [Chat Completions contract](https://console.groq.com/docs/api-reference).
No model or key is hardcoded. Set `GROQ_MODEL` and `GROQ_API_KEY` (or generic
`LLM_MODEL` and `LLM_API_KEY`). `aiops-agent/.env` is loaded automatically and process
environment variables take precedence. No scenario-directory `.env` is loaded.
`.env.example` documents the settings. For example, in your own PowerShell session:

```powershell
$env:LLM_PROVIDER = "groq"
$env:GROQ_MODEL = Read-Host "Groq model ID available to your account"
$env:GROQ_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host "Groq API key" -AsSecureString)).Password
python -m pip install -r aiops-agent/requirements.txt
python aiops-agent/inspect_agents.py data_bulk --output aiops-agent/phase3_report.json
```

The model must support JSON-object output and temperature 0..0.2. Default temperature
is 0.1. Each request caps completion tokens at 3,000 and the complete serialized input
at 48,000 UTF-8 bytes. `MAX_STEPS` defaults to 5, with at most 24 provider requests and
48,000 reserved output tokens across the session. Each attempted request reserves its
full output cap, including retries; budget exhaustion stops investigation. Input bytes
are a prompt-size limit, not an exact token count. Provider token usage is recorded
where returned. No automatic network retries extend these budgets. Models/accounts
with smaller context or rate limits can still reject a request explicitly.

`redaction.py` masks sensitive keys and common email, IP, credential, authorization,
phone and identifier patterns; the configured API key is also explicitly removed.
The agent view allowlists useful record fields, omits user identifiers and stack
dumps, truncates long messages/large span arrays with explicit markers, and labels
sampled context. Heuristic redaction is not a guarantee for every arbitrary PII format;
extend it when introducing a new telemetry schema. Local raw Phase 1–2 reports/audits
remain sensitive. Agent transcripts save the actual redacted messages and validated
outputs, never the authorization header. Redirects are rejected to protect credentials.

Prepare the actual initial input without credentials or network access:

```powershell
python aiops-agent/inspect_agents.py data_bulk --prepare-only --output aiops-agent/phase3_prepared_input.json
```

The read-only loop generates hypotheses, evaluates seed evidence, executes registered
tools, evaluates new records in batches, and presents contradictions/errors to the
planner. Reconsideration replaces predictions and reevaluates evidence, recording a
replanning history. It never evaluates tool errors as causal evidence. Repeated
identical tool calls are skipped and each loop is bounded. Context sampling and any
omitted evidence are explicitly marked; tools can retrieve additional pages.

The confidence assessment remains `pending_phase4`; no LLM prior is used as a score,
no root cause is confirmed, and no remediation executes. The remediation role is
contract-tested independently and rejects proposals without a confirmed assessment,
an observed target, and structured evidence for exact parameters. Its execution and
approval binding will be connected in Phase 5.

Validation artifacts in this workspace:

- `phase3_prepared_input.json`: actual redacted initial `data_bulk` input; no model called.
- `phase3_contract_examples.json`: four roles' input/output examples from explicitly
  synthetic scripted tests, not live findings or calculated confidence.
- `phase3_live_status.json`: historical pre-configuration check, when credentials/model
  were unavailable; it is not a current authentication result. Later model discovery
  authenticated successfully. Live incident telemetry validation still requires
  explicit approval to disclose the prepared redacted payload to Groq.

Run the complete test suite with the same unittest command above. Agent tests cover
all four schemas, retry bounds, evidence references, redaction, transport request
shape, loop tool execution, missing-source handling, replanning and budget limits.
