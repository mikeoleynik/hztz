from hztz.core.config import mask_api_key


def test_mask_short_key():
    assert mask_api_key("abc") == "***"
    assert mask_api_key("12345678") == "********"


def test_mask_long_key():
    assert mask_api_key("sk-1234567890abcdef") == "sk-1…cdef"
