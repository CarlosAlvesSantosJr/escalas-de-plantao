import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime, timedelta
import re
from fpdf import FPDF
from tkcalendar import DateEntry

# =========================
# MODELOS
# =========================

class Funcionario:
    def __init__(self, nome, tipo):
        self.nome = nome
        self.tipo = tipo
        self.disponibilidade = {}  
        self.total_plantoes = 0
        self.ultimo_plantao = None

    def resetar_contadores(self):
        self.total_plantoes = 0
        self.ultimo_plantao = None

class Plantao:
    def __init__(self, data, turno):
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
        self.root.geometry("1100x850") # Aumentado um pouco para o calendário caber melhor
        
        self.funcionarios = []
        self.escala = []
        self.periodo_inicio = None
        self.periodo_fim = None
        
        self.criar_interface()

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

    def validar_nome(self, nome_sujo):
        nome_limpo = nome_sujo.strip().upper()
        if not nome_limpo:
            messagebox.showwarning("Aviso", "O nome não pode estar vazio.")
            return None
        if not re.match(r'^[A-ZÀ-Ÿ\s]+$', nome_limpo):
            messagebox.showwarning("Erro", "Apenas letras e espaços são permitidos.")
            return None
        return nome_limpo

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
        self.periodo_inicio = self.ent_inicio.get_date()
        self.periodo_fim = self.ent_fim.get_date()
        if self.periodo_inicio > self.periodo_fim:
            messagebox.showerror("Erro", "Data início maior que fim.")
            return
        messagebox.showinfo("Sucesso", "Período definido!")
        self.notebook.select(1)

    def setup_aba_funcionarios(self):
        frame_cad = ttk.LabelFrame(self.frame_funcionarios, text="Cadastro", padding=10)
        frame_cad.pack(fill='x', padx=10, pady=10)
        
        self.ent_nome = ttk.Entry(frame_cad, width=30)
        self.ent_nome.grid(row=0, column=0, padx=5)
        self.combo_tipo = ttk.Combobox(frame_cad, values=["ENFERMEIRO", "MOTORISTA"], state="readonly")
        self.combo_tipo.set("ENFERMEIRO")
        self.combo_tipo.grid(row=0, column=1, padx=5)
        
        ttk.Button(frame_cad, text="Adicionar", command=self.add_funcionario).grid(row=0, column=2, padx=2)
        ttk.Button(frame_cad, text="Alterar", command=self.update_funcionario).grid(row=0, column=3, padx=2)
        ttk.Button(frame_cad, text="Deletar", command=self.delete_funcionario).grid(row=0, column=4, padx=2)

        self.tree_func = ttk.Treeview(self.frame_funcionarios, columns=('ID', 'Nome', 'Cargo'), show='headings', height=10)
        self.tree_func.heading('ID', text='ID'); self.tree_func.heading('Nome', text='Nome'); self.tree_func.heading('Cargo', text='Cargo')
        self.tree_func.column('ID', width=50); self.tree_func.pack(fill='both', expand=True, padx=10)
        self.tree_func.bind('<<TreeviewSelect>>', self.carregar_dados_funcionario)

    def add_funcionario(self):
        nome = self.validar_nome(self.ent_nome.get())
        if nome:
            self.funcionarios.append(Funcionario(nome, self.combo_tipo.get()))
            self.refresh_tree_funcionarios()
            self.limpar_campos_func()

    def update_funcionario(self):
        sel = self.tree_func.selection()
        if not sel: return
        nome = self.validar_nome(self.ent_nome.get())
        if nome:
            idx = self.tree_func.index(sel[0])
            self.funcionarios[idx].nome = nome
            self.funcionarios[idx].tipo = self.combo_tipo.get()
            self.refresh_tree_funcionarios()
            self.limpar_campos_func()

    def delete_funcionario(self):
        sel = self.tree_func.selection()
        if sel and messagebox.askyesno("Confirmar", "Deletar funcionário?"):
            idx = self.tree_func.index(sel[0])
            del self.funcionarios[idx]
            self.refresh_tree_funcionarios()

    def refresh_tree_funcionarios(self):
        for item in self.tree_func.get_children(): self.tree_func.delete(item)
        for i, f in enumerate(self.funcionarios, 1):
            self.tree_func.insert('', 'end', values=(i, f.nome, f.tipo))
        self.update_combo_dispo()

    def carregar_dados_funcionario(self, event):
        sel = self.tree_func.selection()
        if sel:
            v = self.tree_func.item(sel[0], 'values')
            self.ent_nome.delete(0, tk.END); self.ent_nome.insert(0, v[1])
            self.combo_tipo.set(v[2])

    def limpar_campos_func(self):
        self.ent_nome.delete(0, tk.END)
        self.tree_func.selection_remove(self.tree_func.selection())

    # =========================
    # ABA DISPONIBILIDADE (ATUALIZADA)
    # =========================
    def setup_aba_disponibilidade(self):
        frame_topo = ttk.Frame(self.frame_disponibilidade, padding=10)
        frame_topo.pack(fill='x')
        
        ttk.Label(frame_topo, text="Selecione o Funcionário:").pack(side=tk.LEFT, padx=5)
        self.combo_disp_func = ttk.Combobox(frame_topo, width=30, state="readonly")
        self.combo_disp_func.pack(side=tk.LEFT, padx=10)
        self.combo_disp_func.bind("<<ComboboxSelected>>", self.refresh_calendar)
        
        # Container com scroll
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
        # Limpar calendário anterior
        for w in self.frame_btns.winfo_children(): 
            w.destroy()
            
        nome = self.combo_disp_func.get()
        f = next((x for x in self.funcionarios if x.nome == nome), None)
        
        if not f or not self.periodo_inicio: 
            ttk.Label(self.frame_btns, text="Defina o período e selecione um funcionário.", padding=20).pack()
            return

        # Cabeçalhos da Semana
        dias_semana = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        for i, dia in enumerate(dias_semana):
            lbl = tk.Label(self.frame_btns, text=dia, font=('Arial', 9, 'bold'), width=12, fg="gray")
            lbl.grid(row=0, column=i, padx=5, pady=10)

        # Lógica de preenchimento do calendário
        curr = self.periodo_inicio
        # No Python, weekday() retorna 0 para Segunda e 6 para Domingo
        coluna = curr.weekday() 
        linha = 1

        while curr <= self.periodo_fim:
            # Container do Dia
            dia_frame = tk.Frame(self.frame_btns, bd=1, relief="solid", highlightbackground="#ddd")
            dia_frame.grid(row=linha, column=coluna, sticky="nsew", padx=2, pady=2)
            
            # Label da Data
            cor_data = "blue" if curr.weekday() >= 5 else "black" # Destaca final de semana
            lbl_data = tk.Label(dia_frame, text=curr.strftime('%d/%m'), font=('Arial', 8, 'bold'), fg=cor_data)
            lbl_data.pack(pady=2)

            # Botões de Turno
            for turno in ["DIA", "NOITE"]:
                cor = self.get_cor(f, curr, turno)
                btn = tk.Button(dia_frame, text=turno, bg=cor, font=('Arial', 7),
                               width=10, command=lambda d=curr, t=turno, obj=f: self.toggle_disp(obj, d, t))
                btn.pack(fill='x', padx=2, pady=1)

            # Incremento de posição
            coluna += 1
            if coluna > 6:
                coluna = 0
                linha += 1
            
            curr += timedelta(days=1)

    def get_cor(self, f, d, t):
        s = f.disponibilidade.get((d, t), "DISPONIVEL")
        return {"DISPONIVEL": "#e1f5fe", "INDISPONIVEL": "#ffcdd2", "PREFERENCIAL": "#c8e6c9"}.get(s)

    def toggle_disp(self, f, d, t):
        estados = ["DISPONIVEL", "INDISPONIVEL", "PREFERENCIAL"]
        atual = f.disponibilidade.get((d, t), "DISPONIVEL")
        f.disponibilidade[(d, t)] = estados[(estados.index(atual) + 1) % 3]
        self.refresh_calendar()

    # =========================
    # ABA ESCALA
    # =========================
    def setup_aba_escala(self):
        frame_top = ttk.Frame(self.frame_escala, padding=10)
        frame_top.pack(fill='x')
        ttk.Button(frame_top, text="GERAR ESCALA", command=self.processar_escala).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_top, text="EXPORTAR PDF", command=self.exportar_pdf).pack(side=tk.LEFT)
        
        self.tree_escala = ttk.Treeview(self.frame_escala, columns=('Data', 'Turno', 'Enf', 'Mot'), show='headings')
        for col in ('Data', 'Turno', 'Enf', 'Mot'): 
            self.tree_escala.heading(col, text=col)
            self.tree_escala.column(col, anchor="center")
        self.tree_escala.pack(fill='both', expand=True, padx=10, pady=10)

    def processar_escala(self):
        if not self.funcionarios or not self.periodo_inicio:
            messagebox.showwarning("Aviso", "Cadastre funcionários e defina o período.")
            return
        
        for f in self.funcionarios: f.resetar_contadores()
        self.escala = []
        
        data_atual = self.periodo_inicio
        while data_atual <= self.periodo_fim:
            for turno in ["DIA", "NOITE"]:
                p = Plantao(data_atual, turno)
                p.enfermeiro = self.selecionar_melhor(data_atual, turno, "ENFERMEIRO")
                p.motorista = self.selecionar_melhor(data_atual, turno, "MOTORISTA")
                self.escala.append(p)
            data_atual += timedelta(days=1)
        self.render_escala()

    def selecionar_melhor(self, data, turno, tipo):
        candidatos = []
        for f in self.funcionarios:
            if f.tipo != tipo: continue
            if f.disponibilidade.get((data, turno)) == "INDISPONIVEL": continue
            
            # Regra de Descanso: Não trabalhar no mesmo dia ou Dobradinha Noite -> Dia seguinte
            if f.ultimo_plantao:
                u_data, u_turno = f.ultimo_plantao
                if u_data == data: continue 
                if turno == "DIA" and u_data == (data - timedelta(days=1)) and u_turno == "NOITE":
                    continue
            candidatos.append(f)
        
        if not candidatos: return None
        
        # Prioridade: 1. Preferencial | 2. Quem tem menos plantões acumulados
        candidatos.sort(key=lambda x: (
            0 if x.disponibilidade.get((data, turno)) == "PREFERENCIAL" else 1,
            x.total_plantoes
        ))
        
        escolhido = candidatos[0]
        escolhido.total_plantoes += 1
        escolhido.ultimo_plantao = (data, turno)
        return escolhido

    def render_escala(self):
        for item in self.tree_escala.get_children(): self.tree_escala.delete(item)
        for p in self.escala:
            e_nome = p.enfermeiro.nome if p.enfermeiro else "VAGO"
            m_nome = p.motorista.nome if p.motorista else "VAGO"
            self.tree_escala.insert('', 'end', values=(p.data.strftime('%d/%m/%y (%a)'), p.turno, e_nome, m_nome))

    def exportar_pdf(self):
        if not self.escala: 
            messagebox.showwarning("Aviso", "Gere a escala antes de exportar.")
            return
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(190, 10, "ESCALA DE PLANTÃO - EMERGÊNCIA MÓVEL", ln=True, align='C')
        pdf.ln(5)
        
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(40, 7, "Data", 1); pdf.cell(30, 7, "Turno", 1); pdf.cell(60, 7, "Enfermeiro", 1); pdf.cell(60, 7, "Motorista", 1)
        pdf.ln()
        
        pdf.set_font("Arial", size=10)
        for p in self.escala:
            e = p.enfermeiro.nome if p.enfermeiro else "VAGO"
            m = p.motorista.nome if p.motorista else "VAGO"
            pdf.cell(40, 7, p.data.strftime('%d/%m/%y'), 1)
            pdf.cell(30, 7, p.turno, 1)
            pdf.cell(60, 7, e, 1)
            pdf.cell(60, 7, m, 1)
            pdf.ln()
            
        pdf.output("escala_emergencia.pdf")
        messagebox.showinfo("Sucesso", "PDF 'escala_emergencia.pdf' gerado com sucesso!")

if __name__ == "__main__":
    root = tk.Tk()
    app = EscalaApp(root)
    root.mainloop()