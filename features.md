---
title: AnswerLayer Features
date: March 2026
version: 1.0
---

# AnswerLayer Features

AnswerLayer transforms how teams interact with their data with it's generative semantic layer and conversational analytics.

---

## Natural Language Query Engine

Enables access to accurate analytics through everyday language.

### How It Works

When data is requested, AnswerLayer reasons about your data. It uses your semantic layer as context: what tables exist, how they connect, what each column means in business terms, and how to calculate know metrics properly. This grounding means the produces results that respect your model of the data.

### Verifiable References

Answers include deterministic references back to the source data. Users can click through to see the underlying data, verify the numbers, and explore further. This closes the loop between insight and evidence, giving teams confidence in AI-generated analytics.

---

## Semantic Layer

The semantic layer bridges raw tables and business concepts, ensuring everyone speaks the same language. It's the map of what exists in the data.

### AI-Powered Generation

Point AnswerLayer at your database and it analyzes actual data to build:

- **Entities** — Core business objects (customers, orders, products)
- **Relationships** — How entities connect, with cardinality (1:1, 1:N, N:N)
- **Measures** — Aggregatable values (revenue, quantity, duration)
- **Metrics** — Calculated KPIs with business logic baked in
- **Dimensions** — Attributes for slicing and filtering
- **Filters** — Pre-built constraints for common queries

---

## Data Security & Privacy

Enterprise-grade protection at every layer. AnswerLayer is built for teams that take data governance seriously.

### Intelligent PII Detection

AnswerLayer scans database schema and metatdata to identify sensitive information:

| Category | Examples |
|----------|----------|
| Personal Identity | Names, dates of birth, gender |
| Contact Information | Email, phone, address |
| Financial | Credit cards, bank accounts, SSN |
| Biometric | Fingerprints, facial recognition data |
| Government IDs | Passport numbers, driver's licenses |

Each detection includes a **confidence score (0-100%)** so you can prioritize review. Columns flagged at PII are automatically blocked so query agents will have no knowledge of them.

### Column-Level Controls

For every column, choose how AnswerLayer handles the data:

- **Block** — Column is invisible to the query engine
- **Allow** — Full access for authorized users

### Defense in Depth

> All credentials encrypted at rest. All connections use SSL/TLS.

---

## API & Integration

Build AnswerLayer into your workflows with a comprehensive REST API.

### Authentication & Access

**Clerk-based auth** supports email/password and OAuth providers. Organize users into **organizations** with role-based access control.

---

# Roadmap

What's next for AnswerLayer.

## Evaluation & Quality Framework

The semantic layer is the key to accurate, efficient answers. Evaluations let you tune it systematically—improving correctness while reducing the tokens needed to generate each query.

| Feature | Description |
|---------|-------------|
| Test cases | Define expected outputs for known queries |
| Evaluation runs | Compare results across semantic layer versions |
| Quality dashboards | Track accuracy trends over time |
| AI-assisted generation | Automatically suggest test cases from query history |
| Model ablation | Compare Haiku vs. Sonnet vs. Opus performance on your data |

The goal: a self-improving loop that becomes more accurate and more efficient over time.

## MCP Integration

Model Context Protocol support for both semantic layer curators and data inquirers—connect AnswerLayer to your existing AI workflows and tools.

## Sharing & Export

- **Report sharing** — Share results with teammates via link or scheduled delivery
- **Data export** — Download query results as CSV, Excel, or JSON
- **Report export** — Generate PDF reports for stakeholders

---
