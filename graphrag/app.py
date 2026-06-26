
#!/usr/bin/env python3
#GraphRAG Microservice - Flask API for orchestrator integration.

import os
import re
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from neo4j_retriever import Neo4jRetriever
from organizer import Organizer

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

retriever = None
organizer = None

def get_retriever():
    global retriever
    if retriever is None:
        retriever = Neo4jRetriever()
    return retriever

def get_organizer():
    global organizer
    if organizer is None:
        organizer = Organizer()
    return organizer

@app.route('/health', methods=['GET'])
def health():
    try:
        r = get_retriever()
        if r.test_connection():
            return jsonify({"status": "ready", "neo4j": "connected"})
        else:
            return jsonify({"status": "degraded", "neo4j": "disconnected"}), 503
    except Exception as e:
        logger.exception("Health check failed")
        return jsonify({"status": "error", "detail": str(e)}), 500

@app.route('/retrieve', methods=['POST'])
def retrieve():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing JSON body"}), 400

        query = data.get('query', '')
        patient_context = data.get('patient_context', {})
        tumor_type = patient_context.get('tumor_type', None)
        top_k = data.get('top_k', None)

        gene_symbols = []
        for g in patient_context.get('genes', []):
            sym = g.get('symbol')
            if sym:
                gene_symbols.append(sym)

        if not gene_symbols and query:
            found = re.findall(r'\b[A-Z][A-Z0-9]{1,8}\b', query)
            gene_symbols = list(set(found))

        if not gene_symbols:
            return jsonify({
                "retrievals": [],
                "kg_summary": "_No genes provided in patient context or query._"
            }), 200

        ret = get_retriever()
        raw_results = ret.retrieve_for_genes(gene_symbols, tumor_type=tumor_type, max_ancestors=3)

        org = get_organizer()

        # Build rich query for cross-encoder
        rich_query = query
        if gene_symbols:
            rich_query += f" Patient genes: {', '.join(gene_symbols)}."
        if tumor_type:
            rich_query += f" Tumor type: {tumor_type}."

        retrievals, kg_summary = org.format_retrievals(
            raw_results, query=rich_query, tumor_type=tumor_type, top_k=top_k
        )

        # Return retrievals and kg_summary
        return jsonify({
            "retrievals": retrievals,
            "kg_summary": kg_summary
        }), 200

    except Exception as e:
        logger.exception("Error in /retrieve")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('GRAPH_RAG_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)