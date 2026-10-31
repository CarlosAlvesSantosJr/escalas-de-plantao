"""Exportação da escala para PDF (fpdf 1.7)."""
from __future__ import annotations

from fpdf import FPDF

from .algoritmo import ResultadoEscala
from .dominio import eh_fim_de_semana

DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

VERMELHO = (196, 30, 36)
LARANJA = (232, 100, 27)
CINZA_CLARO = (245, 246, 248)
AZUL_FDS = (232, 240, 254)
TEXTO = (33, 37, 41)


def gerar_pdf(resultado: ResultadoEscala) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    periodo = resultado.periodo
    pdf.set_fill_color(*VERMELHO)
    pdf.rect(0, 0, 210, 26, "F")
    pdf.set_fill_color(*LARANJA)
    pdf.rect(0, 26, 210, 1.5, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(10, 6)
    pdf.cell(0, 8, "SAMU 192 - ESCALA DE PLANTÃO")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(10, 14)
    pdf.cell(0, 6, f"Período: {periodo.inicio:%d/%m/%Y} a {periodo.fim:%d/%m/%Y}   |   "
                   f"Cobertura: {resultado.cobertura:.0%}")
    pdf.set_y(34)

    colunas = [("Data", 34), ("Turno", 22), ("Enfermeiro(a)", 67), ("Motorista", 67)]

    def cabecalho():
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(*TEXTO)
        pdf.set_text_color(255, 255, 255)
        for titulo, largura in colunas:
            pdf.cell(largura, 8, titulo, border=0, fill=True)
        pdf.ln()

    cabecalho()
    pdf.set_font("Helvetica", "", 10)
    for i, p in enumerate(resultado.plantoes):
        if pdf.get_y() > 270:
            pdf.add_page()
            cabecalho()
            pdf.set_font("Helvetica", "", 10)
        fundo = AZUL_FDS if eh_fim_de_semana(p.data) else (CINZA_CLARO if i % 2 else (255, 255, 255))
        pdf.set_fill_color(*fundo)
        pdf.set_text_color(*TEXTO)
        pdf.cell(34, 7, f"{p.data:%d/%m} {DIAS_SEMANA[p.data.weekday()]}", fill=True)
        pdf.cell(22, 7, p.turno.value, fill=True)
        for membro in (p.enfermeiro, p.motorista):
            if membro:
                pdf.set_text_color(*TEXTO)
                pdf.cell(67, 7, membro.nome, fill=True)
            else:
                pdf.set_text_color(*VERMELHO)
                pdf.cell(67, 7, "VAGO", fill=True)
        pdf.ln()

    pdf.ln(6)
    pdf.set_text_color(*TEXTO)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Resumo por profissional", ln=True)
    pdf.set_font("Helvetica", "", 9)
    for st in resultado.estatisticas:
        pdf.cell(0, 5.5, f"{st.funcionario.nome} ({st.funcionario.cargo.value.title()}): "
                         f"{st.total} plantões  -  {st.dias} dia / {st.noites} noite  -  "
                         f"{st.fins_de_semana} fim de semana", ln=True)

    return pdf.output(dest="S").encode("latin-1")
