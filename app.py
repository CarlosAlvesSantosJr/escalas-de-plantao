"""Versão desktop (Tkinter). Usa o mesmo núcleo `escala` do frontend web."""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkcalendar import DateEntry

from escala.algoritmo import ResultadoEscala, gerar_escala
from escala.dominio import Cargo, Funcionario, Periodo, Status, Turno, normalizar_nome
from escala.relatorio_pdf import gerar_pdf
from escala.repositorio import EstadoApp, RepositorioJSON

ARQUIVO_DADOS = Path(__file__).resolve().parent / "dados_escala.json"

CORES_STATUS = {
    Status.DISPONIVEL: "#e1f5fe",
    Status.INDISPONIVEL: "#ffcdd2",
    Status.PREFERENCIAL: "#c8e6c9",
    Status.FERIAS: "#ffe0b2",
}
CICLO_STATUS = list(Status)
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


class EscalaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema de Escala Inteligente - Emergência Móvel")
        self.root.geometry("1100x850")

        self.repo = RepositorioJSON(ARQUIVO_DADOS)
        self.estado = self._carregar()
        self.resultado: ResultadoEscala | None = None

        self.criar_interface()
        self.refresh_tree_funcionarios()
        if self.estado.periodo:
            self.ent_inicio.set_date(self.estado.periodo.inicio)
            self.ent_fim.set_date(self.estado.periodo.fim)

    @property
    def funcionarios(self) -> list[Funcionario]:
        return self.estado.funcionarios

    # --- persistência ---

    def _carregar(self):
        try:
            return self.repo.carregar()
        except Exception as e:
            messagebox.showerror("Erro ao Carregar", f"Erro ao ler arquivo de dados: {e}")
            return EstadoApp()

    def salvar_dados(self):
        try:
            self.repo.salvar(self.estado)
        except OSError as e:
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar os dados: {e}")

    # --- interface ---

    def criar_interface(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        self.frame_config = ttk.Frame(self.notebook)
        self.frame_funcionarios = ttk.Frame(self.notebook)
        self.frame_disponibilidade = ttk.Frame(self.notebook)
        self.frame_escala = ttk.Frame(self.notebook)

        self.notebook.add(self.frame_config, text="1. Período")
        self.notebook.add(self.frame_funcionarios, text="2. Cadastro")
        self.notebook.add(self.frame_disponibilidade, text="3. Indisponibilidade")
        self.notebook.add(self.frame_escala, text="4. Gerar Escala")

        self.setup_aba_config()
        self.setup_aba_funcionarios()
        self.setup_aba_disponibilidade()
        self.setup_aba_escala()

    def setup_aba_config(self):
        frame = ttk.LabelFrame(self.frame_config, text="Definição do Ciclo", padding=20)
        frame.pack(pady=50)
        ttk.Label(frame, text="Início:").grid(row=0, column=0)
        self.ent_inicio = DateEntry(frame, width=12, locale='pt_BR', date_pattern='dd/mm/yyyy')
        self.ent_inicio.grid(row=0, column=1, padx=10, pady=5)
        ttk.Label(frame, text="Fim:").grid(row=1, column=0)
        self.ent_fim = DateEntry(frame, width=12, locale='pt_BR', date_pattern='dd/mm/yyyy')
        self.ent_fim.grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(frame, text="Confirmar Período", command=self.confirmar_periodo).grid(row=2, column=0, columnspan=2, pady=20)

    def confirmar_periodo(self):
        try:
            self.estado.periodo = Periodo(self.ent_inicio.get_date(), self.ent_fim.get_date())
        except ValueError as e:
            messagebox.showerror("Erro", str(e))
            return
        self.salvar_dados()
        messagebox.showinfo("Sucesso", "Período definido!")
        self.refresh_calendar()
        self.notebook.select(1)

    def setup_aba_funcionarios(self):
        frame_cad = ttk.LabelFrame(self.frame_funcionarios, text="Cadastro", padding=10)
        frame_cad.pack(fill='x', padx=10, pady=10)

        self.ent_nome = ttk.Entry(frame_cad, width=30)
        self.ent_nome.grid(row=0, column=0, padx=5)
        self.combo_tipo = ttk.Combobox(frame_cad, values=[c.value for c in Cargo], state="readonly")
        self.combo_tipo.set(Cargo.ENFERMEIRO.value)
        self.combo_tipo.grid(row=0, column=1, padx=5)

        ttk.Button(frame_cad, text="Adicionar", command=self.add_funcionario).grid(row=0, column=2, padx=2)
        ttk.Button(frame_cad, text="Alterar", command=self.update_funcionario).grid(row=0, column=3, padx=2)
        ttk.Button(frame_cad, text="Deletar", command=self.delete_funcionario).grid(row=0, column=4, padx=2)

        self.tree_func = ttk.Treeview(self.frame_funcionarios, columns=('Nome', 'Cargo'), show='headings', height=10)
        self.tree_func.heading('Nome', text='Nome')
        self.tree_func.heading('Cargo', text='Cargo')
        self.tree_func.pack(fill='both', expand=True, padx=10)
        self.tree_func.bind('<<TreeviewSelect>>', self.carregar_dados_funcionario_form)

    def _ler_nome(self, ignorar_id=None):
        try:
            nome = normalizar_nome(self.ent_nome.get())
        except ValueError as e:
            messagebox.showwarning("Aviso", str(e))
            return None
        if self.estado.nome_em_uso(nome, ignorar_id):
            messagebox.showwarning("Aviso", f"Já existe um profissional chamado {nome}.")
            return None
        return nome

    def _selecionado(self) -> Funcionario | None:
        sel = self.tree_func.selection()
        return self.estado.funcionario(sel[0]) if sel else None

    def add_funcionario(self):
        nome = self._ler_nome()
        if nome:
            self.funcionarios.append(Funcionario(nome, Cargo(self.combo_tipo.get())))
            self._apos_alterar_equipe()

    def update_funcionario(self):
        f = self._selecionado()
        if not f:
            return
        nome = self._ler_nome(ignorar_id=f.id)
        if nome:
            f.nome = nome
            f.cargo = Cargo(self.combo_tipo.get())
            self._apos_alterar_equipe()

    def delete_funcionario(self):
        f = self._selecionado()
        if f and messagebox.askyesno("Confirmar", f"Deletar {f.nome}?"):
            self.funcionarios.remove(f)
            self._apos_alterar_equipe()

    def _apos_alterar_equipe(self):
        self.refresh_tree_funcionarios()
        self.salvar_dados()
        self.limpar_campos_func()

    def refresh_tree_funcionarios(self):
        self.tree_func.delete(*self.tree_func.get_children())
        for f in self.funcionarios:
            # O id do funcionário vira o iid da linha: seleção não depende mais do índice.
            self.tree_func.insert('', 'end', iid=f.id, values=(f.nome, f.cargo.value))
        self.update_combo_dispo()

    def carregar_dados_funcionario_form(self, event):
        f = self._selecionado()
        if f:
            self.ent_nome.delete(0, tk.END)
            self.ent_nome.insert(0, f.nome)
            self.combo_tipo.set(f.cargo.value)

    def limpar_campos_func(self):
        self.ent_nome.delete(0, tk.END)
        self.tree_func.selection_remove(self.tree_func.selection())

    def setup_aba_disponibilidade(self):
        frame_topo = ttk.Frame(self.frame_disponibilidade, padding=10)
        frame_topo.pack(fill='x')

        ttk.Label(frame_topo, text="Selecione o Funcionário:").pack(side=tk.LEFT, padx=5)
        self.combo_disp_func = ttk.Combobox(frame_topo, width=30, state="readonly")
        self.combo_disp_func.pack(side=tk.LEFT, padx=10)
        self.combo_disp_func.bind("<<ComboboxSelected>>", self.refresh_calendar)

        self.canvas_cal = tk.Canvas(self.frame_disponibilidade)
        self.scroll_cal = ttk.Scrollbar(self.frame_disponibilidade, orient="vertical", command=self.canvas_cal.yview)
        self.frame_btns = ttk.Frame(self.canvas_cal)

        self.canvas_cal.create_window((0, 0), window=self.frame_btns, anchor="nw")
        self.canvas_cal.configure(yscrollcommand=self.scroll_cal.set)

        self.canvas_cal.pack(side="left", fill="both", expand=True)
        self.scroll_cal.pack(side="right", fill="y")
        self.frame_btns.bind("<Configure>", lambda e: self.canvas_cal.configure(scrollregion=self.canvas_cal.bbox("all")))

    def update_combo_dispo(self):
        self.combo_disp_func['values'] = [f.nome for f in self.funcionarios]

    def refresh_calendar(self, event=None):
        for w in self.frame_btns.winfo_children():
            w.destroy()
        f = next((x for x in self.funcionarios if x.nome == self.combo_disp_func.get()), None)
        periodo = self.estado.periodo

        if not f or not periodo:
            ttk.Label(self.frame_btns, text="Defina o período (Aba 1) e selecione um funcionário.", padding=20).pack()
            return

        for i, dia in enumerate(DIAS_SEMANA):
            tk.Label(self.frame_btns, text=dia, font=('Arial', 9, 'bold'), width=12, fg="gray").grid(row=0, column=i, padx=5, pady=10)

        linha = 1
        for dia in periodo.dias():
            coluna = dia.weekday()
            dia_frame = tk.Frame(self.frame_btns, bd=1, relief="solid", highlightbackground="#ddd")
            dia_frame.grid(row=linha, column=coluna, sticky="nsew", padx=2, pady=2)

            cor_data = "blue" if coluna >= 5 else "black"
            tk.Label(dia_frame, text=dia.strftime('%d/%m'), font=('Arial', 8, 'bold'), fg=cor_data).pack(pady=2)

            for turno in Turno:
                tk.Button(dia_frame, text=turno.value, bg=CORES_STATUS[f.status(dia, turno)], font=('Arial', 7), width=10,
                          command=lambda d=dia, t=turno: self.toggle_disp(f, d, t)).pack(fill='x', padx=2, pady=1)

            if coluna == 6:
                linha += 1

    def toggle_disp(self, f: Funcionario, dia, turno):
        atual = f.status(dia, turno)
        f.definir_status(dia, turno, CICLO_STATUS[(CICLO_STATUS.index(atual) + 1) % len(CICLO_STATUS)])
        self.salvar_dados()
        self.refresh_calendar()

    def setup_aba_escala(self):
        frame_top = ttk.Frame(self.frame_escala, padding=10)
        frame_top.pack(fill='x')
        ttk.Button(frame_top, text="GERAR ESCALA", command=self.processar_escala).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_top, text="EXPORTAR PDF", command=self.exportar_pdf).pack(side=tk.LEFT)
        self.lbl_resumo = ttk.Label(frame_top, text="")
        self.lbl_resumo.pack(side=tk.LEFT, padx=20)

        self.tree_escala = ttk.Treeview(self.frame_escala, columns=('Data', 'Turno', 'Enf', 'Mot'), show='headings')
        for col in ('Data', 'Turno', 'Enf', 'Mot'):
            self.tree_escala.heading(col, text=col)
            self.tree_escala.column(col, anchor="center")
        self.tree_escala.tag_configure("vago", foreground="#c62828")
        self.tree_escala.pack(fill='both', expand=True, padx=10, pady=10)

    def processar_escala(self):
        if not self.funcionarios or not self.estado.periodo:
            messagebox.showwarning("Aviso", "Cadastre funcionários e defina o período.")
            return
        self.resultado = gerar_escala(self.funcionarios, self.estado.periodo)
        self.render_escala()

    def render_escala(self):
        self.tree_escala.delete(*self.tree_escala.get_children())
        for p in self.resultado.plantoes:
            e_nome = p.enfermeiro.nome if p.enfermeiro else "VAGO"
            m_nome = p.motorista.nome if p.motorista else "VAGO"
            tags = () if p.completo else ("vago",)
            self.tree_escala.insert('', 'end', values=(p.data.strftime('%d/%m/%y (%a)'), p.turno.value, e_nome, m_nome), tags=tags)
        self.lbl_resumo.config(text=f"Cobertura: {self.resultado.cobertura:.0%}  |  Vagas: {len(self.resultado.vagas)}")

    def exportar_pdf(self):
        if not self.resultado:
            messagebox.showwarning("Aviso", "Gere a escala antes de exportar.")
            return
        destino = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="escala_emergencia.pdf",
                                               filetypes=[("PDF", "*.pdf")])
        if not destino:
            return
        Path(destino).write_bytes(gerar_pdf(self.resultado))
        messagebox.showinfo("Sucesso", "PDF gerado com sucesso!")


if __name__ == "__main__":
    root = tk.Tk()
    app = EscalaApp(root)
    root.mainloop()
