from datetime import date, timedelta

import pytest

from escala.algoritmo import Regras, gerar_escala
from escala.dominio import Cargo, Funcionario, Periodo, Status, Turno, normalizar_nome

INICIO = date(2026, 11, 2)  # segunda-feira


def equipe(n_enf=3, n_mot=3):
    return ([Funcionario(f"ENF {chr(65 + i)}", Cargo.ENFERMEIRO) for i in range(n_enf)]
            + [Funcionario(f"MOT {chr(65 + i)}", Cargo.MOTORISTA) for i in range(n_mot)])


def periodo(dias):
    return Periodo(INICIO, INICIO + timedelta(days=dias - 1))


def plantoes_de(resultado, f):
    return [(p.data, p.turno) for p in resultado.plantoes if f in p.equipe.values()]


def test_cobertura_total_com_equipe_suficiente():
    r = gerar_escala(equipe(), periodo(14))
    assert r.vagas == []
    assert r.cobertura == 1.0
    assert len(r.plantoes) == 28


def test_nunca_escala_indisponivel_ou_ferias():
    funcs = equipe()
    a = funcs[0]
    for d in periodo(7).dias():
        a.definir_status(d, Turno.DIA, Status.INDISPONIVEL)
        a.definir_status(d, Turno.NOITE, Status.FERIAS)
    r = gerar_escala(funcs, periodo(7))
    assert plantoes_de(r, a) == []


def test_descanso_um_plantao_por_dia_e_noite_nao_emenda_dia():
    funcs = equipe(2, 2)
    r = gerar_escala(funcs, periodo(30))
    for f in funcs:
        slots = plantoes_de(r, f)
        datas = [d for d, _ in slots]
        assert len(datas) == len(set(datas)), f"{f.nome} com dois plantões no mesmo dia"
        for d, t in slots:
            if t is Turno.NOITE:
                assert (d + timedelta(days=1), Turno.DIA) not in slots


def test_distribuicao_equilibrada():
    funcs = equipe(4, 4)
    r = gerar_escala(funcs, periodo(28))
    for cargo in Cargo:
        totais = [s.total for s in r.estatisticas if s.funcionario.cargo is cargo]
        assert max(totais) - min(totais) <= 1
        noites = [s.noites for s in r.estatisticas if s.funcionario.cargo is cargo]
        assert max(noites) - min(noites) <= 1


def test_preferencial_e_atendido_quando_ha_empate():
    funcs = equipe(2, 2)
    b = funcs[1]
    b.definir_status(INICIO, Turno.DIA, Status.PREFERENCIAL)
    r = gerar_escala(funcs, periodo(1))
    assert r.plantoes[0].enfermeiro is b


def test_preferencial_nao_monopoliza_os_plantoes():
    """Antes, quem marcava tudo como PREFERENCIAL ganhava quase todos os plantões."""
    funcs = equipe(3, 3)
    a = funcs[0]
    for d, t in periodo(21).slots():
        a.definir_status(d, t, Status.PREFERENCIAL)
    r = gerar_escala(funcs, periodo(21))
    totais = {s.funcionario.nome: s.total for s in r.estatisticas
              if s.funcionario.cargo is Cargo.ENFERMEIRO}
    assert totais[a.nome] - min(totais.values()) <= 2


def test_olha_adiante_para_nao_criar_vaga():
    """A é o único disponível no DIA de amanhã; o guloso puro o poria na NOITE de hoje."""
    a, b = Funcionario("A", Cargo.ENFERMEIRO), Funcionario("B", Cargo.ENFERMEIRO)
    amanha = INICIO + timedelta(days=1)
    # Hoje: B só pode de dia, A só de noite.
    b.definir_status(INICIO, Turno.NOITE, Status.INDISPONIVEL)
    a.definir_status(INICIO, Turno.DIA, Status.INDISPONIVEL)
    # Amanhã de dia só A pode; à noite só B.
    b.definir_status(amanha, Turno.DIA, Status.INDISPONIVEL)
    a.definir_status(amanha, Turno.NOITE, Status.INDISPONIVEL)
    # Hoje à noite também há C, que não pode amanhã.
    c = Funcionario("C", Cargo.ENFERMEIRO)
    c.definir_status(amanha, Turno.DIA, Status.INDISPONIVEL)
    c.definir_status(amanha, Turno.NOITE, Status.INDISPONIVEL)
    c.definir_status(INICIO, Turno.DIA, Status.INDISPONIVEL)

    r = gerar_escala([a, b, c], periodo(2))
    enf = {(p.data, p.turno): p.enfermeiro for p in r.plantoes}
    assert enf[(INICIO, Turno.NOITE)] is c
    assert enf[(amanha, Turno.DIA)] is a
    assert not [v for v in r.vagas if v.cargo is Cargo.ENFERMEIRO]


def test_ninguem_fica_mais_de_sete_dias_sem_plantao():
    funcs = equipe(6, 6)
    r = gerar_escala(funcs, periodo(28), Regras(max_dias_sem_plantao=7))
    for f in funcs:
        datas = sorted(d for d, _ in plantoes_de(r, f))
        assert datas, f"{f.nome} sem nenhum plantão"
        for anterior, proximo in zip(datas, datas[1:]):
            assert (proximo - anterior).days <= 8


def test_vaga_informa_motivo():
    funcs = [Funcionario("A", Cargo.ENFERMEIRO)]
    r = gerar_escala(funcs, periodo(1))
    motivos = {(v.turno, v.cargo): v.motivo for v in r.vagas}
    assert "Nenhum motorista" in motivos[(Turno.DIA, Cargo.MOTORISTA)]
    assert "descanso" in motivos[(Turno.NOITE, Cargo.ENFERMEIRO)]


def test_resultado_deterministico():
    a = gerar_escala(equipe(), periodo(10))
    b = gerar_escala(equipe(), periodo(10))
    nomes = lambda r: [(p.enfermeiro.nome, p.motorista.nome) for p in r.plantoes]
    assert nomes(a) == nomes(b)


@pytest.mark.parametrize("entrada,esperado", [
    ("  maria   da silva ", "MARIA DA SILVA"),
    ("joão", "JOÃO"),
])
def test_normalizar_nome(entrada, esperado):
    assert normalizar_nome(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "   ", "ANA2", "ANA-MARIA"])
def test_normalizar_nome_invalido(entrada):
    with pytest.raises(ValueError):
        normalizar_nome(entrada)


def test_periodo_invalido():
    with pytest.raises(ValueError):
        Periodo(date(2026, 1, 2), date(2026, 1, 1))
