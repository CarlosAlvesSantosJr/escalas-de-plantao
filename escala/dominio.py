"""Modelos de domínio da escala de plantão (sem dependência de UI ou I/O)."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Iterator


class Cargo(str, Enum):
    ENFERMEIRO = "ENFERMEIRO"
    MOTORISTA = "MOTORISTA"


class Turno(str, Enum):
    DIA = "DIA"
    NOITE = "NOITE"


class Status(str, Enum):
    DISPONIVEL = "DISPONIVEL"
    INDISPONIVEL = "INDISPONIVEL"
    PREFERENCIAL = "PREFERENCIAL"
    FERIAS = "FERIAS"

    @property
    def bloqueia(self) -> bool:
        """Status que impedem o funcionário de ser escalado."""
        return self in (Status.INDISPONIVEL, Status.FERIAS)


Slot = tuple[date, Turno]

_NOME_VALIDO = re.compile(r"^[A-ZÀ-Ÿ]+(?: [A-ZÀ-Ÿ]+)*$")


def normalizar_nome(nome: str) -> str:
    """Remove espaços extras e coloca em maiúsculas. Lança ValueError se inválido."""
    limpo = " ".join(nome.split()).upper()
    if not limpo:
        raise ValueError("O nome não pode estar vazio.")
    if not _NOME_VALIDO.match(limpo):
        raise ValueError("Use apenas letras e espaços no nome.")
    return limpo


def _novo_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Funcionario:
    nome: str
    cargo: Cargo
    disponibilidade: dict[Slot, Status] = field(default_factory=dict)
    id: str = field(default_factory=_novo_id)

    def status(self, dia: date, turno: Turno) -> Status:
        return self.disponibilidade.get((dia, turno), Status.DISPONIVEL)

    def definir_status(self, dia: date, turno: Turno, status: Status) -> None:
        # DISPONIVEL é o padrão: não armazenamos para manter o arquivo enxuto.
        if status is Status.DISPONIVEL:
            self.disponibilidade.pop((dia, turno), None)
        else:
            self.disponibilidade[(dia, turno)] = status

    def pode_trabalhar(self, dia: date, turno: Turno) -> bool:
        return not self.status(dia, turno).bloqueia

    def bloqueado_o_dia_todo(self, dia: date) -> bool:
        return all(self.status(dia, t).bloqueia for t in Turno)


@dataclass(frozen=True)
class Periodo:
    inicio: date
    fim: date

    def __post_init__(self) -> None:
        if self.inicio > self.fim:
            raise ValueError("A data de início deve ser anterior ou igual à data de fim.")

    @property
    def total_dias(self) -> int:
        return (self.fim - self.inicio).days + 1

    def dias(self) -> Iterator[date]:
        for i in range(self.total_dias):
            yield self.inicio + timedelta(days=i)

    def slots(self) -> Iterator[Slot]:
        for dia in self.dias():
            for turno in Turno:
                yield dia, turno


@dataclass
class Plantao:
    data: date
    turno: Turno
    equipe: dict[Cargo, Funcionario | None] = field(default_factory=dict)

    @property
    def enfermeiro(self) -> Funcionario | None:
        return self.equipe.get(Cargo.ENFERMEIRO)

    @property
    def motorista(self) -> Funcionario | None:
        return self.equipe.get(Cargo.MOTORISTA)

    @property
    def completo(self) -> bool:
        return all(self.equipe.get(c) is not None for c in Cargo)


def eh_fim_de_semana(dia: date) -> bool:
    return dia.weekday() >= 5
