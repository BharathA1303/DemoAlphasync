from dataclasses import dataclass

from app.kernel.ids.generator import default_id_generator


@dataclass(frozen=True)
class OrderId:
    value: str

    @classmethod
    def new(cls) -> "OrderId":
        return cls(value=default_id_generator.generate("ord"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserId:
    value: str

    @classmethod
    def new(cls) -> "UserId":
        return cls(value=default_id_generator.generate("usr"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SessionId:
    value: str

    @classmethod
    def new(cls) -> "SessionId":
        return cls(value=default_id_generator.generate("ses"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class InstrumentId:
    value: str

    @classmethod
    def new(cls) -> "InstrumentId":
        return cls(value=default_id_generator.generate("ins"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PortfolioId:
    value: str

    @classmethod
    def new(cls) -> "PortfolioId":
        return cls(value=default_id_generator.generate("port"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PositionId:
    value: str

    @classmethod
    def new(cls) -> "PositionId":
        return cls(value=default_id_generator.generate("pos"))

    def __str__(self) -> str:
        return self.value
