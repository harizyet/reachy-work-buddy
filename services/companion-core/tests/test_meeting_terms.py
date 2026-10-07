"""Phase 41: key-terms candidate generation (the deterministic half of the resolver)."""

import pytest
from companion_core.meetings import terms as T

TERMS = ["Gemini", "Antigravity", "ClickHouse", "Claude", "Codex", "InfluxDB", "Kubernetes"]


def candidates(text: str, terms=TERMS):
    return T.find_candidates([(0, text)], terms)


def test_the_real_mishearing_is_a_candidate_for_the_right_term() -> None:
    found = candidates("And germanite.")
    assert [(c.span, c.terms[0][0]) for c in found] == [("germanite", "Gemini")]
    assert not found[0].spelling_variant


@pytest.mark.parametrize("heard,term", [("anti-gravity", "Antigravity"), ("click house", "ClickHouse"), ("in flux db", "InfluxDB")])
def test_spelling_variants_have_the_same_letters_and_need_no_model(heard: str, term: str) -> None:
    found = candidates(f"We use {heard} here.")
    assert [(c.span, c.terms[0][0], c.spelling_variant) for c in found] == [(heard, term, True)]


def test_a_run_that_already_contains_a_term_or_matches_it_in_case_only_is_left_alone() -> None:
    assert candidates("And codex, and Codex, and Claude.") == []
    assert candidates("We like gemini a lot.") == []


def test_overlapping_runs_keep_only_the_strongest() -> None:
    found = candidates("then anti-gravity too")
    assert len(found) == 1 and found[0].span == "anti-gravity"


def test_short_words_and_unrelated_words_are_ignored() -> None:
    assert candidates("the cat sat on a mat with a hat") == []


def test_phonetic_key_ignores_vowel_noise_and_soft_g() -> None:
    assert T.phonetic_key("germanite")[0] == T.phonetic_key("Gemini")[0] == "j"
    assert T.similarity("germanite", "Gemini") > 0.62
    assert T.similarity("because", "Gemini") < 0.62
