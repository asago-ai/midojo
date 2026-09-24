"""In-memory persistence seam with immutable evaluation session bindings.

Session lookup and callback mutation share an evaluation lock so completion
cannot race a late callback. Persistent storage can implement the same Store
contract later.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from functools import wraps
from threading import RLock
from typing import Any, Concatenate, Protocol

from midojo.types import Environment, FunctionCallRecord, SuiteName

from .models import CreateFunctionCallRecord
from .state import Evaluation, Run


def _new_id() -> str:
    return uuid.uuid4().hex


class Store(Protocol):
    """Interface for run/evaluation persistence."""

    # --- runs ---
    def create_run(self, suite_name: SuiteName) -> Run: ...
    def get_run(self, run_id: str) -> Run | None: ...
    def list_runs(self) -> list[Run]: ...

    # --- evaluations ---
    def create_evaluation(
        self,
        run_id: str,
        *,
        user_task_id: str,
        injection_task_id: str | None,
        pre_environment: Environment,
        environment: Environment,
        active_injections: dict[str, str],
        agent_input: str | None = None,
    ) -> Evaluation: ...
    def get_evaluation(self, run_id: str, eval_id: str) -> Evaluation | None: ...
    def create_session(self, run_id: str, eval_id: str, ttl_seconds: int) -> tuple[str, str]: ...
    def close_session(self, run_id: str, eval_id: str) -> None: ...
    def session_evaluation(self, session_token: str) -> AbstractContextManager[Evaluation]: ...

    # --- per-evaluation mutations (ID-based) ---
    # Each returns the mutated evaluation, or None if (run_id, eval_id) is unknown.
    def append_function_call(self, run_id: str, eval_id: str, req: CreateFunctionCallRecord) -> Evaluation | None: ...
    def set_environment(self, run_id: str, eval_id: str, environment: Environment) -> Evaluation | None: ...
    def record_observations(self, run_id: str, eval_id: str, source: str, data: Any) -> Evaluation | None: ...
    def set_grade(
        self, run_id: str, eval_id: str, *, utility: bool, security: bool, security_reason: str | None = None
    ) -> Evaluation | None: ...
    def complete_evaluation(self, run_id: str, eval_id: str, agent_output: str) -> Evaluation | None: ...


class InvalidSessionError(ValueError):
    """A callback has no live evaluation binding."""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _locked[**P, R](
    method: Callable[Concatenate[InMemoryStore, P], R],
) -> Callable[Concatenate[InMemoryStore, P], R]:
    @wraps(method)
    def call(self: InMemoryStore, *args: P.args, **kwargs: P.kwargs) -> R:
        with self._lock:
            return method(self, *args, **kwargs)

    return call


class InMemoryStore:
    """Process-local, in-memory :class:`Store`. State is lost on restart."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._evaluation_ids: set[str] = set()
        self._sessions: dict[str, tuple[str, str, float]] = {}
        self._session_tokens: dict[tuple[str, str], set[str]] = {}
        self._evaluation_locks: dict[tuple[str, str], RLock] = {}
        self._lock = RLock()

    def _remove_sessions(self, run_id: str, eval_id: str) -> None:
        for token_hash in self._session_tokens.pop((run_id, eval_id), set()):
            self._sessions.pop(token_hash, None)

    def _evaluation_lock(self, run_id: str, eval_id: str) -> RLock | None:
        return self._evaluation_locks.get((run_id, eval_id))

    # --- runs ---

    @_locked
    def create_run(self, suite_name: SuiteName) -> Run:
        run = Run(id=_new_id(), suite_name=suite_name)
        self._runs[run.id] = run
        return run

    @_locked
    def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    @_locked
    def list_runs(self) -> list[Run]:
        return list(self._runs.values())

    # --- evaluations ---

    @_locked
    def create_evaluation(
        self,
        run_id: str,
        *,
        user_task_id: str,
        injection_task_id: str | None,
        pre_environment: Environment,
        environment: Environment,
        active_injections: dict[str, str],
        agent_input: str | None = None,
    ) -> Evaluation:
        run = self._runs[run_id]
        # Keep evaluation IDs short and unique across every run in this store.
        # The method's lock covers allocation and insertion together.
        eval_id = secrets.token_hex(5)
        while eval_id in self._evaluation_ids:
            eval_id = secrets.token_hex(5)
        evaluation = Evaluation(
            id=eval_id,
            run_id=run_id,
            user_task_id=user_task_id,
            injection_task_id=injection_task_id,
            pre_environment=pre_environment,
            environment=environment,
            active_injections=active_injections,
            agent_input=agent_input,
        )
        run.evaluations[evaluation.id] = evaluation
        self._evaluation_ids.add(evaluation.id)
        self._evaluation_locks[(run_id, evaluation.id)] = RLock()
        return evaluation

    @_locked
    def get_evaluation(self, run_id: str, eval_id: str) -> Evaluation | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        return run.evaluations.get(eval_id)

    def create_session(self, run_id: str, eval_id: str, ttl_seconds: int) -> tuple[str, str]:
        with self._lock:
            evaluation = self.get_evaluation(run_id, eval_id)
            if evaluation is None or evaluation.completed:
                raise InvalidSessionError("Cannot open a session for this evaluation")
            if ttl_seconds <= 0:
                raise ValueError("Session TTL must be positive")
            self._remove_sessions(run_id, eval_id)
            token = secrets.token_urlsafe(32)
            expires = time.time() + ttl_seconds
            token_hash = _token_hash(token)
            self._sessions[token_hash] = (run_id, eval_id, expires)
            self._session_tokens.setdefault((run_id, eval_id), set()).add(token_hash)
            return token, datetime.fromtimestamp(expires, UTC).isoformat()

    def close_session(self, run_id: str, eval_id: str) -> None:
        with self._lock:
            self._remove_sessions(run_id, eval_id)
            evaluation_lock = self._evaluation_lock(run_id, eval_id)
        if evaluation_lock is not None:
            with evaluation_lock:
                pass

    @contextmanager
    def session_evaluation(self, session_token: str) -> Iterator[Evaluation]:
        """Hold the binding valid for a complete callback, including its mutation.

        The evaluation lock prevents completion or revocation between validation
        and mutation without serializing callbacks for other evaluations.
        """
        with self._lock:
            token_hash = _token_hash(session_token)
            binding = self._sessions.get(token_hash)
            if binding is None or binding[2] <= time.time():
                if binding is not None:
                    self._sessions.pop(token_hash)
                    self._session_tokens.get(binding[:2], set()).discard(token_hash)
                raise InvalidSessionError("Invalid, expired, or closed evaluation session")
            run = self._runs.get(binding[0])
            evaluation = run.evaluations.get(binding[1]) if run is not None else None
            if evaluation is None or evaluation.completed:
                raise InvalidSessionError("Invalid, expired, or closed evaluation session")
            evaluation_lock = self._evaluation_lock(binding[0], binding[1])
            assert evaluation_lock is not None
            evaluation_lock.acquire()
        try:
            yield evaluation
        finally:
            evaluation_lock.release()

    # --- per-evaluation mutations ---

    def append_function_call(self, run_id: str, eval_id: str, req: CreateFunctionCallRecord) -> Evaluation | None:
        evaluation_lock = self._evaluation_lock(run_id, eval_id)
        if evaluation_lock is None:
            return None
        with evaluation_lock:
            evaluation = self.get_evaluation(run_id, eval_id)
            if evaluation is None:
                return None
            # Each call's pre-env is the previous call's post-env, chaining from the
            # eval's initial environment; post-env is a deep copy so later mutations
            # don't retroactively change the recorded snapshot.
            if evaluation.function_calls:
                pre_env = evaluation.function_calls[-1].post_environment
            else:
                pre_env = evaluation.pre_environment
            record = FunctionCallRecord(
                **req.model_dump(),
                timestamp=datetime.now(UTC).isoformat(),
                pre_environment=pre_env,
                post_environment=evaluation.environment.model_copy(deep=True),
            )
            evaluation.function_calls.append(record)
            return evaluation

    def set_environment(self, run_id: str, eval_id: str, environment: Environment) -> Evaluation | None:
        evaluation_lock = self._evaluation_lock(run_id, eval_id)
        if evaluation_lock is None:
            return None
        with evaluation_lock:
            evaluation = self.get_evaluation(run_id, eval_id)
            if evaluation is None:
                return None
            evaluation.environment = environment
            return evaluation

    def record_observations(self, run_id: str, eval_id: str, source: str, data: Any) -> Evaluation | None:
        evaluation_lock = self._evaluation_lock(run_id, eval_id)
        if evaluation_lock is None:
            return None
        with evaluation_lock:
            evaluation = self.get_evaluation(run_id, eval_id)
            if evaluation is None:
                return None
            evaluation.observations[source] = data
            return evaluation

    def set_grade(
        self, run_id: str, eval_id: str, *, utility: bool, security: bool, security_reason: str | None = None
    ) -> Evaluation | None:
        evaluation_lock = self._evaluation_lock(run_id, eval_id)
        if evaluation_lock is None:
            return None
        with evaluation_lock:
            evaluation = self.get_evaluation(run_id, eval_id)
            if evaluation is None:
                return None
            evaluation.utility = utility
            evaluation.security = security
            evaluation.security_reason = security_reason
            return evaluation

    def complete_evaluation(self, run_id: str, eval_id: str, agent_output: str) -> Evaluation | None:
        with self._lock:
            evaluation_lock = self._evaluation_lock(run_id, eval_id)
            self._remove_sessions(run_id, eval_id)
        if evaluation_lock is None:
            return None
        with evaluation_lock:
            evaluation = self.get_evaluation(run_id, eval_id)
            if evaluation is None:
                return None
            evaluation.agent_output = agent_output
            evaluation.completed = True
            return evaluation
