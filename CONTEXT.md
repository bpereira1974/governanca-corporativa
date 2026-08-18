# CONTEXT.md — Motor de Governança Corporativa
> Documento de contexto do projeto. Atualizar sempre que houver decisões relevantes.
> Ao abrir o Claude Code, começar com: "leia o CONTEXT.md antes de qualquer coisa".

---

## O que é esse projeto

Ferramenta para avaliação e ranking de governança corporativa de empresas brasileiras listadas na B3. Dado um conjunto de campos sobre uma empresa, o motor calcula uma nota de 0 a 100 distribuída em 5 blocos. O objetivo final é que o analista possa avaliar uma nova empresa combinando:
1. Dados buscados automaticamente no BigQuery (CVM/FRE)
2. Campos preenchidos manualmente pelo analista (critérios qualitativos)
3. Dados extraídos do estatuto social (cláusulas específicas)

**Objetivo central (confirmado 2026-07-03):** o critério de sucesso real do projeto é conseguir extrair automaticamente, para QUALQUER empresa listada na B3, os dados do FRE (Formulário de Referência) e do Estatuto Social — não só reprocessar a planilha das 10 empresas de exemplo. O motor de scoring por si só tem valor limitado sem essa automação de sourcing. Ao priorizar próximos passos, priorizar sempre o que aproxima dessa automação.

---

## Arquitetura atual (Python puro — fase 1)

```
governanca-corporativa/
├── src/
│   ├── main.py                 # Entrypoint: roda avaliação completa e exibe ranking
│   ├── scoring_engine.py       # Motor de cálculo de notas por bloco
│   ├── parser_planilha.py      # Lê Template_Governança.xlsx e extrai dados das empresas
│   ├── fre_pdf_parser.py       # Extrai Conselho/Diretoria/Comitês direto do PDF do FRE
│   ├── dashboard_store.py      # Persistência (JSON) das empresas processadas no dashboard
│   ├── dashboard_app.py        # Dashboard interativo (Streamlit) — ver seção própria abaixo
│   └── utils/
│       └── logging_utils.py    # Logger estruturado padrão LEQ (custom_log)
├── configs/
│   └── config.py               # Todas as regras de pontuação (pesos, tabelas de conversão)
├── tests/
├── data/
│   ├── Template_Governança.xlsx    # Planilha com critérios e 10 empresas de exemplo
│   └── dashboard_store.json        # Store do dashboard (gerado, gitignored — ver *.json)
├── CONTEXT.md                  # Este arquivo
├── requirements.txt            # pandas, openpyxl, python-dotenv, pdfplumber, streamlit
├── .env.example
└── .gitignore
```

**Próximas fases planejadas (ainda não implementadas):**
- API Flask (Cloud Run) — expor o motor como endpoint HTTP
- MCP Server — ferramentas para o Claude usar diretamente
- Módulo BigQuery — buscar dados do FRE automaticamente
- ~~Dashboard~~ — **iniciado em 2026-08-04** (Streamlit), ver seção "Dashboard de Governança" abaixo

---

## Modelo de scoring (100 pontos)

| Bloco | Peso | Critérios principais |
|---|---|---|
| Segmento de Listagem | 10 | Nível de listagem B3 + mitigadores de tag along |
| Direitos dos Acionistas | 10 | Conselho Fiscal, Poison Pill, limitações |
| Estrutura Acionária | 20 | Natureza, controlador, insiders, conflitos, partes relacionadas |
| Conselho de Administração | 30 | Estrutura (# membros) + qualidade/diversidade |
| Diretoria | 20 | Qualidade, transparência rem., práticas contábeis, contingências, sustentabilidade |

**Regra importante:** para todos os blocos, nota bruta = nota ponderada (o peso de cada bloco já é igual ao seu máximo de pontos brutos). Não há normalização adicional.

---

## Calibração do motor (status atual)

O motor foi calibrado contra as 10 empresas de exemplo da planilha:

| Empresa | Motor | Planilha | Status |
|---|---|---|---|
| B3 | 62.0 | 62 | ✓ |
| BTG Pactual | 60.0 | 61 | ✓ (~1pt) |
| LOG | 58.0 | 58 | ✓ |
| Lopes | 56.5 | 56.5 | ✓ |
| Multiplan | 65.5 | 65.5 | ✓ |
| Itausa | 72.0 | 76 | ← diff de 4pts no bloco Conselho |
| Itau | 67.0 | 67 | ✓ |
| Bradesco | 48.0 | 47 | ✓ (~1pt) |
| Banco do Brasil | 47.0 | 48 | ✓ (~1pt) |
| Cyrela | 72.0 | 72 | ✓ |

**Issues conhecidos:**
- **Itausa Conselho (-4pts):** analista usou nota estrutura 3 para 8 membros, mas o Guia define nota 2 para 8 membros. Divergência de interpretação humana — não automatizável.
- **BTG/Bradesco/BB (~1pt na Diretoria):** subcritério ainda não identificado. Diferença mínima, não prioritário.
- **Bradesco divergiu mais em 2026-07-03** (motor deu 46.0 rodando localmente, vs 48.0 registrado acima): a planilha copiada para esta máquina pode ser uma versão mais recente/atualizada que a usada na calibração original. Não é bug de código (as outras 9 empresas bateram exato) — fica para revisão quando os critérios forem reavaliados.

**Correções importantes já aplicadas:**
- Parser busca `% Remuneração Fixa` da **Diretoria** (2ª ocorrência na planilha, `campo_nth(n=1)`), não do Conselho
- Corporation sem controlador: `participação = 3pts`, `visão = 3pts` (neutro)
- Mitigadores de tag along inferidos do campo "Comentário" do segmento
- `natureza_estrutura` comparada em lowercase
- Nota estrutura do Conselho: 1→2pts, 2→6pts, 3→10pts (fixo, não normalizado)

---

## Campos do scoring e suas origens

### Campos automáticos (virão do BigQuery/FRE)
Mapeamento descoberto lendo o FRE da Cyrela (Formulário de Referência 2026, Versão 1).

#### Seção 6.1/2 — Posição Acionária
Tabela estruturada com uma linha por acionista. Colunas relevantes:
- `Participa de acordo de acionistas` (Sim/Não)
- `Acionista controlador` (Sim/Não)
- `Total ações %`

| Campo do scoring | Como derivar |
|---|---|
| `natureza_estrutura` | Se nenhum acionista tem `Acionista controlador = Sim` → "Corporation". Se houver acionista estatal controlador → "Controle Estatal". Caso contrário → "Controle Privado" |
| `participacao_controlador` | Somar `Total ações %` de todos com `Acionista controlador = Sim` |
| `insiders_ownership` | Somar `Total ações %` dos membros da administração (cruzar com seção 7.3) |

#### Seção 1.13 — Acordos de Acionistas
Texto livre.

| Campo do scoring | Como derivar |
|---|---|
| `acordo_acionistas` (Sim/Não) | Buscar padrão "não possui acordo" → Não; qualquer descrição de acordo → Sim |

#### Seção 7.1D — Características dos Órgãos (tabela estruturada)
Tabela com contagem de membros por gênero por órgão.

| Campo do scoring | Como derivar |
|---|---|
| `n_membros_conselho` | Linha "Conselho de Administração - Efetivos": somar Feminino + Masculino + outros |
| `n_membros_diretoria` | Linha "Diretoria": somar todos |
| `conselho_fiscal_permanente` / `instalado` | Campo texto no início de 7.3: ex. "Funcionamento do conselho fiscal: Não permanente e instalado" |

#### Seção 7.3 — Composição e Experiências
Ficha por membro com: nome, CPF, experiência profissional, órgão, cargo eletivo, data da eleição, data de início do **primeiro mandato**, flag "Foi eleito pelo controlador".

| Campo do scoring | Como derivar |
|---|---|
| `pct_membros_independentes` | Contar membros com "Independente" no cargo / total membros CA |
| `n_conselheiros_mais_5_anos` | Calcular (hoje - data_inicio_primeiro_mandato) > 5 anos |
| `n_conselheiros_mais_10_anos` | Calcular (hoje - data_inicio_primeiro_mandato) > 10 anos |
| `qualidade_conselho` (nota 1–5) | **Input manual do analista** — requer leitura da experiência profissional |

#### Seção 7.4 — Composição dos Comitês

| Campo do scoring | Como derivar |
|---|---|
| Lista de comitês existentes | Campo "Tipo comitê" + "Descrição de outros comitês" |
| `comites_com_membros_externos` | Cruzar membros dos comitês com lista da Diretoria |

### Campos do estatuto social (requerem leitura de PDF por IA)
- `poison_pill` (Sim/Não) e `poison_pill_threshold` (%)
- `limite_voto` (Sim/Não)
- `limite_dividendo` (Sim/Não)

**Abordagem planejada:** usar Claude via API para ler o estatuto em PDF e extrair esses campos em JSON estruturado.

### Campos sempre manuais (input do analista)
- `visao_controlador` (Positiva / Mixed / Negativa)
- `qualidade_conselho` (nota 1–5)
- `qualidade_diretoria` (nota 1–5)
- `potencial_conflito` (Baixo / Médio / Alto)
- `transacoes_partes_relacionadas` (Sim/Não)
- `praticas_contabeis_agressivas` (Sim/Não)
- `contingencias_relevantes` (Sim/Não)

---

## Acesso a dados da CVM (investigado em 2026-07-03)

**BigQuery interno da LEQ:** hipótese de tabela `cvm.fre_cia_aberta` repassada pelo usuário, mas **não confirmada nem descartada** — nenhuma ferramenta de BigQuery genérica esteve acessível na sessão de investigação (a skill `leblon-bigquery` existe, mas as tools não estavam conectadas). Precisa de alguém com acesso real ao console GCP para verificar se a tabela existe e o que ela cobre. Se existir, é provável que seja uma família de tabelas por seção (`fre_cia_aberta_<secao>`), não uma tabela única — é assim que a CVM organiza os dados oficialmente (ver abaixo).

**Caminho público confirmado e funcional (independe do BigQuery):** portal de dados abertos `https://dados.cvm.gov.br/`, sem autenticação.
- **FRE estruturado:** `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_AAAA.zip` — um ZIP por ano-base (2010–2026 disponíveis), contendo dezenas de CSVs internos, um por seção do Anexo 24/Resolução CVM 80/22, cobrindo todas as companhias abertas daquele ano (cada linha tem `CNPJ_CIA` para filtrar por empresa). Dicionário de dados: `https://dados.cvm.gov.br/dataset/cia_aberta-doc-fre/resource/4ffa636e-95a3-48ac-979c-7396213930ff`.
  - Seções 7.1D, 7.3, 7.4 têm cobertura razoável nos CSVs.
  - Seções 6.1/2 (posição acionária) e 1.13 (acordo de acionistas) ainda não confirmadas arquivo a arquivo — mapear ao inspecionar o zip.
- **Estatuto Social NÃO está no FRE.** Fica no dataset **IPE** (Informações Periódicas e Eventuais): `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_AAAA.zip` — um índice CSV de metadados de documentos por empresa/tipo/data; o PDF do estatuto é baixado separadamente a partir desse índice (alternativa manual: sistema RAD/ENET `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`).
- Não existe API REST oficial da CVM — é sempre download de arquivo estático (ZIP/CSV/PDF).

**Conclusão:** o objetivo central (extrair FRE + Estatuto de qualquer empresa) é viável hoje via `dados.cvm.gov.br`, independente de resolver o BigQuery interno. O BigQuery, se existir e estiver populado, seria um atalho mais limpo, mas não é bloqueante — pode ser feito em paralelo.

**Pendente (próxima sessão):** baixar `fre_cia_aberta_2025.zip` (~8.1MB, ainda não baixado — aguardando confirmação do usuário) para inspecionar os CSVs reais e mapear seções 6.1/2 e 1.13.

---

## Padrões de código (LEQ)

- **Sempre consultar** a skill `leq-code-standards` antes de criar qualquer arquivo novo
- Logger: usar `custom_log` de `src/utils/logging_utils.py` — nunca `print()` para mensagens operacionais
- Credenciais: nunca no repo — usar `GOOGLE_APPLICATION_CREDENTIALS` via env var
- Dependências: sempre com versão fixada no `requirements.txt`
- Deploy futuro: Cloud Run, região `southamerica-east1`, `--min-instances 0`

---

## Próximos passos (ordem sugerida, atualizada 2026-07-03)

1. **Confirmar acesso ao BigQuery da LEQ** (`cvm.fre_cia_aberta` ou equivalente) — em paralelo, feito pelo usuário fora do Claude Code
2. ~~Prototipar parser do capítulo 7 (administração) direto do PDF do FRE~~ — **feito**, ver `src/fre_pdf_parser.py` abaixo
3. **Prototipar módulo de download/parsing do FRE via `dados.cvm.gov.br`** — baixar `fre_cia_aberta_AAAA.zip`, inspecionar CSVs reais, mapear seções 6.1/2 e 1.13 que ainda faltam confirmar
4. **Módulo `cvm_client.py`** (nome provisório) — dado um CNPJ, retorna os campos automáticos do FRE, seja via BigQuery (se confirmado) ou via CSVs baixados da CVM
5. **Interface de input manual** — formulário para o analista preencher os campos qualitativos
6. **Módulo `estatuto_parser.py`** — baixar PDF do estatuto via índice IPE da CVM, usar Claude API para extrair campos booleanos (poison pill, limite de voto, limite de dividendo)
7. **Integrar tudo em `main.py`** — pipeline completo: CVM (FRE + estatuto) + input manual → nota final
8. **API Flask** — expor o motor como endpoint HTTP
9. **MCP Server** — ferramentas para o Claude usar diretamente
10. **Dashboard React** — interface visual para analistas

---

## Parser do FRE em PDF (`src/fre_pdf_parser.py`, prototipado 2026-07-03)

Enquanto o caminho via BigQuery/CSV da CVM não está confirmado, prototipamos um parser que le' o **PDF do FRE diretamente** (o formato que os analistas já têm em mãos) e extrai a estrutura do capítulo 7 (administração). Validado ponta a ponta contra o FRE real da Cyrela (2026, Versão 4, páginas 121–165):

- **Biblioteca:** `pdfplumber` (puro Python, sem depender de binário externo como `poppler`/`pdftotext` — mais fácil de empacotar num deploy futuro no Cloud Run)
- **O que extrai:** contagem de membros por órgão (7.1D), lista de membros com currículo resumido e órgão/mandato/tenure (7.3), e composição dos comitês (7.4)
- **Resultado da validação:** 22/22 membros classificados corretamente por órgão (10 Conselho, 6 Diretoria, 3+3 Conselho Fiscal efetivo/suplente), datas de início de mandato batendo 100% com leitura manual, e os 3 comitês (Auditoria Estatutário, Estratégia e Finanças, Pessoas e Sustentabilidade) identificados com o membro certo em cada um
- **Armadilha de parsing descoberta:** o `pdfplumber` (e o `pdftotext`, testado antes) preserva o layout físico linha a linha — quando uma célula de tabela quebra em várias linhas, cada linha física contém fragmentos de **todas** as colunas daquele "andar", então não dá pra simplesmente colapsar quebras de linha e buscar por frases inteiras (ex: "Conselho de Administração" pode aparecer com "Conselho de" numa linha e "Administração" bem mais adiante, intercalada com texto de outras colunas). A solução foi ancorar regex no início de cada linha física e usar heurísticas estruturais (ex: a linha do "Comitê de Auditoria" sempre vem antes de qualquer linha "Outros Comitês")
- **Achado real (não é bug):** tanto Elie Horn quanto Rogério Frota Melzi aparecem como "Presidente do Conselho de Administração" na Cyrela — parece ser uma estrutura de co-presidência do conselho (espelhando os Co-Presidentes da Diretoria)
- **Dependência nova:** `pdfplumber==0.11.4` no `requirements.txt`

### Segundo teste: FRE do BTG Pactual (2026, Versão 4, páginas 267–312)

Confirmou a suspeita: **o layout varia entre empresas** e quebrou duas heurísticas que funcionavam na Cyrela. Ambas corrigidas de forma genérica (sem hardcode pro BTG), sem regredir a Cyrela:

1. **Cargo duplo numa linha só:** Roberto Sallouti (CEO do BTG) ocupa "Diretoria e Conselho de Administração" na mesma linha da tabela — um formato que não existia na Cyrela (lá cada membro só tinha 1 órgão por linha). Ele deveria contar pros dois totais (Conselho E Diretoria), não só um. Corrigido: o parser agora reconhece o conector "e" entre órgãos e a contagem final usa substring em vez de igualdade exata, pra capturar cargos combinados.
2. **Nome do comitê direto na coluna, não via "Outros Comitês":** a Cyrela sempre embrulhava comitês não-estatutários num "Outros Comitês" genérico + nome numa coluna separada. O BTG às vezes coloca o nome direto na coluna "Tipo comitê" (ex: "Comitê de Risco"). Quando esse nome é curto cabe numa linha só; quando é longo (ex: "Comitê de Remuneração") quebra em 2 linhas do mesmo jeito que o "Comitê de Auditoria" quebrava — e o parser capturava por engano a palavra do cargo ("Membro") como se fosse o nome do comitê. Corrigido com uma heurística de recuperação: se a palavra capturada depois de "Comitê de" é uma palavra de cargo conhecida (Membro/Outros/Coordenador/Secretário), o parser busca o nome real no fim da linha normalizada, depois da última data.
- **Resultado final do BTG:** 22/22 membros corretos (9 Conselho, 14 Diretoria — batendo com a tabela 7.1D), 3 comitês certos (Auditoria Estatutário, Remuneração, Risco) com os membros certos em cada
- **Achado de dado (não é bug):** a seção 7.2 do BTG lista 5 comitês (Auditoria, Remuneração, Risco, Compliance, ESG), mas só 3 aparecem na tabela 7.4 (composição por administrador) — Compliance e ESG aparentemente são compostos por pessoas fora do Conselho/Diretoria, então não aparecem nessa tabela específica. Confirmado por busca no texto (não há nenhuma menção a esses dois nomes na seção 7.4 inteira)
- **Limitação que continua:** `KNOWN_COMMITTEE_NAMES` (usado só para o padrão "Outros Comitês") ainda está hardcoded com os nomes da Cyrela — para uma 3ª empresa que use esse padrão com nomes diferentes, precisa estender a lista (ou trocar por uma extração dinâmica a partir da seção 7.2, que lista os comitês de cada empresa em texto livre)

### Terceiro teste: FRE da Estapar/Allpark (2026, páginas 163–204)

Mais dois formatos novos, ambos corrigidos de forma genérica (sem regredir Cyrela nem BTG):

1. **Nome de comitê sem "de" depois de "Comitê":** a Estapar tem um "Comitê Financeiro e de Investimentos" — no FRE, a coluna "Tipo comitê" mostra só "Comitê Financeiro" (sem "de" logo após "Comitê"), diferente do padrão "Comitê de X" visto até então. O regex de início de linha exigia literalmente a palavra "de" — generalizado para aceitar tanto "Comitê de X" quanto "Comitê X" diretamente
2. **Grafia alternativa de "Estatutário":** o sinal usado pra detectar a linha do Comitê de Auditoria buscava o texto fixo "Estatutário", mas este FRE grafa "**Estatuário**" (sem o segundo "t") na descrição do regime regulatório. Regex ajustado pra tolerar as duas grafias (`Estatut?ário`)
3. **Nome do comitê "perdido" quando o texto de outra coluna (prazo do mandato) continua depois do marcador `(Efetivo)`:** a heurística de recuperação de nome (criada pro caso do BTG) assumia que o nome do comitê ficava sempre bem no fim da linha normalizada; na Estapar, o "Prazo do mandato" é um texto longo que continua *depois* do "(Efetivo)", então a heurística precisou ser refinada pra cortar exatamente antes do marcador `(Efetivo)/(Suplente)/(Coordenador)`, descartando o que vem depois
- **Resultado final da Estapar:** 12/12 membros corretos (8 Conselho, 4 Diretoria — batendo com a tabela 7.1D), 3 comitês certos (Auditoria Estatutário, Financeiro — nome parcial, falta "e de Investimentos" —, Inovação), nenhum membro de comitê (16 no total, incluindo 4 externos ao Conselho/Diretoria) ficou sem classificação
- **Conclusão desta rodada de 3 empresas:** a abordagem de parsing generaliza bem — cada nova empresa expôs 1-2 variações de formatação genuínas (não specific-to-company hacks), todas corrigidas com heurísticas que continuam funcionando nas empresas testadas anteriormente. Ainda vale testar mais empresas antes de confiar em produção sem supervisão, mas a confiança na abordagem aumentou bastante

### Detecção automática do capítulo 7 (`find_chapter7_page_range`, 2026-08-04)

Antes disso, era preciso descobrir manualmente (grep/busca de texto) em que páginas do PDF ficava o capítulo 7 de cada empresa — inviável para um dashboard interativo de upload. `find_chapter7_page_range()` escaneia o **cabeçalho de seção repetido** em cada página (a 2ª linha não-vazia, logo após o título "Formulário de Referência...") em busca de "7.1 Principais características" (início) e "8.1"/"7.5 Relações familiares" (fim, o que vier primeiro).

**Armadilha descoberta:** a página de índice também lista "7.1 Principais características..." como item de sumário — checar a substring em qualquer lugar da página dava falso positivo na página 2. A solução foi checar especificamente a 2ª linha da página (que só tem esse texto em páginas de conteúdo real, não no índice, que tem "Índice" nessa posição).

Validado nas 3 empresas: localizou corretamente o intervalo em todas, sem precisar de nenhuma informação manual.

### Correção do "Cargo eletivo ocupado" (`_extract_cargo_eletivo`, 2026-08-04)

**Bug encontrado pelo usuário testando o dashboard:** o campo `cargo_eletivo_ocupado` retornava besteira pros cargos de liderança — Efraim Horn, Raphael Abba Horn e Miguel Mickelberg (Co-Presidentes e CFO da Cyrela) apareciam com cargo **"Diretoria"** (o nome do órgão, não o cargo real), e vários conselheiros "regulares" apareciam com `None`.

**Causa raiz:** a extração buscava a palavra-chave "Diretor" na linha inteira da tabela, mas a primeira ocorrência de "Diretor" é o próprio nome do órgão ("**Diretor**ia", na coluna "Órgão da Administração", que vem *antes* da coluna "Cargo eletivo ocupado" na mesma linha física). A busca capturava esse falso positivo antes de chegar no cargo real.

**Correção:**
1. A busca por palavras-chave de cargo agora começa **depois da 1ª data da linha** (Data da Eleição), que sempre separa a coluna do órgão da coluna do cargo — elimina o falso positivo do nome do órgão
2. Adicionado um fallback pro caso de conselheiros "regulares": o cargo "Conselho de Administração (Efetivo)", escrito por extenso, quebra em várias linhas do mesmo jeito que o nome do órgão (mesma armadilha de sempre) — reconhecido agora pelo marcador `(Efetivo)`/`(Suplente)` que sobrevive intacto, mesmo sem conseguir recortar a frase inteira

**Resultado (validado na Cyrela, 22/22 membros):** todos os cargos agora vêm preenchidos e corretos — "Diretor Presidente", "Diretor Financeiro", "Presidente do Conselho de Administração", "Conselho de Administração (Efetivo)", "C.F.(Efetivo)Eleito" etc. Sem regressão nas contagens de órgãos/comitês.

**Limitação que continua:** quando o título completo quebra em 2 linhas físicas (ex: "Diretor Presidente **/ Superintendente**", "Diretor Financeiro **/ Diretor de Relações com Investidores**", "Conselho de Adm. **Independente (Efetivo)**"), só a 1ª linha é capturada — a parte que vem depois na 2ª linha física ainda se perde, pela mesma razão estrutural de sempre (colunas se intercalam quando o texto quebra em várias linhas). Corrigir isso de vez exigiria parsing por posição (x/y) das palavras no PDF, não só regex em texto — considerar se vira prioridade.

**Pendente:** só foi possível re-testar contra a Cyrela nesta sessão — os PDFs do BTG e da Estapar não estavam mais na pasta Downloads do usuário (provavelmente organizada/limpa desde a última sessão). Os dados dessas duas empresas no dashboard (`data/dashboard_store.json`) ainda têm o cargo do bug antigo até serem reprocessadas.

**Atualização (mesmo dia):** usuário testou o upload por conta própria pelo dashboard e processou uma 4ª empresa (**Even Construtora**) — confirmando que o fluxo de upload funciona de ponta a ponta na prática, não só simulado. Esse teste revelou mais um cargo que quebra em 2 linhas e não estava coberto: **"Vice Presidente [do] Conselho de Administração"** (abreviado "Vice Presidente Cons. de Administração" no PDF). Adicionado como reconstrução por texto fixo, igual ao "Presidente do Conselho de Administração". Cyrela e Even reprocessadas com o fix, ambas 100% dos cargos preenchidos corretamente.

---

## Dashboard de Governança (`src/dashboard_app.py`, iniciado 2026-08-04)

Primeira versão do dashboard interativo, construído em **Streamlit** (decisão registrada abaixo). Funcionalidades:
- Upload de PDF do FRE → detecção automática do capítulo 7 → parsing ao vivo → exibição da composição do Conselho/Diretoria/Comitês com tempo no cargo calculado
- Nome da empresa sugerido automaticamente a partir do cabeçalho do PDF (`extract_company_name`)
- **Mini currículos** (adicionado 2026-08-18): abaixo da tabela de cada órgão, um `st.expander` por membro com o texto de "Experiência Profissional" já extraído pelo parser (campo `experiencia_profissional`, existia desde o início mas não era exibido) + a profissão como legenda
- **Aba Remuneração** (adicionada 2026-08-18): ver seção própria "Remuneração qualitativa (capítulo 8)" abaixo
- Persistência simples em `data/dashboard_store.json` (gitignored — ver `.gitignore`, `*.json`) — trocar por banco de dados quando o BigQuery/CVM estiver resolvido
- Visão geral comparando todas as empresas já processadas

**Como rodar:** `venv\Scripts\streamlit.exe run src/dashboard_app.py`

**Decisão de arquitetura (Streamlit vs. Dash/deep-thought vs. React):** optamos por Streamlit pela velocidade de entrega, com o cuidado de manter toda a lógica de negócio (parsing, cálculo de tempo no cargo, agregação) em módulos Python puros (`fre_pdf_parser.py`, `dashboard_store.py`), separados da camada de apresentação. Isso deixa aberta a migração futura:
- **Para Dash** (convenção oficial da LEQ pra dashboards, ver skill `new-deepthought-dashboard`): reaproveita 100% da lógica, só reescreve a camada de apresentação
- **Para React**: os mesmos módulos virariam endpoints de uma API Flask — que já era o próximo passo planejado (item 8 da lista de próximos passos) independente do dashboard

**Testado:** preview local via browser, todas as abas. O upload real (clicar e selecionar arquivo no navegador) foi testado com sucesso pelo próprio usuário, sem necessidade de mais validação — processou a Even Construtora como 4ª empresa.

---

## Remuneração qualitativa — capítulo 8 do FRE (`parse_remuneracao_qualitativa`, 2026-08-18)

Diferente do capítulo 7 (tabelas estruturadas com colunas fixas), o **capítulo 8 (remuneração) é majoritariamente texto corrido**, que varia bastante de redação entre empresas — regex não consegue produzir uma resposta 100% confiável e estruturada aqui, ao contrário do que fizemos para a composição do Conselho/Diretoria. Por decisão explícita do usuário (perguntado antes de implementar), a abordagem escolhida foi: **extrair o texto relevante + sinalizar SIM/NÃO/A CONFIRMAR por palavra-chave**, deixando a confirmação final para leitura humana do texto extraído — não IA, não regex "definitivo".

**O que extrai:**
- **`find_remuneracao_page_range()`** — localiza as páginas do capítulo 8 (mesma técnica de `find_chapter7_page_range`: cabeçalho de seção na 2ª linha de cada página), de "8.1" até "8.5"
- **(a) Remuneração de longo prazo** (seção **8.4** "Plano de remuneração baseado em ações"): quando não há plano, a CVM usa um padrão de negação curto e consistente ("Não aplicável, tendo em vista que não há plano vigente...") — detectado via regex `_LONGO_PRAZO_NEGATIVO_RE`. Quando há plano, tenta identificar o tipo por palavra-chave (opções de compra de ações/stock options, ações restritas/RSU, phantom shares, matching de ações)
- **(b) Metas/indicadores na remuneração variável de curto prazo** (seção **8.1** "Política ou prática de remuneração", texto completo): sinaliza SIM se o texto menciona "indicador(es)", "metas individuais/estabelecidas/corporativas", "KPI" ou "critérios de desempenho" — mas **não tenta identificar quais são os indicadores especificamente**, isso normalmente não vem detalhado publicamente no FRE (validado na Cyrela: o texto diz "com base em indicadores previamente determinados pelo Conselho de Administração", sem nomear quais)

**Validado na Cyrela:** (a) NÃO — texto extraído confirma "não há plano vigente de remuneração baseada em ações" (bate com a tabela 8.5, que mostra 0% de remuneração baseada em ações); (b) SIM — menciona indicadores/metas.

**Integração no dashboard:** nova aba "Remuneração" por empresa, com indicador SIM/NÃO colorido + texto extraído das seções 8.1/8.4 num expander pra conferência humana. Falha nessa extração não bloqueia o resto do processamento (upload continua funcionando mesmo se o capítulo 8 não for encontrado — ex: FRE com numeração atípica).

**Limitação clara (por design, não bug):** isso é uma **triagem rápida por palavra-chave**, não uma classificação definitiva — sempre exige que o analista leia o texto extraído antes de usar a resposta. Ainda não testado contra outras empresas (BTG, Estapar, Even) — os PDFs originais precisam ser re-enviados pra validar a generalização, como fizemos com o capítulo 7.

---

## Remuneração quantitativa — seção 8.2 do FRE (`parse_remuneracao_valores`, 2026-08-18)

Complementa a extração qualitativa acima com dois aspectos **quantitativos**, pedidos pelo usuário: (a) composição % da remuneração total entre fixa/variável de curto prazo/variável de longo prazo, e (b) quadro com valores efetivos por órgão, estruturado pra permitir cálculo de % e de valor per capita.

**Diferente do capítulo 8.1/8.4 (texto corrido), a seção 8.2 "Remuneração total por órgão" é uma tabela numérica com layout consistente** entre empresas (exigido pelo Ofício-Circular/Anual da CVM/SEP) — por isso a extração aqui é **posicional**, igual à técnica usada no capítulo 7, não uma triagem por palavra-chave.

**O que extrai (`parse_remuneracao_valores`):**
- Localiza a seção 8.2 (dentro do intervalo já achado por `find_remuneracao_page_range`) e identifica os blocos por exercício social (normalmente 3-4 anos: o corrente previsto + últimos 2-3 realizados)
- Pra cada ano e cada órgão (Conselho de Administração, Diretoria Estatutária, Conselho Fiscal, Total): nº total de membros, nº de membros remunerados, e os componentes em R$ — salário/pró-labore, benefícios, participações em comitês, outros (fixos); bônus, participação de resultados, participação em reuniões, comissões, outros (variáveis); pós-emprego; cessação do cargo; remuneração baseada em ações; total
- Números em formato BR (`5.942.498,78`) convertidos pra float (`_br_to_float`)
- **Armadilha:** o rótulo "Outros" aparece 2x na tabela (uma vez em "Remuneração fixa anual", outra em "Remuneração variável") — resolvido pegando a 1ª e 2ª ocorrência na ordem em que aparecem no texto (`_parse_linhas_outros`). Outra armadilha: o rótulo "Baseada em ações **(incluindo** opções)" tem texto extra antes dos números (a continuação "opções)" quebra pra linha de baixo) — o gap entre rótulo e 1º número teve que virar `[^\d]*?` em vez de `\s+` estrito

**Cálculos derivados (feitos no dashboard, não no parser — dados brutos ficam disponíveis pra qualquer recorte):**
- (a) % = fixo/total, variável-curto/total, variável-longo/total, onde fixo = salário+benefícios+participações em comitês+outros(fixo); variável curto = bônus+participação de resultados+participação em reuniões+comissões+outros(variável); variável longo = remuneração baseada em ações
- (b) per capita = total da remuneração ÷ **nº de membros remunerados** (não o total, que pode incluir gente que não recebeu nada — usar "total" super-diluiria a média)

**Validado na Cyrela (4 exercícios: 2026 previsto, 2025, 2024, 2023):** Conselho de Administração = 100% fixo em todos os anos (bate com o texto da 8.1: "os membros do Conselho de Administração não farão jus ao recebimento de remuneração variável"); Diretoria Estatutária = ~24% fixo / ~76% variável curto prazo / 0% longo prazo em 2026, valores per capita na casa de R$ 5,75 milhões/ano — todos os valores conferidos manualmente contra o texto bruto do PDF, batendo exato.

**Integração no dashboard:** dentro da aba "Remuneração", uma nova seção "Valores quantitativos" no topo (antes dos "Aspectos qualitativos"), com uma tabela de composição % e uma tabela de valores/per capita por órgão (Conselho e Diretoria), uma por exercício social. Testado no navegador.

**Pendente:** testar contra BTG/Estapar/Even (PDFs precisam ser re-enviados) pra confirmar que o layout da tabela 8.2 é tão padronizado entre empresas quanto parece ser (é um formato exigido por ofício-circular da CVM, então a expectativa é alta, mas ainda não confirmada empiricamente como fizemos com o capítulo 7).

---

## Status do ambiente local (atualizado 2026-07-03)

- Repositório Git local inicializado, conectado ao remoto `https://github.com/bpereira1974/governanca-corporativa` (branch `main`). Push ainda não realizado — só local até confirmação explícita.
- Python 3.12.10 instalado (via winget, fonte oficial Python Software Foundation). Ambiente virtual em `venv/` na raiz do projeto (ignorado no Git), dependências do `requirements.txt` instaladas e testadas.
- `data/Template_Governança.xlsx` presente localmente (ignorado no Git — nunca commitar planilhas com dados).
- `main.py` roda com sucesso via `venv\Scripts\python.exe src\main.py`.
