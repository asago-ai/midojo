# Design note: EvaluationContext and the env / verification axes

Status: implemented
Branch: `acs-runtime-oracle`
Date: 2026-06-01

## Problem

Every predicate's `evaluate` repeats the same signature:

```python
def evaluate(self, agent_output, pre_env, post_env, ctx: GradingContext = None) -> bool
```

`ctx` feels bolted on: it sits *next to* the env args as a half-used optional 4th
wheel, most predicates ignore it, and its type is a loose `dict[str, Any] | None`.
The same long signature is repeated across ~13 predicate/combinator classes
(8 builtin, 2 ACS, 3 combinators).

The awkwardness is a symptom. The real issue: a predicate may read evidence from
two different places — the **environment** (pre/post snapshots, agent output) and a
**verification provider** (RHACS runtime oracle, future filesystem/network/k8s
backends) — and today those two sources are passed through different mechanisms
(positional args vs. the tacked-on `ctx` dict).

## Background: two orthogonal axes

Per the platform doc, MiDojo's observability extends along two axes that are
deliberately *not* a fixed pair (the relationship is many-to-many):

- **Environment backend** — *what the agent operates on*. YAML dict today;
  sandboxed container / cluster resource later. One env can be checked by several
  verifiers.
- **Verification provider** — *how outcomes are checked*. Predicates over env
  state + output today; filesystem inspection, network traffic, k8s audit later.
  One verifier (e.g. the builtin predicate provider) works across many env
  backends.

Note: in the ACS case, the Rox client is **not** the environment — the live
pod/deployment is the environment; the Rox client is the *observability plane*
over it. The binding between them is `namespace / deployment / cluster + time
window`, resolved in `RhacsProvider.setup()`.

## Decision

Collapse everything a predicate may read into a single typed `EvaluationContext`,
and give predicates one stable argument.

```python
@dataclass
class EvaluationContext:
    agent_output: str
    pre_env: Environment
    post_env: Environment
    _providers: dict[str, VerificationProvider] = field(default_factory=dict)

    def provider(self, name: str) -> VerificationProvider:
        if name not in self._providers:
            raise RuntimeError(
                f"Predicate requires the '{name}' verification provider "
                f"(check the relevant env vars are set)."
            )
        return self._providers[name]


class Predicate(Protocol):
    def evaluate(self, ctx: EvaluationContext) -> bool: ...
```

Predicates then read only what they need:

```python
class OutputContains:
    def evaluate(self, ctx: EvaluationContext) -> bool:
        return self.value.lower() in ctx.agent_output.lower()

class AcsProcessMatch:
    def evaluate(self, ctx: EvaluationContext) -> bool:
        provider = ctx.provider("rhacs")   # typed; raises its own clear error
        ...

class AllOf:
    def evaluate(self, ctx: EvaluationContext) -> bool:
        return all(p.evaluate(ctx) for p in self.predicates)
```

### Why a uniform signature (not split predicate kinds)

The tempting alternative — state predicates take `(output, pre, post)`, oracle
predicates take a provider — breaks on the combinators. `all_of` / `any_of` mix
both kinds in one tree and must call a uniform `.evaluate()`. So the signature has
to be identical for everyone, which means one context object.

## What this buys

- One short signature everywhere; the ~13 repeated 4-arg litanies collapse.
- Predicates that don't need a verifier simply never call `ctx.provider(...)` —
  env and output are right there on `ctx`. No optional tail param to ignore.
- `_require_provider` (free function) and `GradingContext = dict | None` (loose
  type) both disappear. The "missing provider" error moves onto `ctx.provider()`.
- Extending is free: add a field to `EvaluationContext` (e.g. `function_calls`,
  which `grade()` already receives but predicates can't see today) without
  touching any `evaluate` signature.

## The provider dict already exists (ephemerally)

There is no persistent `dict[str, VerificationProvider]` registry today. Related
structures:

- `predicates._PARSERS: dict[str, Callable]` — persistent, but keyed by predicate
  YAML key (`"acs_process_match"` → parser fn), not by provider name. Different
  axis.
- `state.providers: list[VerificationProvider]` and
  `providers._KNOWN_PROVIDERS: list[type[...]]` — both lists.

The name→provider dict exists only ephemerally, built once per grade at
`runs.py:143`:

```python
grading_context = {p.name: p for p in providers} if providers else None
```

`EvaluationContext._providers` simply absorbs that line — it is not a new
registry. Follow-on: promote `state.providers` to a `dict[str,
VerificationProvider]` keyed by `.name` (have `discover_providers()` return a
dict). Dict preserves insertion order, so `setup()`/`settle()` iteration is
unaffected, and `runs.grade_evaluation` can pass the dict straight into the
context instead of rebuilding it.

## Rename

`BuiltinProvider` is a *verification* provider (predicates over env state +
output), not an environment. Rename to make the axis explicit, e.g.
`BuiltinPredicateProvider` / `StatePredicateProvider`. The YAML dict loader in
`YAMLTaskSuite` is the thing that would eventually be a "builtin env backend" —
the *other* axis.

## Explicitly deferred

Do **not** introduce an `EnvironmentBackend` ABC yet. There is exactly one env
backend (YAML dict) with no second implementation in sight; the abstraction would
be speculative. The verification axis earns its ABC because it already has two
real implementations (builtin + rhacs). Revisit when a container backend is
actually imminent.

## Scope of the refactor

- `predicates.py` — `EvaluationContext` (here or its own module), `Predicate`
  protocol, combinators, `evaluate_predicate`. Drop `GradingContext`.
- `providers/builtin.py` — 8 predicates to the new signature.
- `providers/rhacs.py` — 2 predicates; drop `_require_provider`.
- `yaml_task_suite.py` / `runs.py` — build `EvaluationContext` from providers +
  env snapshots at grade time.
- Tests — `_ctx(provider)` becomes constructing an `EvaluationContext`.
