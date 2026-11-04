"""Test helpers for jobs/: adds jobs/ to sys.path so tests can import the
shared `common` package, and provides `load_worker_entrypoint()` to load each
standalone worker's `entrypoint.py` under a unique module name.

Every worker's entrypoint module is named `entrypoint.py` (required so each
container's `ENTRYPOINT ["python", "entrypoint.py"]` works identically), so
naively adding every worker directory to sys.path and `import entrypoint`
would have every test file share one cached `sys.modules["entrypoint"]` -
whichever worker's test imported it first. `load_worker_entrypoint` avoids
that by loading each worker's file under a distinct name via importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

JOBS_ROOT = Path(__file__).resolve().parent.parent
if str(JOBS_ROOT) not in sys.path:
    sys.path.insert(0, str(JOBS_ROOT))


def load_worker_entrypoint(worker_name: str) -> ModuleType:
    module_name = f"_jobs_test_{worker_name}_entrypoint"
    if module_name in sys.modules:
        return sys.modules[module_name]

    entrypoint_path = JOBS_ROOT / worker_name / "entrypoint.py"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
