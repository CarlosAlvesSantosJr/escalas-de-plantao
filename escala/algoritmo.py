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

from dataclasses import dataclass
from datetime import date, timedelta

# ResultadoEscala e afins moram em `avaliacao`; reexportados aqui por compatibilidade.
from .avaliacao import EstatisticaFuncionario, ResultadoEscala, Vaga, avaliar_escala  # noqa: F401
from .dominio import Cargo, Funcionario, Periodo, Plantao, Slot, Status, Turno, eh_fim_de_semana


@dataclass(frozen=True)
class Regras:
    max_dias_sem_plantao: int = 7


class GeradorEscala:
    def __init__(self, funcionarios: list[Funcionario], periodo: Periodo,
                 regras: Regras = Regras()):
        self.periodo = periodo
        self.regras = regras
        self._funcionarios = funcionarios
        self._por_cargo = {c: [f for f in funcionarios if f.cargo is c] for c in Cargo}
        self._stats = {f.id: EstatisticaFuncionario(f) for f in funcionarios}

    def gerar(self) -> ResultadoEscala:
        plantoes: list[Plantao] = []
        for dia, turno in self.periodo.slots():
            plantao = Plantao(dia, turno)
            for cargo in Cargo:
                escolhido = self._escolher(dia, turno, cargo)
                plantao.equipe[cargo] = escolhido
                if escolhido:
                    self._stats[escolhido.id].registrar(dia, turno)
            plantoes.append(plantao)
        # Estatísticas, vagas e motivos saem da mesma avaliação usada na revisão manual.
        return avaliar_escala(self._funcionarios, self.periodo, plantoes)

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


def gerar_escala(funcionarios: list[Funcionario], periodo: Periodo,
                 regras: Regras = Regras()) -> ResultadoEscala:
    return GeradorEscala(funcionarios, periodo, regras).gerar()
