"""이름 → 구현 등록부 (개방-폐쇄 원칙).

새 구현(데이터 백엔드, 계산식, 변경 처리기, 업로드 형식 …)은 기존 코드를 고치지 않고
등록만 해서 붙인다.

    FORMULAS = Registry[RequiredFteFormula]("필요 FTE 계산식")

    @FORMULAS.register("workload")
    class WorkloadFormula: ...

    FORMULAS.get("workload")
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, what: str):
        self.what = what
        self._items: dict[str, T] = {}

    def register(self, name: str, item: T | None = None):
        """register("x", obj) 또는 @register("x") 데코레이터. 같은 이름을 두 번 등록하면 오류."""
        def add(obj: T) -> T:
            if name in self._items and self._items[name] is not obj:
                raise ValueError(f"{self.what} '{name}' 이(가) 이미 등록되어 있습니다.")
            self._items[name] = obj
            return obj
        return add(item) if item is not None else add

    def get(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"등록되지 않은 {self.what}: {name!r} (가능: {', '.join(self._items) or '없음'})") from None

    def create(self, name: str, *args, **kwargs):
        """등록된 것이 클래스·팩토리면 호출해서 만든다."""
        factory: Callable = self.get(name)  # type: ignore[assignment]
        return factory(*args, **kwargs)

    def names(self) -> list[str]:
        return list(self._items)

    def items(self) -> Iterator[tuple[str, T]]:
        return iter(list(self._items.items()))

    def __contains__(self, name: object) -> bool:
        return name in self._items
