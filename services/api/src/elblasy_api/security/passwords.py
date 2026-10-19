"""Password policy. Length is enforced by the request models (>= 12); this adds the checks a length
rule cannot: obvious choices, and passwords built from the account's own e-mail."""

_COMMON = {
    "password1234",
    "123456789012",
    "qwertyuiop12",
    "administrator",
    "letmein123456",
    "welcome12345",
    "iloveyou1234",
    "password1234!",
    "changeme1234",
    "111111111111",
    "abcdefghijkl",
    "0123456789ab",
}


def check_password_policy(password: str, email: str) -> str | None:
    """Returns a short reason code, or None when the password is acceptable."""
    low = password.lower()
    if low in _COMMON or len(set(password)) < 5:
        return "too_common"
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in low:
        return "contains_email"
    if low.isdigit():
        return "digits_only"
    return None
