"""Tests for text helpers (no network)."""
from playcache.textutils import (
    best_match,
    clean_search_query,
    format_rating,
    join_names,
    similarity,
    strip_html,
    truncate,
)


class TestStripHtml:
    def test_strips_tags_and_entities(self):
        assert strip_html("<p>Hollow <b>Knight</b> &amp; friends</p>") == "Hollow Knight & friends"

    def test_none_and_empty(self):
        assert strip_html(None) == ""
        assert strip_html("") == ""

    def test_collapses_whitespace(self):
        assert strip_html("a\n\n  b\tc") == "a b c"


class TestTruncate:
    def test_short_unchanged(self):
        assert truncate("short", 100) == "short"

    def test_long_truncated_with_ellipsis(self):
        text = "word " * 100
        out = truncate(text, 40)
        assert len(out) <= 41
        assert out.endswith("…")

    def test_exact_length(self):
        assert truncate("exact", 5) == "exact"


class TestFormatRating:
    def test_whole_number(self):
        assert format_rating(9.0) == "9/10"

    def test_half(self):
        assert format_rating(8.5) == "8.5/10"

    def test_zero_returns_empty(self):
        assert format_rating(0) == ""

    def test_none_returns_empty(self):
        assert format_rating(None) == ""

    def test_rounds_to_one_decimal(self):
        # Python uses banker's rounding (7.25 -> 7.2); just confirm format + suffix
        assert format_rating(7.25).endswith("/10")
        assert format_rating(7.24) == "7.2/10"
        assert format_rating(7.26) == "7.3/10"

    def test_rawg_rating_doubled(self):
        # RAWG rating 4.5 / 5 -> 9.0 / 10
        assert format_rating(4.5 * 2) == "9/10"


class TestSimilarity:
    def test_identical(self):
        assert similarity("Hollow Knight", "Hollow Knight") == 100.0

    def test_different(self):
        assert similarity("Hollow Knight", "Doom Eternal") < 50.0

    def test_empty(self):
        assert similarity("", "anything") == 0.0


class TestBestMatch:
    def test_picks_best(self):
        candidates = [
            ("Hollow Knight: Silksong", {"id": 2}),
            ("Hollow Knight", {"id": 1}),
            ("Hollow", {"id": 3}),
        ]
        match = best_match("Hollow Knight", candidates, threshold=50)
        assert match["id"] == 1

    def test_no_match_below_threshold(self):
        candidates = [("Completely Different", {"id": 1})]
        assert best_match("Hollow Knight", candidates, threshold=80) is None

    def test_substring_boost(self):
        candidates = [("Hollow Knight", {"id": 1})]
        match = best_match("Hollow Knight", candidates, threshold=50)
        assert match["id"] == 1


class TestJoinNames:
    def test_join(self):
        items = [{"name": "Action"}, {"name": "RPG"}]
        assert join_names(items) == "Action / RPG"

    def test_empty(self):
        assert join_names(None) == ""
        assert join_names([]) == ""

    def test_skips_missing_key(self):
        assert join_names([{"name": "X"}, {"foo": "y"}]) == "X"


class TestCleanSearchQuery:
    def test_preserves_intra_word_hyphen(self):
        assert clean_search_query("Half-Life") == "Half-Life"
        assert clean_search_query("Counter-Strike") == "Counter-Strike"

    def test_strips_colon_subtitle(self):
        assert clean_search_query("Hollow Knight: Voidheart Edition") == "Hollow Knight"

    def test_strips_spaced_hyphen_subtitle(self):
        assert clean_search_query("Some Game - subtitle") == "Some Game"

    def test_strips_en_dash_subtitle(self):
        assert clean_search_query("Some Game – subtitle") == "Some Game"

    def test_plain_name_unchanged(self):
        assert clean_search_query("Deep Rock Galactic") == "Deep Rock Galactic"

    def test_preserves_year_in_title(self):
        assert clean_search_query("Cyberpunk 2077") == "Cyberpunk 2077"
