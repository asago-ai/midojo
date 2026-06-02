"""Built-in verifiers.

Importing this package registers the verifiers MiDojo ships with. Add a new
built-in verifier by dropping a module here and importing it below; it
self-registers via :func:`midojo.verifier.register_verifier`.
"""

from midojo.verifiers import builtin as _builtin  # noqa: F401  -- registers the default verifier
