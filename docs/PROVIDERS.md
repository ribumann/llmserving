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
| Fresh full authenticated cloud release acceptance | Blocked by external Graph/SSO bootstrap device policy | Separate real-model validation required | Unsupported | Unsupported |

AWS/GCP are non-blocking experimental directions, not working adapters,
deployment targets, or tested portability claims. No placeholder adapter or
Azure fallback is registered for them; do not persist a profile that claims
otherwise.

Azure quota/SKU visibility is not physical allocation. Quota headroom must cover
the requested VM's vCPU count; quota success does not prove GPU stock, Spot
availability, model VRAM fit, networking, consent, or authentication. A
deallocated GPU VM is not a running model; restarting and warming the model are
separate states. Database readiness is also independent of API process liveness.

Capability flags describe checked-in routing, not deployment test evidence.
In particular, `durableEvaluation=false` must remain honest until golden,
benchmark, LLMPerf and report semantics match the proven backend path and
restart/duplicate/cancellation/failure handling has been exercised.
