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
Execute o aplicativo:

Bash
python nome_do_seu_arquivo.py
Regras de Negócio do Algoritmo
O sistema segue regras rígidas de segurança hospitalar na geração automática:

Descanso Mínimo: Se um funcionário trabalhou no turno da NOITE, ele não pode ser escalado para o turno do DIA seguinte.

Carga Horária Equilibrada: O algoritmo sempre seleciona o funcionário com o menor número de plantões realizados até aquele momento, entre os que estão disponíveis.

Respeito às Preferências: Se alguém marcou um turno como "Preferencial", o sistema tentará colocá-lo ali antes de buscar outros candidatos.

Persistência de Dados
O sistema gera um arquivo chamado dados_escala.json na mesma pasta do executável. Isso garante que, ao fechar o programa, você não perca os funcionários cadastrados nem as configurações de disponibilidade.

Licença
Este projeto está sob a licença MIT. Veja o arquivo LICENSE para detalhes.
Desenvolvido por Carlos Alves Santos Jr
