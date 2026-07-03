# CONTEXT.md — Motor de Governança Corporativa
> Documento de contexto do projeto. Atualizar sempre que houver decisões relevantes.
> Ao abrir o Claude Code, começar com: "leia o CONTEXT.md antes de qualquer coisa".

---

## O que é esse projeto

Ferramenta para avaliação e ranking de governança corporativa de empresas brasileiras listadas na B3. Dado um conjunto de campos sobre uma empresa, o motor calcula uma nota de 0 a 100 distribuída em 5 blocos. O objetivo final é que o analista possa avaliar uma nova empresa combinando:
1. Dados buscados automaticamente no BigQuery (CVM/FRE)
2. Campos preenchidos manualmente pelo analista (critérios qualitativos)
3. Dados extraídos do estatuto social (cláusulas específicas)

---

## Arquitetura atual (Python puro — fase 1)

```
governanca-corporativa/
├── src/
│   ├── main.py               # Entrypoint: roda avaliação completa e exibe ranking
│   ├── scoring_engine.py     # Motor de cálculo de notas por bloco
│   ├── parser_planilha.py    # Lê Template_Governança.xlsx e extrai dados das empresas
│   └── utils/
│       └── logging_utils.py  # Logger estruturado padrão LEQ (custom_log)
├── configs/
│   └── config.py             # Todas as regras de pontuação (pesos, tabelas de conversão)
├── tests/
├── data/
│   └── Template_Governança.xlsx   # Planilha com critérios e 10 empresas de exemplo
├── CONTEXT.md                # Este arquivo
├── requirements.txt          # pandas==3.0.2, openpyxl==3.1.5, python-dotenv==1.0.1
├── .env.example
└── .gitignore
```

**Próximas fases planejadas (ainda não implementadas):**
- API Flask (Cloud Run) — expor o motor como endpoint HTTP
- MCP Server — ferramentas para o Claude usar diretamente
- Módulo BigQuery — buscar dados do FRE automaticamente
- Dashboard React — interface visual para analistas

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

## Tabelas do BigQuery (a mapear)

Quando houver acesso ao BigQuery, as tabelas do FRE provavelmente seguem o padrão `fre_cia_aberta_*`. Seções prioritárias:
- Seção 6.1/2 → tabela de posição acionária
- Seção 1.13 → tabela de acordos de acionistas
- Seção 7.1D → tabela de composição dos órgãos
- Seção 7.3 → tabela de membros da administração
- Seção 7.4 → tabela de composição dos comitês

**Pendente:** confirmar nomes exatos das tabelas. Consultar a skill `leblon-bigquery` antes de qualquer query.

---

## Padrões de código (LEQ)

- **Sempre consultar** a skill `leq-code-standards` antes de criar qualquer arquivo novo
- Logger: usar `custom_log` de `src/utils/logging_utils.py` — nunca `print()` para mensagens operacionais
- Credenciais: nunca no repo — usar `GOOGLE_APPLICATION_CREDENTIALS` via env var
- Dependências: sempre com versão fixada no `requirements.txt`
- Deploy futuro: Cloud Run, região `southamerica-east1`, `--min-instances 0`

---

## Próximos passos (ordem sugerida)

1. **Mapear tabelas do BigQuery** — identificar nomes exatos das tabelas do FRE para as seções 6 e 7
2. **Módulo `bq_client.py`** — função que dado um ticker/CNPJ busca os campos automáticos no BigQuery
3. **Interface de input manual** — formulário para o analista preencher os campos qualitativos
4. **Módulo `estatuto_parser.py`** — usar Claude API para ler estatuto em PDF e extrair campos booleanos
5. **Integrar tudo em `main.py`** — pipeline completo: BigQuery + input manual + estatuto → nota final
6. **API Flask** — expor o motor como endpoint HTTP
7. **MCP Server** — ferramentas para o Claude usar diretamente
8. **Dashboard React** — interface visual para analistas
