# arent/teachers.py — интерфейс сменных политик-учителей и их реестр.
#
# Учитель — это то, кто размечает состояние для BC-конвейера: принимает payload и
# возвращает Labeled (контекст, план, значение). Всё, что ниже sample_one, работает
# только с Labeled, поэтому новая политика подключается реализацией label(), а не
# правкой генерации/кодировки. Формат выборки, размерности сети и чекпойнт bc2 от
# выбора учителя не зависят.
#
# Реестр ленивый: get_teacher сам импортирует модули политик (arent.teacher и др.),
# поэтому сами политики импортируют только это поле (register/TeacherPolicy) и не
# зацикливаются. Имя по умолчанию — greedy: без конфигурации конвейер ведёт себя
# ровно как до появления реестра.
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from arent.teacher import Labeled

DEFAULT_TEACHER = "greedy"

# имя -> класс политики. Наполняется при импорте модулей политик (см. _autoload).
_REGISTRY: Dict[str, type] = {}


class TeacherPolicy(ABC):
    """Единый интерфейс учителя: label(payload) -> Labeled. Имя — ключ реестра."""

    name: str = ""

    @abstractmethod
    def label(self, payload: Dict[str, Any]) -> "Labeled":
        """Разметить одно состояние: лучший план политики и значение его линии."""
        raise NotImplementedError

    def plan(self, ctx) -> List[Any]:
        """Действия в уже собранном BattleContext (для closed-loop сравнения учителей).

        Незаменённый по умолчанию: не каждой политике нужен контекстный вход. Те, кому
        нужен (greedy, battlecast), переопределяют — сравнение работает ИМИ, а не самим
        scorer'ом политики, поэтому оценка общая.
        """
        raise NotImplementedError(f"{type(self).__name__} не поддерживает plan(ctx)")

    def pick(self, ctx) -> List[Any]:
        """Действия для ТЕКУЩЕГО актёра (ctx.src) — каноничная точка входа мульти-акторной
        разметки: любой живой боец команды, наведённый как src, размечается одной и той же
        политикой. По умолчанию опирается на plan(ctx)."""
        return self.plan(ctx)


def register(name: str) -> Callable[[type], type]:
    """Зарегистрировать класс политики под именем (декоратор над классом)."""

    def _wrap(cls: type) -> type:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _wrap


def _autoload() -> None:
    """Импортировать модули политик, чтобы их @register сработал. Держим локальные
    импорты: на уровне модуля это создало бы цикл (политики импортируют register)."""
    import arent.teacher  # noqa: F401  (greedy)
    try:
        import arent.battlecast  # noqa: F401  (появится на этапе 2)
    except ImportError:
        pass


def get_teacher(name: str = DEFAULT_TEACHER, **kwargs: Any) -> TeacherPolicy:
    """Собрать учителя по имени реестра; неизвестное имя — явная ошибка."""
    _autoload()
    if name not in _REGISTRY:
        raise ValueError(f"Неизвестный учитель {name!r}; доступны: {', '.join(list_teachers())}")
    return _REGISTRY[name](**kwargs)


def list_teachers() -> List[str]:
    """Имена зарегистрированных политик (по алфавиту — для CLI и отчётов)."""
    _autoload()
    return sorted(_REGISTRY)
