"""
ConsensusEvaluator: early-exit node for the DAG (Phase 10.3).

Checks whether a set of agent proposals agree sufficiently to skip the
challenge round — saving one full parallel LLM call batch.

Agreement heuristic (v1): keyword overlap ratio across proposal texts.
Replace with embedding cosine similarity when latency budget allows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ConsensusResult:
    reached: bool
    score: float          # 0.0 – 1.0
    dominant_theme: str   # most common non-stopword from proposals
    dissenting_agents: list[str]


_STOPWORDS = frozenset(
    "the a an and or but in on at to for of with is are was were be been "
    "being have has had do does did will would could should may might must "
    "shall can this that these those it its we they them their i you your".split()
)


def _keyword_set(text: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


class ConsensusEvaluator:
    """
    Evaluate whether a set of agent proposals have reached consensus.

    Args:
        threshold: Minimum agreement score (0–1) to declare consensus.
                   Default 0.65 means 65% keyword overlap between proposals.
    """

    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = threshold

    def evaluate(self, proposals: dict[str, str]) -> ConsensusResult:
        """
        proposals: {agent_name: response_text}
        Returns ConsensusResult with reached=True if agreement >= threshold.
        """
        if len(proposals) < 2:
            return ConsensusResult(
                reached=True, score=1.0,
                dominant_theme="", dissenting_agents=[],
            )

        keyword_sets = {name: _keyword_set(text) for name, text in proposals.items()}

        # Pairwise Jaccard similarity
        names = list(keyword_sets)
        pair_scores: list[float] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = keyword_sets[names[i]], keyword_sets[names[j]]
                union = a | b
                jaccard = len(a & b) / len(union) if union else 1.0
                pair_scores.append(jaccard)

        avg_score = sum(pair_scores) / len(pair_scores)

        # Find dominant theme (most frequent keyword across all proposals)
        all_words: list[str] = []
        for kw in keyword_sets.values():
            all_words.extend(kw)
        freq: dict[str, int] = {}
        for w in all_words:
            freq[w] = freq.get(w, 0) + 1
        dominant = max(freq, key=freq.get) if freq else ""

        # Identify dissenters (agents whose keyword overlap with others is below threshold)
        dissenters: list[str] = []
        for name in names:
            others = [keyword_sets[n] for n in names if n != name]
            combined_others = set().union(*others)
            own = keyword_sets[name]
            union = own | combined_others
            overlap = len(own & combined_others) / len(union) if union else 1.0
            if overlap < self.threshold:
                dissenters.append(name)

        return ConsensusResult(
            reached=avg_score >= self.threshold,
            score=round(avg_score, 3),
            dominant_theme=dominant,
            dissenting_agents=dissenters,
        )