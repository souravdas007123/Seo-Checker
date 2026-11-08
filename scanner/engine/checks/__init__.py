from .ai import CHECKS as AI
from .onpage import CHECKS as ONPAGE
from .technical import CHECKS as TECHNICAL

ALL_CHECKS = [*ONPAGE, *TECHNICAL, *AI]
