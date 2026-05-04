"""AMR-specific tools — the first set of antimicrobial Open Agent Skills.

These 5 tools are unique to Lysos and fill the gap in K-Dense Scientific Agent
Skills (which has 135 skills but ZERO AMR-specific). We contribute these back.
"""
from . import predict_mic_pathogen
from . import check_resistance_genes
from . import predict_resistance_escape
from . import get_pathogen_resistome
from . import find_active_against_mdr
