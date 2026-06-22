#!/usr/bin/env python3
#HTTP client for GraphRAG service.

import os
import requests
import logging

logger = logging.getLogger(__name__)

class Neo4jGraphRAGClient:
    def __init__(self, base_url=None):
        self.base_url = base_url or os.environ.get('GRAPH_RAG_URL', 'http://localhost:5000')
        self.timeout = 10

    def is_ready(self):
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=2)
            return resp.status_code == 200 and resp.json().get('status') == 'ready'
        except Exception:
            return False

    def retrieve(self, query, patient_context, top_k=5):
        payload = {
            "query": query,
            "patient_context": patient_context,
            "top_k": top_k
        }
        try:
            resp = requests.post(f"{self.base_url}/retrieve", json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('retrievals', [])
            else:
                logger.error(f"GraphRAG service returned {resp.status_code}: {resp.text}")
                return []
        except Exception as e:
            logger.exception("GraphRAG retrieve failed")
            return []

    def format_context(self, retrievals):
        if not retrievals:
            return "_No relevant medical evidence retrieved._"
        lines = []
        for i, r in enumerate(retrievals, 1):
            ev = f" [evidence {r['evidence_level']}]" if r.get("evidence_level") else ""
            lines.append(f"{i}. ({r['source']}{ev}, relevance {r.get('relevance_score', 0):.2f}) {r['content']}")
        return "\n".join(lines)