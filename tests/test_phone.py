from pipeline.phone import normalise_value, split_numbers, to_e164


def test_split_on_semicolon_and_comma():
    assert split_numbers("+34 912 345 678; +34 913 456 789,  915550123") == [
        "+34 912 345 678", "+34 913 456 789", "915550123"]


def test_to_e164_uses_country_and_validity():
    assert to_e164("912 345 678", "ES") == "+34912345678"
    assert to_e164("+49 30 12345678", "ES") == "+493012345678"   # explicit country code wins
    assert to_e164("12345", "ES") is None
    assert to_e164("hello", "ES") is None


def test_normalise_value_counts_invalid_and_dedupes():
    nums, invalid = normalise_value("912345678;+34 912 345 678;999", "ES")
    assert nums == ["+34912345678"]
    assert invalid == 1
