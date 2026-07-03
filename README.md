# Governança Corporativa — Motor de Scoring

Ferramenta para avaliação e ranking de governança corporativa de empresas brasileiras listadas na B3.

## Estrutura

```
governanca-corporativa/
├── src/
│   ├── main.py               # Entrypoint
│   ├── scoring_engine.py     # Motor de cálculo de notas por bloco
│   ├── parser_planilha.py    # Lê a planilha .xlsx e extrai dados
│   └── utils/
│       └── logging_utils.py  # Logger estruturado (GCP Cloud Logging)
├── configs/
│   └── config.py             # Regras de pontuação
├── data/                     # Planilha de template (não versionada)
├── CONTEXT.md                # Contexto completo do projeto — ler primeiro
├── requirements.txt
└── .gitignore
```

## Como rodar

```bash
pip install -r requirements.txt
cp Template_Governança.xlsx data/
python src/main.py
```

## Contexto completo

Leia o `CONTEXT.md` para entender a arquitetura, decisões de design, mapeamento do FRE e próximos passos.
