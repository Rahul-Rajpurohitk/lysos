"""Chem-workbench tools — atom/bond editing, structure inspection, library
match, valid-actions pre-filter, diagnostics. Same operations the human
UI exposes, registered as @tool so the Gemma 4 model can function-call
them directly.

Every tool here mirrors a /workbench/ endpoint and produces identical
results. The agent can either:
  - HTTP POST /workbench/molecule/edit (REST path)
  - Tool-call edit_molecule (function-calling path)
…and get the exact same JSON shape back. The UI subscribes to the
playground store; tool-calls + REST calls both update it.

Categories:
  - chem_workbench/   8 tools (atom/bond/fragment/replace/inspect/match)
"""
from . import edit_molecule         # noqa: F401
from . import replace_smiles        # noqa: F401
from . import inspect_atom          # noqa: F401
from . import valid_actions         # noqa: F401
from . import diagnostics           # noqa: F401
from . import list_bonds            # noqa: F401
from . import match_known           # noqa: F401
from . import list_elements         # noqa: F401
from . import attach_fragment       # noqa: F401
from . import attach_functional     # noqa: F401
