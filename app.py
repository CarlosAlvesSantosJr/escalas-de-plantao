import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime, timedelta
from fpdf import FPDF
from tkcalendar import DateEntry

# =========================
# MODELOS
# =========================

class Funcionario:
    def __init__(self, nome, tipo):
        self.nome = nome
        self.tipo = tipo  # ENFERMEIRO ou MOTORISTA
        self.disponibilidade = {}  # {(data, turno): "DISPONIVEL", "INDISPONIVEL", "PREFERENCIAL"}
        self.total_plantoes = 0
        self.ultimo_plantao = None

    def resetar_contadores(self):
        self.total_plantoes = 0
        self.ultimo_plantao = None

class Plantao:
    def __init__(self, data, turno, horario):
        self.data = data
        self.turno = turno
        self.enfermeiro = None
        self.motorista = None

# =========================
# APP PRINCIPAL
# =========================

class EscalaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema de Escala Inteligente - Emergência Móvel")
        self.root.geometry("1000x850")
        
        self.funcionarios = []
        self.escala = []
        self.periodo_inicio = None
        self.periodo_fim = None
        
        self.criar_interface()

    def criar_interface(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Abas
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

    # --- ABA 1: CONFIGURAÇÃO ---
    def setup_aba_config(self):
        frame = ttk.LabelFrame(self.frame_config, text="Definição do Ciclo", padding=20)
        frame.pack(pady=50)
        
        ttk.Label(frame, text="Início da Escala:").grid(row=0, column=0, pady=5)
        self.ent_inicio = DateEntry(frame, width=12, locale='pt_BR', date_pattern='dd/mm/yyyy')
        self.ent_inicio.grid(row=0, column=1, padx=10)
        
        ttk.Label(frame, text="Fim da Escala:").grid(row=1, column=0, pady=5)
        self.ent_fim = DateEntry(frame, width=12, locale='pt_BR', date_pattern='dd/mm/yyyy')
        self.ent_fim.grid(row=1, column=1, padx=10)
        
        ttk.Button(frame, text="Confirmar e Prosseguir", command=self.confirmar_periodo).grid(row=2, column=0, columnspan=2, pady=20)

    def confirmar_periodo(self):
        self.periodo_inicio = self.ent_inicio.get_date()
        self.periodo_fim = self.ent_fim.get_date()
        if self.periodo_inicio > self.periodo_fim:
            messagebox.showerror("Erro", "A data de início deve ser anterior ao fim.")
            return
        messagebox.showinfo("Sucesso", f"Período definido: {self.periodo_inicio.strftime('%d/%m/%Y')} até {self.periodo_fim.strftime('%d/%m/%Y')}")
        self.notebook.select(1)

    # --- ABA 2: FUNCIONÁRIOS (CORRIGIDA) ---
    def setup_aba_funcionarios(self):
        frame_cad = ttk.LabelFrame(self.frame_funcionarios, text="Gerenciar Funcionários", padding=10)
        frame_cad.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(frame_cad, text="Nome:").grid(row=0, column=0)
        self.ent_nome = ttk.Entry(frame_cad, width=30)
        self.ent_nome.grid(row=0, column=1, padx=5)
        
        self.combo_tipo = ttk.Combobox(frame_cad, values=["ENFERMEIRO", "MOTORISTA"], state="readonly")
        self.combo_tipo.set("ENFERMEIRO")
        self.combo_tipo.grid(row=0, column=2, padx=5)
        
        btn_frame = ttk.Frame(frame_cad)
        btn_frame.grid(row=0, column=3, padx=5)

        ttk.Button(btn_frame, text="Adicionar", command=self.add_funcionario).pack(side='left', padx=2)
        ttk.Button(btn_frame, text="Alterar", command=self.update_funcionario).pack(side='left', padx=2)
        ttk.Button(btn_frame, text="Deletar", command=self.delete_funcionario).pack(side='left', padx=2)
        
        self.tree_func = ttk.Treeview(self.frame_funcionarios, columns=('ID', 'Nome', 'Cargo'), show='headings', height=10)
        self.tree_func.heading('ID', text='ID')
        self.tree_func.heading('Nome', text='Nome')
        self.tree_func.heading('Cargo', text='Cargo')
        self.tree_func.column('ID', width=50, anchor='center')
        self.tree_func.pack(fill='both', expand=True, padx=10, pady=10)

        self.tree_func.bind('<<TreeviewSelect>>', self.carregar_dados_funcionario)
        
        ttk.Button(self.frame_funcionarios, text="Ir para Indisponibilidades", command=lambda: self.notebook.select(2)).pack(pady=5)

    def add_funcionario(self):
        nome = self.ent_nome.get().strip()
        if not nome: 
            messagebox.showwarning("Aviso", "O nome do funcionário não pode estar vazio.")
            return
        f = Funcionario(nome, self.combo_tipo.get())
        self.funcionarios.append(f)
        self.refresh_tree_funcionarios()
        self.limpar_campos_func()

    def carregar_dados_funcionario(self, event):
        item_sel = self.tree_func.selection()
        if item_sel:
            valores = self.tree_func.item(item_sel[0], 'values')
            self.ent_nome.delete(0, tk.END)
            self.ent_nome.insert(0, valores[1])
            self.combo_tipo.set(valores[2])

    def update_funcionario(self):
        item_sel = self.tree_func.selection()
        if not item_sel:
            messagebox.showwarning("Aviso", "Selecione um funcionário na lista abaixo antes de clicar em Alterar.")
            return
        
        # Pega o índice real baseado na posição na Treeview
        idx = self.tree_func.index(item_sel[0])
        nome_novo = self.ent_nome.get().strip()
        
        if nome_novo:
            # ATUALIZAÇÃO REAL DO OBJETO NA LISTA
            self.funcionarios[idx].nome = nome_novo
            self.funcionarios[idx].tipo = self.combo_tipo.get()
            
            self.refresh_tree_funcionarios()
            self.limpar_campos_func()
            messagebox.showinfo("Sucesso", "Cadastro atualizado com sucesso!")
        else:
            messagebox.showwarning("Aviso", "O nome não pode ficar vazio.")

    def delete_funcionario(self):
        item_sel = self.tree_func.selection()
        if not item_sel:
            messagebox.showwarning("Aviso", "Selecione um funcionário para deletar.")
            return
        
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja remover este funcionário?"):
            idx = self.tree_func.index(item_sel[0])
            del self.funcionarios[idx]
            self.refresh_tree_funcionarios()
            self.limpar_campos_func()

    def refresh_tree_funcionarios(self):
        for item in self.tree_func.get_children():
            self.tree_func.delete(item)
        for i, f in enumerate(self.funcionarios, 1):
            self.tree_func.insert('', 'end', values=(i, f.nome, f.tipo))
        self.update_combo_dispo()

    def limpar_campos_func(self):
        self.ent_nome.delete(0, tk.END)
        self.combo_tipo.set("ENFERMEIRO")
        self.tree_func.selection_remove(self.tree_func.selection())

    # --- ABA 3: INDISPONIBILIDADE ---
    def setup_aba_disponibilidade(self):
        frame_topo = ttk.Frame(self.frame_disponibilidade, padding=10)
        frame_topo.pack(fill='x')
        
        ttk.Label(frame_topo, text="Selecione o Funcionário:").pack(side=tk.LEFT)
        self.combo_disp_func = ttk.Combobox(frame_topo, width=30, state="readonly")
        self.combo_disp_func.pack(side=tk.LEFT, padx=10)
        self.combo_disp_func.bind("<<ComboboxSelected>>", self.refresh_calendar)
        
        legenda = ttk.Label(frame_topo, text="[ VERDE: OK ] [ VERMELHO: BLOQUEADO ] [ AZUL: PREFERÊNCIA ]", foreground="gray")
        legenda.pack(side=tk.RIGHT)

        self.canvas_cal = tk.Canvas(self.frame_disponibilidade)
        self.scroll_cal = ttk.Scrollbar(self.frame_disponibilidade, orient="vertical", command=self.canvas_cal.yview)
        self.frame_btns = ttk.Frame(self.canvas_cal)

        self.frame_btns.bind("<Configure>", lambda e: self.canvas_cal.configure(scrollregion=self.canvas_cal.bbox("all")))
        self.canvas_cal.create_window((0, 0), window=self.frame_btns, anchor="nw")
        self.canvas_cal.configure(yscrollcommand=self.scroll_cal.set)

        self.canvas_cal.pack(side="left", fill="both", expand=True, padx=10)
        self.scroll_cal.pack(side="right", fill="y")

    def update_combo_dispo(self):
        self.combo_disp_func['values'] = [f.nome for f in self.funcionarios]
        self.combo_disp_func.set("") 

    def refresh_calendar(self, event=None):
        for widget in self.frame_btns.winfo_children():
            widget.destroy()
            
        nome_sel = self.combo_disp_func.get()
        f = next((x for x in self.funcionarios if x.nome == nome_sel), None)
        if not f: return
        if not self.periodo_inicio:
            messagebox.showwarning("Aviso", "Defina o período na Aba 1 primeiro.")
            return

        dias_nome = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        for i, d_nome in enumerate(dias_nome):
            btn_all = tk.Button(self.frame_btns, text=f"Bloquear\n{d_nome}s", font=('Arial', 7),
                               command=lambda d_idx=i, func=f: self.bloquear_dia_semana(func, d_idx))
            btn_all.grid(row=0, column=i+1, padx=2, pady=5)

        curr = self.periodo_inicio
        row = 1
        while curr <= self.periodo_fim:
            lbl_data = ttk.Label(self.frame_btns, text=curr.strftime('%d/%m (%a)'), width=15)
            lbl_data.grid(row=row, column=0, padx=5, pady=2)
            
            col_idx = curr.weekday() + 1
            for t_idx, turno in enumerate(["DIA", "NOITE"]):
                cor = self.get_cor(f, curr, turno)
                b = tk.Button(self.frame_btns, text=turno, bg=cor, width=8,
                             command=lambda d=curr, t=turno, obj=f: self.toggle_disp(obj, d, t))
                b.grid(row=row + t_idx, column=col_idx, padx=2, pady=1)
                
            curr += timedelta(days=1)
            row += 2

    def bloquear_dia_semana(self, f, dia_index):
        curr = self.periodo_inicio
        while curr <= self.periodo_fim:
            if curr.weekday() == dia_index:
                f.disponibilidade[(curr, "DIA")] = "INDISPONIVEL"
                f.disponibilidade[(curr, "NOITE")] = "INDISPONIVEL"
            curr += timedelta(days=1)
        self.refresh_calendar()

    def get_cor(self, f, d, t):
        s = f.disponibilidade.get((d, t), "DISPONIVEL")
        return {"DISPONIVEL": "lightgreen", "INDISPONIVEL": "salmon", "PREFERENCIAL": "lightblue"}.get(s)

    def toggle_disp(self, f, d, t):
        estados = ["DISPONIVEL", "INDISPONIVEL", "PREFERENCIAL"]
        atual = f.disponibilidade.get((d, t), "DISPONIVEL")
        novo = estados[(estados.index(atual) + 1) % 3]
        f.disponibilidade[(d, t)] = novo
        self.refresh_calendar()

    # --- ABA 4: GERAÇÃO DE ESCALA ---
    def setup_aba_escala(self):
        frame_top = ttk.Frame(self.frame_escala, padding=10)
        frame_top.pack(fill='x')
        
        ttk.Button(frame_top, text="GERAR ESCALA FINAL", command=self.processar_escala).pack(side=tk.LEFT, padx=10)
        ttk.Button(frame_top, text="Exportar PDF", command=self.exportar_pdf).pack(side=tk.LEFT)
        
        self.tree_escala = ttk.Treeview(self.frame_escala, columns=('Data', 'Turno', 'Enf', 'Mot'), show='headings')
        self.tree_escala.heading('Data', text='Data')
        self.tree_escala.heading('Turno', text='Turno')
        self.tree_escala.heading('Enf', text='Enfermeiro')
        self.tree_escala.heading('Mot', text='Motorista')
        self.tree_escala.pack(fill='both', expand=True, padx=10, pady=10)

    def processar_escala(self):
        if not self.funcionarios: 
            messagebox.showwarning("Aviso", "Cadastre funcionários primeiro.")
            return
        if not self.periodo_inicio or not self.periodo_fim:
            messagebox.showwarning("Aviso", "Defina o período na Aba 1.")
            return
        
        for f in self.funcionarios: f.resetar_contadores()
        self.escala = []
        
        curr = self.periodo_inicio
        while curr <= self.periodo_fim:
            for turno in ["DIA", "NOITE"]:
                p = Plantao(curr, turno, "12h")
                
                enf = self.selecionar_melhor(curr, turno, "ENFERMEIRO")
                if enf:
                    p.enfermeiro = enf
                    self.marcar_plantao(enf, curr, turno)
                
                mot = self.selecionar_melhor(curr, turno, "MOTORISTA")
                if mot:
                    p.motorista = mot
                    self.marcar_plantao(mot, curr, turno)
                
                self.escala.append(p)
            curr += timedelta(days=1)
        self.render_escala()

    def selecionar_melhor(self, data, turno, tipo):
        candidatos = []
        for f in self.funcionarios:
            if f.tipo != tipo: continue
            if f.disponibilidade.get((data, turno)) == "INDISPONIVEL": continue
            if f.ultimo_plantao:
                u_d, u_t = f.ultimo_plantao
                if u_d == data: continue 
                if turno == "DIA" and u_d == (data - timedelta(days=1)) and u_t == "NOITE": continue
            candidatos.append(f)
        
        if not candidatos: return None
        
        candidatos.sort(key=lambda x: (
            0 if x.disponibilidade.get((data, turno)) == "PREFERENCIAL" else 1,
            x.total_plantoes
        ))
        return candidatos[0]

    def marcar_plantao(self, f, data, turno):
        f.ultimo_plantao = (data, turno)
        f.total_plantoes += 1

    def render_escala(self):
        for item in self.tree_escala.get_children(): self.tree_escala.delete(item)
        for p in self.escala:
            enf = p.enfermeiro.nome if p.enfermeiro else "VAGO"
            mot = p.motorista.nome if p.motorista else "VAGO"
            self.tree_escala.insert('', 'end', values=(p.data.strftime('%d/%m/%y'), p.turno, enf, mot))

    def exportar_pdf(self):
        if not self.escala: 
            messagebox.showwarning("Aviso", "Gere a escala antes de exportar.")
            return
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(190, 10, "ESCALA DE PLANTÃO - EMERGÊNCIA", ln=True, align='C')
        pdf.ln(5)
        pdf.set_font("Arial", size=10)
        
        for p in self.escala:
            txt = f"{p.data.strftime('%d/%m')} | {p.turno} | Enf: {p.enfermeiro.nome if p.enfermeiro else 'VAGO'} | Mot: {p.motorista.nome if p.motorista else 'VAGO'}"
            pdf.cell(190, 8, txt, ln=True, border=1)
        
        try:
            pdf.output("escala.pdf")
            messagebox.showinfo("Sucesso", "PDF 'escala.pdf' gerado com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível gerar o PDF: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = EscalaApp(root)
    root.mainloop()