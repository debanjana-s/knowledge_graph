# GraphRAG for Oral Cancer Knowledge Graph

A Neo4j‑based GraphRAG system for oral cancer clinical decision support. It acts as the evidence engine for the orchestrator, providing structured, citation‑backed facts when the medical LLM's confidence is low.

It bridges the gap between the orchestrator's low‑confidence state and the Knowledge Graph by:

Retrieving structured evidence from Neo4j – gene roles, tissues, mutation types, syndromes, ClinVar‑annotated mutations, disease associations (from COSMIC), and literature‑mined gene‑cancer roles with citation counts (from CancerMine).

Scoring evidence objectively using COSMIC Tiers, ClinVar classifications, and CancerMine citation counts.

Formatting the evidence into a bulleted, numbered context string that the orchestrator can directly paste into the augmented prompt.

This builds a knowledge graph that integrates COSMIC Gene Census, COSMIC Mutation Census, CancerMine , and HeNeCOn (Head and Neck Cancer Ontology). It exposes a simple REST API that the orchestrator calls when confidence is low, returning evidence snippets with relevance scores and a formatted context string ready for LLM ingestion.


## Repository Structure

```
graphrag/
├── app.py                     # Flask API
├── neo4j_retriever.py         # Cypher queries
├── organizer.py               # Evidence formatting + scoring
├── requirements.txt           # Dependencies
├── .env.example               # Environment template
└── orchestrator_adapter.py    # HTTP client for orchestrator integration

knowledge_graph/
├── import_cancermine.py
├── import_henecon.py
├── import_gene_census.py
└── import_mutation_census.py
```

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Neo4j | Running with the database populated. |
| Dependencies | See `requirements.txt`. |

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/debanjana-s/knowledge_graph.git
cd graphrag
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=cosmicmutationhenecon
GRAPH_RAG_PORT=5000

```

### 3. Run the Service

```bash
python app.py
```

Service available at: `http://127.0.0.1:5000`

## API Endpoints

### GET /health

Check service and Neo4j connectivity.

**Response:**

```json
{"status": "ready", "neo4j": "connected"}
```

### POST /retrieve

Retrieve evidence for a set of genes.

**Request:**

```json
{
  "patient_context": {
    "genes": [{"symbol": "TP53"}],
    "tumor_type": "HNSCC"
  },
  "top_k": 5
}
```

## Evidence Scoring

| Evidence Type | Score | Basis |
|---------------|-------|-------|
| COSMIC Gene Census | 1.0 | Expert-curated Tier 1 |
| COSMIC Mutation (Pathogenic) | 1.0 | ClinVar classification |
| COSMIC Mutation (Likely Pathogenic) | 0.8 | ClinVar classification |
| CancerMine (≥100 citations) | 1.0 | Literature support |
| CancerMine (≥50 citations) | 0.85 | Literature support |
| CancerMine (≥20 citations) | 0.70 | Literature support |

## Data Sources

| Source | Data |
|--------|------|
| COSMIC | Gene Census (roles, tissues, mutation types) & Mutation Census (ClinVar) |
| CancerMine | Literature-mined gene-disease roles with citation counts |
| HeNeCOn | Head and Neck Cancer Ontology (staging, pathology, treatments) |
