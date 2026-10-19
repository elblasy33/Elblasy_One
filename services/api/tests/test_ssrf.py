import pytest

from elblasy_api.security.ssrf import UnsafeUrlError, validate_odoo_url


def res(*ips: str):
    return lambda host, port: list(ips)


def check(url, ips=("93.184.216.34",), **kw):
    kw.setdefault("production", True)
    return validate_odoo_url(url, resolver=res(*ips), **kw)


def test_accepts_public_https():
    v = check("https://erp.example.com/")
    assert v.url == "https://erp.example.com" and v.port == 443


@pytest.mark.parametrize(
    "url,ips",
    [
        ("ftp://erp.example.com", ("93.184.216.34",)),
        ("http://erp.example.com", ("93.184.216.34",)),
        ("https://user:pw@erp.example.com", ("93.184.216.34",)),
        ("https://erp.example.com/?a=1", ("93.184.216.34",)),
        ("https://metadata.google.internal", ("93.184.216.34",)),
        ("https://evil.example.com", ("169.254.169.254",)),
        ("https://evil.example.com", ("::ffff:169.254.169.254",)),
        ("https://evil.example.com", ("127.0.0.1",)),
        ("https://evil.example.com", ("10.0.0.5",)),
        ("https://evil.example.com", ("93.184.216.34", "192.168.1.1")),  # mixed answers
        ("https://evil.example.com", ("0.0.0.0",)),  # noqa: S104
        ("https://evil.example.com", ()),
    ],
)
def test_rejects_unsafe(url, ips):
    with pytest.raises(UnsafeUrlError):
        check(url, ips)


def test_private_allowed_only_with_flag_but_metadata_never():
    assert check("https://erp.lan", ("10.0.0.5",), allow_private=True)
    with pytest.raises(UnsafeUrlError):
        check("https://erp.lan", ("169.254.169.254",), allow_private=True)


def test_http_never_in_production_even_if_flagged():
    with pytest.raises(UnsafeUrlError):
        check("http://erp.example.com", production=True, allow_insecure_http=True)
    assert check("http://erp.example.com", production=False, allow_insecure_http=True)
