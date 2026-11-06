from app.realtime.factcheck import unverified_figures
from app.realtime.prompts import SAMPLE_CV


def test_flags_invented_figures():
    answer = (
        "I cut p99 latency from 480 ms to 120 ms and duplicates by 98%. "
        "Later I improved latency by 15% within 2 hours, saving $40k in 2021."
    )
    assert unverified_figures(answer, SAMPLE_CV) == ["15%", "2 hours", "$40k", "2021"]


def test_ignores_plain_numbers_and_cv_figures():
    answer = (
        "Return HTTP 429 after 100 req/min. "
        "At Kitecart we served 2M requests; search 70% faster."
    )
    assert unverified_figures(answer, SAMPLE_CV) == []


def test_part_of_a_cv_number_is_not_a_match():
    assert unverified_figures("Duplicates fell by 8%.", SAMPLE_CV) == ["8%"]


def test_cv_years_and_durations_are_known():
    assert unverified_figures("Since 2022, with 6 years of experience.", SAMPLE_CV) == []
