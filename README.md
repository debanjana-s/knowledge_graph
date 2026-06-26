# GraphRAG for Oral Cancer Knowledge Graph

A Neo4j-based Graph Retrieval-Augmented Generation service for oral cancer clinical decision support.

It retrieves structured biomedical evidence from a Neo4j knowledge graph, re-ranks it using a cross-encoder, and returns concise, citation-backed evidences. It is designed to serve as the retrieval engine for the orchestrator, providing additional knowledge whenever the medical LLM's confidence is low.

---

## Features

* Retrieve structured biomedical evidence from a Neo4j knowledge graph
* Query multiple evidence sources simultaneously:

  * COSMIC Gene Census
  * COSMIC Mutation Census
  * CancerMine
  * HeNeCOn ontology
* Re-rank retrieved evidence using the MS MARCO MiniLM Cross Encoder
* Aggregate redundant evidence into concise gene–disease summaries
* REST API for seamless integration with external orchestration systems
* Returns both ranked evidence and an LLM-ready context paragraph

---

## Repository Structure

```text
graphrag/
├── app.py                     # Flask REST API
├── neo4j_retriever.py         # Cypher retrieval layer
├── organizer.py               # Re-ranking & aggregation
├── orchestrator_adapter.py    # Client used by the orchestrator
├── requirements.txt
└── .env.example

knowledge_graph/
├── import_cancermine.py
├── import_henecon.py
├── import_gene_census.py
└── import_mutation_census.py
```

---


## Prerequisites

| Requirement  | Version                         |
| ------------ | ------------------------------- |
| Python       | 3.9+                            |
| Neo4j        | Running with populated database |
| Dependencies | `requirements.txt`              |

The Neo4j database should already contain data imported from:

* COSMIC Gene Census
* COSMIC Mutation Census
* CancerMine
* HeNeCOn

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/debanjana-s/knowledge_graph.git
cd graphrag
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example configuration.

```bash
cp .env.example .env
```

---

## Running the Service

```bash
python app.py
```

The API will be available at

```
http://127.0.0.1:5000
```

---

## API

### Health Check

#### GET `/health`

Checks service readiness and Neo4j connectivity.

#### Response

```json
{
  "status": "ready",
  "neo4j": "connected"
}
```

---

### Retrieve Evidence

#### POST `/retrieve`

Retrieves and re-ranks evidence for the supplied patient context.

#### Request

```json
{
  "patient_context": {
    "genes": [
      {"symbol": "TP53"},
      {"symbol": "EGFR"}
    ],
    "tumor_type": "HNSCC"
  },
  "query": "Explain why this patient is predicted to have oral cancer.",
  "top_k": 5
}
```

#### Parameters

| Field                      | Description                        |
| -------------------------- | ---------------------------------- |
| patient_context.genes      | List of gene symbols               |
| patient_context.tumor_type | Primary tumour site                |
| query                      | Question from the orchestrator     |
| top_k                      | Number of evidence items to return |

#### Response

```json
{
  "retrievals": [
    {
      "gene": "TP53",
      "target_name": "head and neck squamous cell carcinoma",
      "type": "cancermine",
      "score": 1.88,
      "citations": 54,
      "role": "tumor suppressor"
    }
  ],
  "kg_summary": "The following evidence supports..."
}
```

---

## Retrieval Pipeline

### 1. Neo4j Retrieval

The retriever gathers all available evidence for the supplied genes.

Retrieved information includes:

* Gene roles
* Associated tissues
* Mutation types
* Syndromes
* COSMIC disease associations
* CancerMine gene–disease relationships
* ClinVar mutation annotations

CancerMine associations are prioritised by:

1. Head and Neck Cancer entries
2. Citation count
3. Remaining diseases

---

### 2. Query Enrichment

Before re-ranking, the original query is expanded with patient-specific context.

---

### 3. Cross-Encoder Re-ranking

Each retrieved evidence item is converted into a natural language passage.


All passages are scored using

```
cross-encoder/ms-marco-MiniLM-L-6-v2
```

against the enriched query.

---

### 4. Evidence Aggregation

The highest-ranked evidence is grouped by

```
(Gene, Disease)
```

Multiple roles and citation counts are merged into a single concise statement to reduce redundancy while preserving supporting evidence.

---

## Knowledge Graph Sources

| Source                 | Data                                           | Relationships                                            |
| ---------------------- | ---------------------------------------------- | -------------------------------------------------------- |
| COSMIC Gene Census     | Gene roles, tissues, mutation types, syndromes | HAS_ROLE, HAS_TISSUE, HAS_MUTATION_TYPE, ASSOCIATED_WITH |
| COSMIC Mutation Census | Mutations, ClinVar significance, diseases      | HAS_MUTATION, ASSOCIATED_WITH                            |
| CancerMine             | Gene–disease roles with citation counts        | IS_ONCOGENE_IN, IS_DRIVER_IN, IS_TUMOR_SUPPRESSOR_IN     |
| HeNeCOn                | Oral cancer ontology                           | SUBCLASS_OF                                              |

---


## Output


* retrievals – ranked individual evidence items
* kg_summary – aggregated evidence formatted as a compact paragraph ready for LLM ingestion

The GraphRAG service is intended to operate as the evidence retrieval component of a larger multi-agent medical reasoning pipeline, supplying structured, citation-backed knowledge whenever additional clinical evidence is required.
