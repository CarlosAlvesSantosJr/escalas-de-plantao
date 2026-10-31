"""Geração automática da escala.

Estratégia: gulosa, slot a slot (DIA, depois NOITE, em ordem cronológica),
escolhendo para cada cargo o candidato elegível de menor "custo".

Regras rígidas (nunca violadas):
  * não escala quem está INDISPONIVEL ou de FERIAS no turno;
  * no máximo um plantão por dia;
  * quem trabalhou à NOITE não pega o DIA seguinte (descanso mínimo).

Critérios de desempate, em ordem de importância:
  1. não "roubar" alguém que é o único disponível num turno logo à frente
     (evita vagas que um guloso simples criaria);
  2. quem está há `max_dias_sem_plantao` dias sem plantão (e não está
     totalmente bloqueado nessa janela) tem prioridade;
  3. menor carga acumulada — o turno PREFERENCIAL vale como um plantão
     a menos, para que a preferência pese sem atropelar a equidade;
  4. equilíbrio de noites e de fins de semana;
  5. quem trabalhou há mais tempo; por fim, o nome (determinismo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .dominio import (Cargo, Funcionario, Periodo, Plantao, Slot, Status, Turno,
                      eh_fim_de_semana)


@dataclass(frozen=True)
class Regras:
    max_dias_sem_plantao: int = 7


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


@dataclass(frozen=True)
class Vaga:
    data: date
    turno: Turno
    cargo: Cargo
    motivo: str


@dataclass
class ResultadoEscala:
    periodo: Periodo
    plantoes: list[Plantao]
    estatisticas: list[EstatisticaFuncionario]
    vagas: list[Vaga] = field(default_factory=list)

    @property
    def cobertura(self) -> float:
        total = len(self.plantoes) * len(Cargo)
        return 1.0 if total == 0 else (total - len(self.vagas)) / total


class GeradorEscala:
    def __init__(self, funcionarios: list[Funcionario], periodo: Periodo,
                 regras: Regras = Regras()):
        self.periodo = periodo
        self.regras = regras
        self._por_cargo = {c: [f for f in funcionarios if f.cargo is c] for c in Cargo}
        self._stats = {f.id: EstatisticaFuncionario(f) for f in funcionarios}

    def gerar(self) -> ResultadoEscala:
        plantoes: list[Plantao] = []
        vagas: list[Vaga] = []
        for dia, turno in self.periodo.slots():
            plantao = Plantao(dia, turno)
            for cargo in Cargo:
                escolhido = self._escolher(dia, turno, cargo)
                plantao.equipe[cargo] = escolhido
                if escolhido:
                    self._registrar(escolhido, dia, turno)
                else:
                    vagas.append(Vaga(dia, turno, cargo, self._motivo_vaga(dia, turno, cargo)))
            plantoes.append(plantao)

        estatisticas = sorted(self._stats.values(),
                              key=lambda s: (s.funcionario.cargo.value, -s.total, s.funcionario.nome))
        return ResultadoEscala(self.periodo, plantoes, estatisticas, vagas)

    # --- seleção -------------------------------------------------------

    def _escolher(self, dia: date, turno: Turno, cargo: Cargo) -> Funcionario | None:
        elegiveis = [f for f in self._por_cargo[cargo]
                     if f.pode_trabalhar(dia, turno) and self._respeita_descanso(f, dia, turno)]
        if not elegiveis:
            return None
        return min(elegiveis, key=lambda f: self._custo(f, dia, turno))

    def _custo(self, f: Funcionario, dia: date, turno: Turno) -> tuple:
        st = self._stats[f.id]
        preferencial = f.status(dia, turno) is Status.PREFERENCIAL
        carga_no_turno = st.noites if turno is Turno.NOITE else st.dias
        return (
            self._criticidade(f, dia, turno),
            not self._obrigatorio(f, dia),
            st.total - int(preferencial),
            not preferencial,
            carga_no_turno,
            st.fins_de_semana if eh_fim_de_semana(dia) else 0,
            st.ultimo[0] if st.ultimo else date.min,
            f.nome,
        )

    def _respeita_descanso(self, f: Funcionario, dia: date, turno: Turno) -> bool:
        ultimo = self._stats[f.id].ultimo
        if ultimo is None:
            return True
        u_dia, u_turno = ultimo
        if u_dia == dia:
            return False
        saiu_da_noite = u_turno is Turno.NOITE and u_dia == dia - timedelta(days=1)
        return not (turno is Turno.DIA and saiu_da_noite)

    def _slots_bloqueados_por(self, dia: date, turno: Turno) -> list[Slot]:
        """Slots futuros que a pessoa perde ao ser escalada em (dia, turno)."""
        if turno is Turno.DIA:
            return [(dia, Turno.NOITE)]
        amanha = dia + timedelta(days=1)
        return [(amanha, Turno.DIA)] if amanha <= self.periodo.fim else []

    def _criticidade(self, f: Funcionario, dia: date, turno: Turno) -> int:
        """Quantos turnos futuros ficariam sem ninguém do cargo se `f` for escalado agora."""
        criticos = 0
        for d, t in self._slots_bloqueados_por(dia, turno):
            if not f.pode_trabalhar(d, t):
                continue
            tem_substituto = any(o is not f and o.pode_trabalhar(d, t)
                                 for o in self._por_cargo[f.cargo])
            criticos += not tem_substituto
        return criticos

    def _obrigatorio(self, f: Funcionario, dia: date) -> bool:
        limite = self.regras.max_dias_sem_plantao
        st = self._stats[f.id]
        referencia = st.ultimo[0] if st.ultimo else self.periodo.inicio
        if (dia - referencia).days < limite:
            return False
        # Quem passou a janela inteira bloqueado (férias, afastamento) está isento.
        return not all(f.bloqueado_o_dia_todo(dia - timedelta(days=i)) for i in range(limite))

    def _registrar(self, f: Funcionario, dia: date, turno: Turno) -> None:
        st = self._stats[f.id]
        st.total += 1
        st.noites += turno is Turno.NOITE
        st.fins_de_semana += eh_fim_de_semana(dia)
        st.preferenciais_atendidas += f.status(dia, turno) is Status.PREFERENCIAL
        st.ultimo = (dia, turno)

    def _motivo_vaga(self, dia: date, turno: Turno, cargo: Cargo) -> str:
        equipe = self._por_cargo[cargo]
        nome_cargo = cargo.value.lower()
        if not equipe:
            return f"Nenhum {nome_cargo} cadastrado"
        if not any(f.pode_trabalhar(dia, turno) for f in equipe):
            return f"Todos os {nome_cargo}s indisponíveis ou de férias"
        return "Disponíveis já cumprem descanso obrigatório"


def gerar_escala(funcionarios: list[Funcionario], periodo: Periodo,
                 regras: Regras = Regras()) -> ResultadoEscala:
    return GeradorEscala(funcionarios, periodo, regras).gerar()
