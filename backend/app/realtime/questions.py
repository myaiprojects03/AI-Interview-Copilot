"""Decide whether an interviewer utterance is a question worth answering.

Fast heuristic on purpose: it runs on every interviewer utterance and adds no latency.
The user can always force an answer with "Answer now".
"""

import re

_QUESTION_STARTS = (
    "what", "why", "how", "when", "where", "which", "who", "whose",
    "can you", "could you", "would you", "will you", "do you", "did you", "have you",
    "are you", "were you", "is there", "is it", "should", "if you",
    "tell me", "describe", "walk me through", "talk me through", "talk about",
    "explain", "give me", "share", "imagine", "suppose", "let's say", "design",
    "write a", "implement", "compare",
)

# Things Whisper tends to "hear" in near-silence or noise.
_HALLUCINATIONS = {
    "", ".", "you", "thank you", "thank you.", "thanks", "thanks for watching",
    "thanks for watching!", "thank you for watching", "bye", "bye.", "okay", "okay.",
    "so", "um", "uh", "hmm",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def normalize(text: str) -> str:
    return " ".join(text.strip().split())


def is_noise(text: str) -> bool:
    t = normalize(text).lower().rstrip(".!? ")
    return t in _HALLUCINATIONS or not any(ch.isalnum() for ch in t)


def is_question(text: str) -> bool:
    t = normalize(text).lower()
    if len(t.split()) < 3:
        return False
    if t.endswith("?"):
        return True
    for sentence in _SENTENCE_SPLIT.split(t):
        if _strip_fillers(sentence).startswith(_QUESTION_STARTS):
            return True
    return False


_FILLERS = ("so ", "okay ", "ok ", "alright ", "right ", "and ", "great ", "now ", "next ", "well ")


def _strip_fillers(sentence: str) -> str:
    s = sentence.strip().replace(",", "")
    changed = True
    while changed:
        changed = False
        for filler in _FILLERS:
            if s.startswith(filler):
                s = s[len(filler):]
                changed = True
    return s
