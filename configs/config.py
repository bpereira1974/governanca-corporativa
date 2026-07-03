# configs/config.py
# Configurações e regras de pontuação extraídas da planilha Template_Governança.xlsx

TEMPLATE_PATH = "data/Template_Governança.xlsx"

# Pesos de cada bloco na nota final (total = 100)
# Regra: nota bruta = nota ponderada (peso de cada bloco = seu máximo de pontos brutos)
PESOS_BLOCOS = {
    "segmento_listagem": 10,
    "direitos_acionistas": 10,
    "estrutura_acionaria": 20,
    "conselho_administracao": 30,
    "diretoria": 20,
}

# --- SEGMENTO DE LISTAGEM ---
# Nota máxima: 10
NOTAS_SEGMENTO = {
    "Novo Mercado": 10,
    "Nível 2": 8,
    "Nível 1": 5,
    "Básico": 4,
    "Cayman dual-class": 6,
}
# Mitigadores de tag along (inferidos do campo Comentário)
# São aplicados quando o segmento não é Novo Mercado
# Lógica: buscar "80%" + "PN" e/ou "100%" + "ON" no comentário
# "2 classes" + "PN" → nota 6 (BTG style)
# tag_along_pn + tag_along_on → 7
# apenas um deles → 6

# --- DIREITOS DOS ACIONISTAS ---
# Nota base pelo Conselho Fiscal
NOTAS_CONSELHO_FISCAL = {
    "permanente": 10,
    "instalado": 8,
    "nao_instalado": 6,
}
# Penalidades (subtraem da nota base)
PENALIDADES_DIREITOS = {
    "poison_pill": -1,
    "poison_pill_threshold_baixo": -0.5,  # threshold <= 20%
    "limite_voto": -1,
    "limite_dividendo": -1,
}

# --- ESTRUTURA ACIONÁRIA ---
# Nota máxima bruta: 4+3+6+3+2+2 = 20 (= peso do bloco, sem normalização)
# (A) Natureza da estrutura — comparação case-insensitive
NOTAS_NATUREZA_ESTRUTURA = {
    "corporation": 4,
    "controle privado": 4,
    "controle estatal": 1,
}
# (B) Participação do controlador no capital total
# Corporation/sem controlador: 3pts (neutro/positivo — não há concentração)
NOTAS_PARTICIPACAO_CONTROLADOR = {
    "abaixo_40": 1,   # < 40%
    "acima_40": 3,    # >= 40%
    "sem_controlador": 3,  # corporation
}
# (C) Visão sobre o acionista controlador
# N/A (corporation sem controlador): 3pts (neutro, equivalente a Mixed)
NOTAS_VISAO_CONTROLADOR = {
    "Positiva": 6,
    "Mixed": 3,
    "Negativa": 0,
    "N/A": 3,  # corporation — neutro
}
# (D) % Insiders' ownership
NOTAS_INSIDERS = {
    "abaixo_5": 1,    # < 5%
    "entre_5_10": 2,  # >= 5% e < 10%
    "acima_10": 3,    # >= 10%
}
# (E) Potencial conflito de interesses
NOTAS_CONFLITO = {
    "Baixo": 2,
    "Médio": 1,
    "Alto": 0,
}
# (F) Transações com partes relacionadas relevantes
NOTAS_PARTES_RELACIONADAS = {
    "Sim": 0,
    "Não": 2,
}

# --- CONSELHO DE ADMINISTRAÇÃO ---
# Nota máxima bruta: 10 + 20 = 30 (= peso do bloco, sem normalização)

# (A) Estrutura: número de membros → nota 1/2/3 → pontos fixos
NOTA_ESTRUTURA_POR_MEMBROS = {
    7: 3, 9: 3,   # ideal
    6: 2, 8: 2,   # razoável
}
NOTA_ESTRUTURA_DEFAULT = 1  # 5 ou menos, 10 ou mais
# Conversão nota 1/2/3 → pontos
NOTAS_ESTRUTURA_CONSELHO_PTS = {1: 2, 2: 6, 3: 10}

# (B) Qualidade e diversidade (nota subjetiva 1–5) → pontos
NOTAS_QUALIDADE_CONSELHO = {
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    5: 20,
}

# --- DIRETORIA ---
# Nota máxima bruta: 10+2+2+2+2+2 = 20 (= peso do bloco, sem normalização)

# (A) Qualidade e diversidade (nota subjetiva 1–5) → pontos
NOTAS_QUALIDADE_DIRETORIA = {
    1: 2,
    2: 4,
    3: 6,
    4: 8,
    5: 10,
}
# (B) % Remuneração Fixa da Diretoria
# ATENÇÃO: usar a 2ª ocorrência de '% Remuneração Fixa / Total' na planilha
# (a 1ª é do Conselho de Administração)
NOTAS_REM_FIXA = {
    "acima_50": 0,    # >= 50% fixa → menos alinhamento com resultado → 0pts
    "abaixo_50": 2,   # < 50% fixa → maior componente variável → 2pts
}
# (C) Transparência na remuneração variável de CP
NOTAS_TRANSPARENCIA_REM = {
    "Sim": 2,
    "Não": 0,
}
# (D) Práticas contábeis agressivas
NOTAS_PRATICAS_CONTABEIS = {
    "Sim": 0,
    "Não": 2,
}
# (E) Contingências relevantes
NOTAS_CONTINGENCIAS = {
    "Sim": 0,
    "Não": 2,
}
# (F) Relatório de sustentabilidade
NOTAS_SUSTENTABILIDADE = {
    "Sim": 2,
    "Não": 0,
}
