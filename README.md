Sistema de Escala Inteligente - Emergência Móvel
Este é um aplicativo desktop desenvolvido em Python para automatizar a gestão de escalas de plantão para equipes de emergência (Enfermeiros e Motoristas). O sistema utiliza uma lógica de distribuição justa para evitar sobrecarga de trabalho e respeitar a disponibilidade de cada funcionário.

Funcionalidades
Gestão de Ciclos: Defina o período de início e fim da escala de forma flexível.

Cadastro de Funcionários: Registro de nomes e cargos (Enfermeiro ou Motorista) com persistência de dados.

Calendário de Disponibilidade: Interface interativa para marcar dias como:

Disponível: Pode ser escalado normalmente.

Indisponível: O sistema nunca o escalará nesse turno.

Preferencial: O sistema dará prioridade para este funcionário no turno escolhido.

Algoritmo de Escalonamento Inteligente:

Evita dobras de turno (não permite trabalhar dia e noite seguidos).

Distribui os plantões de forma equilibrada entre os disponíveis.

Prioriza quem tem menos plantões acumulados no ciclo.

Exportação para PDF: Gera um documento formatado e pronto para impressão ou compartilhamento via WhatsApp/E-mail.

🛠️ Tecnologias Utilizadas
Linguagem: Python 3.x

Interface Gráfica: tkinter (Nativo do Python)

Componentes Avançados: tkcalendar (Para seleção de datas)

Geração de Relatórios: fpdf

Armazenamento: JSON (Persistência local leve)

Como Instalar e Rodar
Clone o repositório:

Bash
git clone https://github.com/CarlosAlvesSantosJr/escalas-de-plantao.git
cd escalas-de-plantao
Instale as dependências:
Você precisará instalar as bibliotecas externas via pip:

Bash
pip install tkcalendar fpdf

Ou para o frontend web use:

Bash
pip install -r requirements.txt

Execute o aplicativo desktop:

Bash
python app.py

Execute o frontend web:

Bash
python webapp.py

Em seguida abra no navegador:

http://localhost:5000

Rodar com Docker (recomendado)

Com o Docker Desktop instalado, dê dois cliques em iniciar.bat (Windows) ou rode ./iniciar.sh (macOS/Linux). Pelo terminal:

Bash
docker compose up -d --build

Abra http://localhost:8080. Os dados ficam na pasta ./dados. Guia passo a passo para quem não é da área: docs/INSTALACAO.md

Documentação do projeto (contexto, fluxogramas, arquitetura e resultados): docs/PORTFOLIO.md

Rodar os testes:

Bash
python -m pytest

Estrutura do projeto

escala/dominio.py       Modelos (Funcionario, Periodo, Plantao) e enums (Cargo, Turno, Status)
escala/algoritmo.py     Geração da escala (puro, sem UI, testável)
escala/repositorio.py   Persistência JSON atômica (lê também o formato antigo)
escala/relatorio_pdf.py Exportação PDF
webapp.py               API Flask + frontend web (static/)
app.py                  Versão desktop Tkinter, usando o mesmo núcleo
tests/                  Testes do algoritmo e da API

Regras de Negócio do Algoritmo
Regras rígidas (nunca violadas):

Indisponível / Férias: o profissional nunca é escalado nesse turno.

Um plantão por dia: ninguém trabalha DIA e NOITE no mesmo dia.

Descanso pós-noite: quem trabalhou à NOITE não pega o DIA seguinte.

Critérios de escolha, em ordem:

1. Olhar adiante: evita escalar alguém que é o único disponível num turno logo à frente (o que criaria uma vaga).

2. Ninguém fica 7 dias sem plantão, exceto quem esteve bloqueado (férias/indisponível) a janela inteira.

3. Carga equilibrada: menor número de plantões. O turno "Preferencial" conta como um plantão a menos, então pesa na escolha sem atropelar a equidade.

4. Equilíbrio de noites e de fins de semana entre a equipe.

5. Quem trabalhou há mais tempo; por fim, ordem alfabética (resultado determinístico).

Vagas que não puderem ser preenchidas aparecem com o motivo (ex.: "Todos os motoristas indisponíveis").

Persistência de Dados
O sistema gera um arquivo chamado dados_escala.json na mesma pasta do executável. Isso garante que, ao fechar o programa, você não perca os funcionários cadastrados nem as configurações de disponibilidade.

Licença
Este projeto está sob a licença MIT. Veja o arquivo LICENSE para detalhes.

⭐ Desenvolvido por Carlos Alves Santos Jr

<img width="1920" height="1080" alt="Captura de Tela (118)" src="https://github.com/user-attachments/assets/311e1752-3466-4fd1-a153-b422bc2d8940" />
<img width="1920" height="1080" alt="Captura de Tela (120)" src="https://github.com/user-attachments/assets/c92ddde2-cef3-406b-8c87-3b61941d00c3" />
<img width="1920" height="1080" alt="Captura de Tela (119)" src="https://github.com/user-attachments/assets/a25870e6-13f9-426d-8c7f-ecf9db02d449" />
