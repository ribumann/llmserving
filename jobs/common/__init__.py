"""Shared helpers for Azure Container Apps Jobs workers (T136/T137).

Every worker under jobs/ (terraform_runner, model_deployment, evaluation_worker,
performance_worker, export_worker) is an independent, isolated container image -
this package is copied into each worker's image at build time rather than being
installed as a shared dependency, since Container Apps Jobs images have no
runtime access to a shared filesystem or package index beyond what each
Dockerfile bakes in.
"""
