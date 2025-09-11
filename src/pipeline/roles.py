from __future__ import annotations

import re
from enum import IntEnum
from typing import List, Optional, Tuple


class DecisionLevel(IntEnum):
    UNKNOWN = 0
    NON_DM = 1
    MGMT = 2
    VP_PLUS = 3
    C_SUITE = 4

    @classmethod
    def from_str(cls, s: str) -> "DecisionLevel":
        if s is None:
            return cls.UNKNOWN
        key = str(s).strip().upper().replace("-", "_").replace(" ", "_")
        mapping = {
            "UNKNOWN": cls.UNKNOWN,
            "NON_DM": cls.NON_DM,
            "NONDM": cls.NON_DM,
            "MGMT": cls.MGMT,
            "VP_PLUS": cls.VP_PLUS,
            "VP": cls.VP_PLUS,
            "C_SUITE": cls.C_SUITE,
            "CSUITE": cls.C_SUITE,
        }
        return mapping.get(key, cls.UNKNOWN)


# Separators for tokenization (info only; classification uses regex on the whole string)
_TOKEN_SPLIT_RE = re.compile(r"[ ,;|/–—·]+")

# Negative (exclude) patterns — checked before inclusives (except 'general counsel')
_NEGATIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bof counsel\b", re.I), "of counsel"),
    (re.compile(r"\bcounsel\b", re.I), "counsel"),
    (re.compile(r"\bassociate\b", re.I), "associate"),
    (re.compile(r"\bassistant\b", re.I), "assistant"),
    (re.compile(r"\bjunior\b", re.I), "junior"),
    (re.compile(r"\bcoordinator\b", re.I), "coordinator"),
    (re.compile(r"\bspecialist\b", re.I), "specialist"),
    (re.compile(r"\banalyst\b", re.I), "analyst"),
    (re.compile(r"\bintern\b", re.I), "intern"),
    (re.compile(r"\btrainee\b", re.I), "trainee"),
    (re.compile(r"\bstaff\b", re.I), "staff"),
    (re.compile(r"\bsupport\b", re.I), "support"),
    (re.compile(r"\bparalegal\b", re.I), "paralegal"),
]

# Inclusive patterns with associated levels and human-readable labels
# Order matters: more specific patterns first
_POSITIVE_PATTERNS: list[tuple[re.Pattern[str], DecisionLevel, str]] = [
    # C_SUITE
    (re.compile(r"\bgeneral counsel\b", re.I), DecisionLevel.C_SUITE, "general counsel"),
    (re.compile(r"(?<!vice )\bpresident\b", re.I), DecisionLevel.C_SUITE, "president"),
    (re.compile(r"\bmanaging director\b", re.I), DecisionLevel.C_SUITE, "managing director"),
    (re.compile(r"\bmanaging partner\b", re.I), DecisionLevel.C_SUITE, "managing partner"),
    (re.compile(r"\bexecutive director\b", re.I), DecisionLevel.C_SUITE, "executive director"),
    (re.compile(r"\bchief [a-z]+ officer\b", re.I), DecisionLevel.C_SUITE, "chief officer"),
    (re.compile(r"\bceo\b", re.I), DecisionLevel.C_SUITE, "ceo"),
    (re.compile(r"\bcfo\b", re.I), DecisionLevel.C_SUITE, "cfo"),
    (re.compile(r"\bcoo\b", re.I), DecisionLevel.C_SUITE, "coo"),
    (re.compile(r"\bcto\b", re.I), DecisionLevel.C_SUITE, "cto"),
    (re.compile(r"\bcmo\b", re.I), DecisionLevel.C_SUITE, "cmo"),
    (re.compile(r"\bcio\b", re.I), DecisionLevel.C_SUITE, "cio"),
    (re.compile(r"\bco-?chair\b", re.I), DecisionLevel.C_SUITE, "co-chair"),
    (re.compile(r"\bgroup chair\b", re.I), DecisionLevel.C_SUITE, "group chair"),
    (re.compile(r"\bchair\b", re.I), DecisionLevel.C_SUITE, "chair"),
    # VP_PLUS
    (re.compile(r"\bsenior director\b", re.I), DecisionLevel.VP_PLUS, "senior director"),
    (re.compile(r"\bhead of\b", re.I), DecisionLevel.VP_PLUS, "head of"),
    (re.compile(r"\bvice president\b", re.I), DecisionLevel.VP_PLUS, "vice president"),
    (re.compile(r"\bsvp\b", re.I), DecisionLevel.VP_PLUS, "svp"),
    (re.compile(r"\bevp\b", re.I), DecisionLevel.VP_PLUS, "evp"),
    (re.compile(r"\bvp\b", re.I), DecisionLevel.VP_PLUS, "vp"),
    (re.compile(r"\bshareholder\b", re.I), DecisionLevel.VP_PLUS, "shareholder"),
    (re.compile(r"\bprincipal\b", re.I), DecisionLevel.VP_PLUS, "principal"),
    (re.compile(r"\bpartner\b", re.I), DecisionLevel.VP_PLUS, "partner"),
    # MGMT (only if negatives didn't trigger)
    (re.compile(r"\bdirector\b", re.I), DecisionLevel.MGMT, "director"),
    (re.compile(r"\blead\b", re.I), DecisionLevel.MGMT, "lead"),
    (re.compile(r"\bmanager\b", re.I), DecisionLevel.MGMT, "manager"),
]

# Structural hints coming from URL context
_STRUCT_HINTS = [
    "leadership",
    "executive",
    "management",
    "board",
    "partners",
    "shareholders",
    "principals",
]


def _normalize(s: Optional[str]) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()


def classify_role(title: Optional[str], url_ctx: Optional[str] | None = None) -> Tuple[DecisionLevel, List[str]]:
    """Classify a role title into a DecisionLevel and return reasons.

    - Negative markers win over inclusives (except 'general counsel' is C_SUITE and overrides 'counsel').
    - Structural hints from URL context can bump UNKNOWN/MGMT up one level (not above C_SUITE).
    - Robust to None/empty inputs.
    """
    reasons: List[str] = []
    tnorm = _normalize(title)

    if not tnorm:
        # No title info
        level = DecisionLevel.UNKNOWN
    else:
        # Tokenize (not strictly needed for regex-based checks, but kept for spec compliance)
        _TOKEN_SPLIT_RE.split(tnorm)

        # Special-case: if 'general counsel' present, treat as C_SUITE regardless of 'counsel' negatives
        if re.search(r"\bgeneral counsel\b", tnorm, re.I):
            level = DecisionLevel.C_SUITE
            reasons.append("title:general counsel")
        else:
            # Negatives first
            for pat, label in _NEGATIVE_PATTERNS:
                if pat.search(tnorm):
                    level = DecisionLevel.NON_DM
                    reasons.append(f"exclude:{label}")
                    break
            else:
                # Positives in order
                level = DecisionLevel.UNKNOWN
                for pat, lvl, label in _POSITIVE_PATTERNS:
                    if pat.search(tnorm):
                        level = max(level, lvl)  # keep the strongest match if multiple
                        reasons.append(f"title:{label}")
                        # Do not break to allow capturing multiple reasons; final level is the strongest
                if level is DecisionLevel.UNKNOWN:
                    # No matches
                    level = DecisionLevel.UNKNOWN

    # Structural hints: bump UNKNOWN/MGMT up one step (not above C_SUITE)
    if url_ctx:
        u = _normalize(url_ctx)
        for key in _STRUCT_HINTS:
            if key in u:
                # Record the first structural reason encountered
                reasons.append(f"struct:{key}")
                if level in (DecisionLevel.UNKNOWN, DecisionLevel.MGMT):
                    bumped = DecisionLevel(min(level + 1, DecisionLevel.C_SUITE))
                    level = bumped
                break

    return level, reasons

