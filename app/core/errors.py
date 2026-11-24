"""서비스 계층 오류 — 웹 계층(pages/api)이 HTTP 상태로 바꾼다.
PermissionDenied → 403, NotFound → 404, InvalidInput → 400
"""


class PermissionDenied(Exception):
    pass


class NotFound(Exception):
    pass


class InvalidInput(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors
