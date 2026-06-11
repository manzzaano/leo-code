"""Data models para mini repo fixture."""

from dataclasses import dataclass


@dataclass
class User:
    """User model."""
    id: int
    name: str
    email: str


@dataclass
class Product:
    """Product model."""
    id: int
    title: str
    price: float

    def discount(self, percent: float) -> float:
        """Calcula precio con descuento."""
        return self.price * (1 - percent / 100)
