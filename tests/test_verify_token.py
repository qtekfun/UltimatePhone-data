from pipeline.verify import fts_token


def test_token_follows_the_fts_tokenizer_not_whitespace():
    assert fts_token("WS-Transporte GmbH") == "WS"
    assert fts_token("Café Central") == "Café"
    assert fts_token("  O'Neill's ") == "O"
    assert fts_token("Bäckerei_Müller") == "Bäckerei"


def test_token_of_a_name_without_words_is_empty():
    assert fts_token("---") == ""
    assert fts_token("") == ""
