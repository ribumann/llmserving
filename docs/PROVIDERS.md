# Provider capabilities and limitations

The authenticated `GET /providers` endpoint reports typed capabilities for
implemented providers. Unknown/missing providers fail explicitly with
`unsupported_provider`, never silently select Azure. Existing profile,
configuration and report schemas are unchanged.

| Capability | Azure | Local Ollama | AWS | GCP |
| --- | --- | --- | --- | --- |
| Implemented provider adapter | Yes | Yes | No | No |
| Infrastructure preview/provision/teardown | Azure SDK + Terraform/Durable jobs | Presenter-managed runtime; no cloud infrastructure | Planned/experimental | Planned/experimental |
| Model deployment | vLLM via managed-identity job/VM Run Command | Ollama pull on local runtime | Not implemented | Not implemented |
| Prompts | vLLM OpenAI-compatible API | Ollama OpenAI-compatible API | Not implemented | Not implemented |
| Golden/benchmark/performance execution | Existing backend in-process orchestrator | Existing backend in-process orchestrator | Not implemented | Not implemented |
| Durable evaluation/performance parity | Not yet certified; worker implementations differ | Not implemented | Not implemented | Not implemented |
| Observed execution / release boundary | Existing deployed Qwen3-4B/vLLM acceptance passed; new-target reproducibility/auth/cleanup remain separately gated | Real CPU API/browser inference smoke merged; not Azure SSO/cloud acceptance | Unsupported | Unsupported |

AWS/GCP are non-blocking experimental directions, not working adapters,
deployment targets, or tested portability claims. No placeholder adapter or
Azure fallback is registered for them; do not persist a profile that claims
otherwise.

Azure quota/SKU visibility is not physical allocation. Quota headroom must cover
the requested VM's vCPU count; quota success does not prove GPU stock, Spot
availability, model VRAM fit, networking, consent, or authentication. A
deallocated GPU VM is not a running model; restarting and warming the model are
separate states. Database readiness is also independent of API process liveness.

Preflight and Terraform resolve the same effective SKU using the existing
`profileSizeClass` mapping (small/medium/large) unless `vmSizeOverride` is set.
The provisioning UI offers Italy North for the Azure 3B profile, including existing
persisted profiles, and passes the chosen VM size override and Spot/Regular priority
to both preview and creation. Changing these inputs requires a new preview. The
selected region must match the shared Terraform network's location: the API passes
the preflighted region to Terraform, which rejects a mismatch before resource
creation. Selecting a region does not create or move a network, and quota/SKU
signals do not guarantee physical allocation capacity.
Profile defaults are merged with request `configurableInputs` in both paths.
The preview endpoint accepts the same optional inputs as creation. Invalid
non-string/empty SKU overrides fail explicitly rather than selecting another VM.
Preflight reads that requested SKU's `vCPUs` capability. The deployed Spot path
checks `lowPriorityCores`; Regular checks its SKU-family quota and total regional
vCPUs. Sufficiency requires `usage + requested vCPUs <= limit`. Missing metadata
or quota records remain unknown, and an unrelated GPU family is never substituted.
The API reports physical `capacityStatus=unknown` even when those checks pass:
only an actual successful allocation establishes capacity.

Environment `lifecycleState` is the persisted workflow state, not a live model
health check. `context.resourceState` reports VM power transitions and distinguishes
an actual 404 from an unavailable lookup. `context.inferenceState=unverified` on a
running VM does not claim that vLLM is warm; stopped/deallocated/starting VMs report
unavailable inference and `coldStartRequired=true`. No saved revision proves
current model health. Permission/network failures report unknown, not deleted.

Capability flags describe checked-in routing, not deployment test evidence.
In particular, `durableEvaluation=false` must remain honest until golden,
benchmark, LLMPerf and report semantics match the proven backend path and
restart/duplicate/cancellation/failure handling has been exercised.

The evaluation worker now imports the backend's pure golden-scoring module
(exact/contains/regex and final-answer reasoning handling), rather than maintaining
a second scorer. Its legacy callback keys/statuses remain unchanged. The shared
scorer also fixes two coupled grading errors in both paths: a reasoning-only
response cannot pass by mentioning an answer in its trace, and regex patterns
retain their case instead of being lowercased along with the rule name.
The legacy performance worker measures successful requests per actual elapsed wall time,
not summed per-request latencies; it still does **not** implement genuine LLMPerf,
token throughput, TTFT or ITL. Neither change certifies complete durable parity:
prompt/model invocation, benchmark execution, report normalization, immutable
snapshots and durable restart/cancellation/ownership gates remain required.
No API routing or capability flag is enabled by these preparatory changes.

For high-level AWS/GCP implementation steps and a copy-paste coding-agent
starter prompt, see [extending to another cloud](PROVIDER_EXTENSION.md).
