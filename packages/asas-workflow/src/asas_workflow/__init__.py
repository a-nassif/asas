"""Asas workflow — graph-based process/approval engine.

Extracted from Teamy (epic WXL-210; extraction epic TEAMY-466, design record
0017 — full design in Teamy's decision record 0011). The package never imports
host models: hosts register system handlers, completion callbacks, subject
renderers, assignee resolvers, and the fail-closed floor resolver via
``registry``; definitions are code-registered specs seeded idempotently
(validate → hash-compare → version-on-change); decisions resume flows via the
best-effort ``events`` seam. Table-owning host contract: ``migrate(engine)``
applies the package Alembic chain (adopt-or-create), ``seed_workflow_definitions``
seeds registered specs.
"""

from .definitions import (  # noqa: F401
    DefinitionSpec,
    NodeSpec,
    TransitionSpec,
    active_definitions_for_purpose,
    clear_registered_specs,
    ensure_definition,
    get_active_definition,
    get_binding,
    register_definition,
    resolve_definition,
    seed_definitions,
    set_binding,
    validate_definition,
)
from .engine import (  # noqa: F401
    EngineError,
    answer_info,
    cancel,
    decide,
    final_decision_of,
    open_instance,
    reassign,
    request_info,
    retry,
)
from .events import emit, subscribe  # noqa: F401
from .migrate import migrate  # noqa: F401
from .seed import seed_workflow_definitions  # noqa: F401
from .models import (  # noqa: F401
    AssigneeStatus,
    DefinitionStatus,
    ExecutionStatus,
    InfoRequest,
    InfoRequestStatus,
    InstanceStatus,
    NodeAssignee,
    NodeDecision,
    NodeExecution,
    NodeType,
    ProcessBinding,
    ProcessDefinition,
    ProcessInstance,
    ProcessNode,
    ProcessTransition,
    Verdict,
)
from .registry import (  # noqa: F401
    ADMIN_FLOOR,
    bindable_purposes,
    register_assignee_resolver,
    register_assignee_resolver_namespace,
    register_bindable_purpose,
    register_completion_callback,
    register_floor_resolver,
    register_subject_renderer,
    register_system_handler,
    split_principal,
    subject_renderer,
)

__version__ = "0.10.0"
