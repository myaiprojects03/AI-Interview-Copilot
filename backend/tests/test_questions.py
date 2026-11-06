import pytest

from app.realtime.questions import is_noise, is_question


@pytest.mark.parametrize(
    "text",
    [
        "Can you tell me a little about yourself?",
        "Tell me about a time you disagreed with a teammate.",
        "So, walk me through how you'd design a URL shortener.",
        "Okay. How would you design a rate limiter for a public API",
        "I see you worked at Kitecart. What was the hardest part of that role?",
        "Explain the difference between a process and a thread.",
        "Great, and why do you want to work here",
    ],
)
def test_questions(text):
    assert is_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "Great, thanks.",
        "That makes sense.",
        "Okay?",
        "I worked on payments for three years.",
        "Let me share my screen first.",
    ],
)
def test_not_questions(text):
    assert not is_question(text)


@pytest.mark.parametrize("text", ["", " . ", "Thank you.", "you", "Thanks for watching!", "..."])
def test_whisper_noise(text):
    assert is_noise(text)


def test_real_text_is_not_noise():
    assert not is_noise("Thank you for coming in today.")
