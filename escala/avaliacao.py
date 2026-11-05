"""Avaliação de uma escala já montada, gerada pelo algoritmo ou editada à mão.

A partir dos plantões, recalcula estatísticas, vagas (com o motivo) e
conflitos com as regras. É o que sustenta a revisão manual: cada ajuste
passa por aqui e o coordenador vê na hora o que ele quebra.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .dominio import Cargo, Funcionario, Periodo, Plantao, Slot, Status, Turno, eh_fim_de_semana

# Quantidade de cores da paleta por profissional (static/css e relatorio_pdf).
TOTAL_CORES = 12


@dataclass
class EstatisticaFuncionario:
    funcionario: Funcionario
    total: int = 0
    noites: int = 0
    fins_de_semana: int = 0
    preferenciais_atendidas: int = 0
    ultimo: Slot | None = None

    @property
    def dias(self) -> int:
        return self.total - self.noites

    def registrar(self, dia: date, turno: Turno) -> None:
        self.total += 1
        self.noites += turno is Turno.NOITE
        self.fins_de_semana += eh_fim_de_semana(dia)
        self.preferenciais_atendidas += self.funcionario.status(dia, turno) is Status.PREFERENCIAL
        self.ultimo = (dia, turno)


@dataclass(frozen=True)
class Vaga:
    data: date
    turno: Turno
    cargo: Cargo
    motivo: str


@dataclass(frozen=True)
class Conflito:
    data: date
    turno: Turno
    cargo: Cargo
    funcionario: Funcionario
    motivo: str


@dataclass(frozen=True)
class Candidato:
    funcionario: Funcionario
    total: int
    preferencial: bool
    impedimentos: list[str]


@dataclass
class ResultadoEscala:
    periodo: Periodo
    plantoes: list[Plantao]
    estatisticas: list[EstatisticaFuncionario]
    vagas: list[Vaga] = field(default_factory=list)
    conflitos: list[Conflito] = field(default_factory=list)

    @property
    def cobertura(self) -> float:
        total = len(self.plantoes) * len(Cargo)
        return 1.0 if total == 0 else (total - len(self.vagas)) / total

    @property
    def cores(self) -> dict[str, int]:
        """Índice de cor de cada profissional, estável enquanto a equipe não muda."""
        ordem = sorted((s.funcionario for s in self.estatisticas), key=lambda f: (f.cargo.value, f.nome))
        return {f.id: i % TOTAL_CORES for i, f in enumerate(ordem)}


class Agenda:
    """Posições de cada profissional por dia, para checar as regras sem varrer a escala."""

    def __init__(self, plantoes: list[Plantao]):
        self._posicoes: dict[str, dict[date, list[tuple[Turno, Cargo]]]] = {}
        for p in plantoes:
            for cargo, f in p.equipe.items():
                if f:
                    self._posicoes.setdefault(f.id, {}).setdefault(p.data, []).append((p.turno, cargo))

    def posicoes(self, f: Funcionario, dia: date) -> list[tuple[Turno, Cargo]]:
        return self._posicoes.get(f.id, {}).get(dia, [])

    def turnos(self, f: Funcionario, dia: date) -> list[Turno]:
        return [t for t, _ in self.posicoes(f, dia)]

    def total(self, f: Funcionario) -> int:
        return sum(len(v) for v in self._posicoes.get(f.id, {}).values())


def _ordem(posicao: tuple[Turno, Cargo]) -> tuple[int, int]:
    turno, cargo = posicao
    return list(Turno).index(turno), list(Cargo).index(cargo)


def impedimentos(f: Funcionario, dia: date, turno: Turno, cargo: Cargo, agenda: Agenda,
                 equipe_ids: set[str], olhar_adiante: bool = True) -> list[str]:
    """Regras que `f` quebra (ou quebraria) ocupando a posição (dia, turno, cargo).

    Com `olhar_adiante=False`, usado ao avaliar uma escala pronta, cada
    conflito entre duas posições é apontado uma única vez, na que vem depois.
    """
    motivos = []
    if f.id not in equipe_ids:
        motivos.append("Não faz mais parte da equipe")
    elif f.cargo is not cargo:
        motivos.append(f"Cadastrado(a) em {f.cargo.rotulo}")

    status = f.status(dia, turno)
    if status is Status.FERIAS:
        motivos.append("De férias")
    elif status is Status.INDISPONIVEL:
        motivos.append("Indisponível neste turno")

    atual = (turno, cargo)
    if any(pos != atual and (olhar_adiante or _ordem(pos) < _ordem(atual))
           for pos in agenda.posicoes(f, dia)):
        motivos.append("Já tem outro plantão neste dia")
    if turno is Turno.DIA and Turno.NOITE in agenda.turnos(f, dia - timedelta(days=1)):
        motivos.append("Saindo do plantão da noite anterior")
    if olhar_adiante and turno is Turno.NOITE and Turno.DIA in agenda.turnos(f, dia + timedelta(days=1)):
        motivos.append("Tem plantão de dia logo após esta noite")
    return motivos


def _motivo_vaga(funcionarios: list[Funcionario], dia: date, turno: Turno, cargo: Cargo,
                 agenda: Agenda, equipe_ids: set[str]) -> str:
    equipe = [f for f in funcionarios if f.cargo is cargo]
    if not equipe:
        return f"Nenhum {cargo.profissional} cadastrado"
    disponiveis = [f for f in equipe if f.pode_trabalhar(dia, turno)]
    if not disponiveis:
        return f"Todos os {cargo.profissionais} indisponíveis ou de férias"
    livres = [f for f in disponiveis if not impedimentos(f, dia, turno, cargo, agenda, equipe_ids)]
    if not livres:
        return "Disponíveis já cumprem descanso obrigatório"
    n = len(livres)
    return f"{n} {cargo.profissionais if n > 1 else cargo.profissional} pode{'m' if n > 1 else ''} cobrir este turno"


def avaliar_escala(funcionarios: list[Funcionario], periodo: Periodo,
                   plantoes: list[Plantao]) -> ResultadoEscala:
    equipe_ids = {f.id for f in funcionarios}
    agenda = Agenda(plantoes)
    stats = {f.id: EstatisticaFuncionario(f) for f in funcionarios}
    vagas: list[Vaga] = []
    conflitos: list[Conflito] = []
    for p in plantoes:
        for cargo in Cargo:
            f = p.equipe.get(cargo)
            if f is None:
                vagas.append(Vaga(p.data, p.turno, cargo,
                                  _motivo_vaga(funcionarios, p.data, p.turno, cargo, agenda, equipe_ids)))
                continue
            stats.setdefault(f.id, EstatisticaFuncionario(f)).registrar(p.data, p.turno)
            conflitos += [Conflito(p.data, p.turno, cargo, f, m)
                          for m in impedimentos(f, p.data, p.turno, cargo, agenda, equipe_ids,
                                                olhar_adiante=False)]

    estatisticas = sorted(stats.values(),
                          key=lambda s: (s.funcionario.cargo.value, -s.total, s.funcionario.nome))
    return ResultadoEscala(periodo, plantoes, estatisticas, vagas, conflitos)


def candidatos(funcionarios: list[Funcionario], plantoes: list[Plantao],
               dia: date, turno: Turno, cargo: Cargo) -> list[Candidato]:
    """Quem pode ocupar uma posição, com o que cada um quebraria. Livres e preferenciais primeiro."""
    agenda = Agenda(plantoes)
    equipe_ids = {f.id for f in funcionarios}
    lista = [Candidato(f, agenda.total(f), f.status(dia, turno) is Status.PREFERENCIAL,
                       impedimentos(f, dia, turno, cargo, agenda, equipe_ids))
             for f in funcionarios if f.cargo is cargo]
    return sorted(lista, key=lambda c: (bool(c.impedimentos), not c.preferencial, c.total, c.funcionario.nome))
