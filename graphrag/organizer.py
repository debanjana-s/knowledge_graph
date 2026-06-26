
#!/usr/bin/env python3
#Organizer: converts raw Neo4j data into evidence using cross-encoder re-ranking,

import os
import logging
from sentence_transformers import CrossEncoder
from ollama import Client

logger = logging.getLogger(__name__)

# ========== Config from environment ==========
RERANK_TOP_K = int(os.environ.get('RERANK_TOP_K', 15))
CROSS_ENCODER_BATCH_SIZE = int(os.environ.get('CROSS_ENCODER_BATCH_SIZE', 16))
CROSS_ENCODER_MODEL = os.environ.get('CROSS_ENCODER_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2')


_cross_encoder = None

def get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        logger.info(f"Loading cross-encoder: {CROSS_ENCODER_MODEL}")
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
        logger.info("Cross-encoder loaded.")
    return _cross_encoder

class Organizer:

    @staticmethod
    def _build_item_passage(item, gene_desc):
        """Build a text passage for a single evidence item."""
        symbol = item["gene"]
        target = item["target_name"]
        item_type = item["type"]

        if item_type == "gene_level":
            role_str = ", ".join(item.get("roles", [])) if item.get("roles") else "unknown role"
            tissue_str = ", ".join(item.get("tissues", [])) if item.get("tissues") else "various tissues"
            mut_type_str = ", ".join(item.get("mutation_types", [])) if item.get("mutation_types") else "various mutation types"
            syndrome_str = ", ".join(item.get("syndromes", [])) if item.get("syndromes") else "none reported"
            passage = f"Gene {symbol}. Roles: {role_str}. Tissues: {tissue_str}. Mutation types: {mut_type_str}. Syndromes: {syndrome_str}."
            if gene_desc:
                passage = gene_desc + ". " + passage
            return passage

        elif item_type == "mutation":
            aa = item.get("aa_change", "unknown")
            clinvar = item.get("clinvar", "")
            if clinvar:
                return f"Gene {symbol} has mutation {aa} (ClinVar: {clinvar})."
            else:
                return f"Gene {symbol} has mutation {aa}."

        elif item_type == "cosmic_disease":
            disease = item["target_name"]
            return f"Gene {symbol} is associated with {disease} (COSMIC)."

        elif item_type == "cancermine":
            disease = item["target_name"]
            role = item.get("role", "associated")
            citations = item.get("citations", 0)
            return f"Gene {symbol} is reported as a {role} in {disease} ({citations} citations)."

        return f"{symbol} -> {target}"

    @staticmethod
    def _flatten_items(genes_data):
        """Flatten raw gene data into a list of evidence items with passages."""
        items = []
        for gene in genes_data:
            symbol = gene.get("symbol", "Unknown")
            gene_desc = gene.get("gene_desc", "")
            roles = gene.get("roles", [])
            tissues = gene.get("tissues", [])
            mut_types = gene.get("mutation_types", [])
            syndromes = gene.get("syndromes", [])
            mutations = gene.get("mutations", [])
            cosmic_diseases = gene.get("cosmic_diseases", [])
            cancermine_diseases = gene.get("cancermine_diseases", [])

            # Gene-level
            item = {
                "gene": symbol,
                "gene_desc": gene_desc,
                "target_name": "gene_level",
                "type": "gene_level",
                "roles": roles,
                "tissues": tissues,
                "mutation_types": mut_types,
                "syndromes": syndromes,
                "score": None,
            }
            item["passage"] = Organizer._build_item_passage(item, gene_desc)
            items.append(item)

            # COSMIC diseases
            for disease in cosmic_diseases:
                item = {
                    "gene": symbol,
                    "gene_desc": gene_desc,
                    "target_name": disease,
                    "type": "cosmic_disease",
                    "metadata": "COSMIC",
                    "score": None,
                }
                item["passage"] = Organizer._build_item_passage(item, gene_desc)
                items.append(item)

            # Mutations
            for mut in mutations:
                item = {
                    "gene": symbol,
                    "gene_desc": gene_desc,
                    "target_name": mut.get("aa_change", "unknown"),
                    "type": "mutation",
                    "aa_change": mut.get("aa_change", "unknown"),
                    "clinvar": mut.get("clinvar", ""),
                    "cds_change": mut.get("cds_change", ""),
                    "score": None,
                }
                item["passage"] = Organizer._build_item_passage(item, gene_desc)
                items.append(item)

            # CancerMine
            for cm in cancermine_diseases:
                role_pretty = {
                    "IS_ONCOGENE_IN": "oncogene",
                    "IS_TUMOR_SUPPRESSOR_IN": "tumor suppressor",
                    "IS_DRIVER_IN": "driver"
                }.get(cm["role"], cm["role"])
                item = {
                    "gene": symbol,
                    "gene_desc": gene_desc,
                    "target_name": cm["name"],
                    "type": "cancermine",
                    "role": role_pretty,
                    "citations": cm["citations"],
                    "score": None,
                }
                item["passage"] = Organizer._build_item_passage(item, gene_desc)
                items.append(item)

        return items

    @staticmethod
    def _clean_item(item):
        """Return a clean version of an item (remove bulky fields)."""
        cleaned = {
            "gene": item.get("gene"),
            "target_name": item.get("target_name"),
            "type": item.get("type"),
            "score": item.get("score"),
        }
        if "citations" in item:
            cleaned["citations"] = item["citations"]
        if "role" in item:
            cleaned["role"] = item["role"]
        if "clinvar" in item:
            cleaned["clinvar"] = item["clinvar"]
        if "aa_change" in item:
            cleaned["aa_change"] = item["aa_change"]
        return cleaned

    @staticmethod
    def _aggregate_items(items):
        """
        Aggregate items by (gene, target_name).
        For each group, collect roles/citations and COSMIC flags.
        Returns a list of dicts with keys: gene, disease, roles (list of {role, citations}), cosmic (bool).
        """
        groups = {}
        for item in items:
            # Skip gene-level and mutation items for aggregation
            if item["type"] in ["gene_level", "mutation"]:
                continue
            key = (item["gene"], item["target_name"])
            if key not in groups:
                groups[key] = {
                    "gene": item["gene"],
                    "disease": item["target_name"],
                    "roles": [],
                    "cosmic": False
                }
            if item["type"] == "cancermine":
                groups[key]["roles"].append({
                    "role": item.get("role", "associated"),
                    "citations": item.get("citations", 0)
                })
            elif item["type"] == "cosmic_disease":
                groups[key]["cosmic"] = True

        # Convert to list and sort by gene, then disease
        aggregated = list(groups.values())
        aggregated.sort(key=lambda x: (x["gene"], x["disease"]))
        return aggregated

    @staticmethod
    def _build_aggregated_text(aggregated, genes_data, tumor_type):
        """Build a text block from aggregated evidence for LLM prompt."""
        lines = []
        for group in aggregated:
            gene = group["gene"]
            disease = group["disease"]
            roles = group["roles"]
            cosmic = group["cosmic"]

            # Get gene roles from raw data
            gene_data = next((g for g in genes_data if g["symbol"] == gene), {})
            gene_role_str = ", ".join(gene_data.get("roles", [])) if gene_data.get("roles") else "unknown role"

            role_strs = []
            for r in roles:
                role_strs.append(f"{r['role']} ({r['citations']} citations)")
            if cosmic:
                role_strs.append("COSMIC association")

            if role_strs:
                line = f"Gene {gene} ({gene_role_str}) associated with {disease} as {', '.join(role_strs)}"
            else:
                line = f"Gene {gene} ({gene_role_str}) associated with {disease}"
            lines.append(line)

        # Add tumor type context
        context = f"Patient has tumor type: {tumor_type if tumor_type else 'not specified'}.\n"
        return context + "\n".join(lines)

    @staticmethod
    def _generate_llm_summary(aggregated_text, tumor_type, query):
        """Call Ollama to generate a clinical summary from aggregated evidence."""
        # Read LLM settings at runtime (after .env is loaded)
        enable_llm = os.environ.get('ENABLE_LLM_SUMMARY', 'false').lower() == 'true'
        if not enable_llm:
            logger.info("LLM summary disabled (ENABLE_LLM_SUMMARY=false)")
            return None

        host = os.environ.get('OLLAMA_HOST', 'http://10.5.30.32:11434')
        model = os.environ.get('OLLAMA_MODEL', 'gemma4:12b')
        timeout = int(os.environ.get('OLLAMA_TIMEOUT', 30))

        logger.info(f"Attempting LLM summary with host={host}, model={model}")

        prompt = f"""You are a clinical oncologist. Based on the following aggregated evidence for a patient with {tumor_type if tumor_type else 'head and neck cancer'}, summarise the key molecular findings in 2–3 sentences that are clinically relevant. Do not add new facts; only synthesise what is given.

Evidence:
{aggregated_text}

Summary:"""

        try:
            client = Client(host=host, timeout=timeout)
            response = client.chat(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.3, 'max_tokens': 150}
            )
            if response and response.message and response.message.content:
                return response.message.content.strip()
            else:
                logger.warning("LLM response had no content.")
                return None
        except Exception as e:
            logger.error(f"Ollama LLM call failed: {e}")
            return None

    @staticmethod
    def _build_template_summary(aggregated, genes_data):
        """Fallback: template-based summary from aggregated data."""
        if not aggregated:
            return "_No relevant medical evidence retrieved._"

        sentences = []
        for group in aggregated:
            gene = group["gene"]
            disease = group["disease"]
            roles = group["roles"]
            cosmic = group["cosmic"]

            gene_data = next((g for g in genes_data if g["symbol"] == gene), {})
            gene_role_str = ", ".join(gene_data.get("roles", [])) if gene_data.get("roles") else "unknown role"

            role_strs = []
            for r in roles:
                role_strs.append(f"{r['role']} ({r['citations']} citations)")
            if cosmic:
                role_strs.append("COSMIC")

            if role_strs:
                sentences.append(f"Gene {gene} ({gene_role_str}) associated with {disease} as {', '.join(role_strs)}")
            else:
                sentences.append(f"Gene {gene} ({gene_role_str}) associated with {disease}")

        return "The following evidence supports the prediction: " + ". ".join(sentences) + "."

    @staticmethod
    def format_retrievals(raw_data, query, tumor_type=None, top_k=None):
        """
        Transform raw Neo4j output into re-ranked, aggregated evidence.
        Returns: (retrievals, kg_summary)
        """
        genes_data = raw_data.get("genes", [])
        if not genes_data:
            return [], "_No relevant medical evidence retrieved."

        # Flatten into evidence items
        items = Organizer._flatten_items(genes_data)
        if not items:
            return [], "_No relevant medical evidence retrieved."

        # Re-rank with cross-encoder
        cross_encoder = get_cross_encoder()
        query_pairs = [(query, item["passage"]) for item in items]

        scores = []
        for i in range(0, len(query_pairs), CROSS_ENCODER_BATCH_SIZE):
            batch = query_pairs[i:i + CROSS_ENCODER_BATCH_SIZE]
            batch_scores = cross_encoder.predict(batch, convert_to_tensor=False)
            if isinstance(batch_scores, (int, float)):
                batch_scores = [batch_scores]
            scores.extend(batch_scores)

        for idx, item in enumerate(items):
            item["score"] = float(scores[idx])

        sorted_items = sorted(items, key=lambda x: x["score"], reverse=True)

        # Candidate pool size
        candidate_limit = RERANK_TOP_K
        candidate_items = sorted_items[:candidate_limit]

        # Output limit from request (top_k)
        if top_k is not None and top_k > 0:
            output_limit = min(top_k, len(candidate_items))
        else:
            output_limit = candidate_limit

        # Take top items for retrieval list
        top_items = candidate_items[:output_limit]

        # Clean retrieval items
        cleaned_retrievals = []
        for item in top_items:
            cleaned = Organizer._clean_item(item)
            cleaned_retrievals.append(cleaned)

        # Remove duplicates
        seen = set()
        unique_retrievals = []
        for item in cleaned_retrievals:
            key = (item.get("gene"), item.get("target_name"), item.get("type"))
            if key not in seen:
                seen.add(key)
                unique_retrievals.append(item)

        unique_retrievals = sorted(unique_retrievals, key=lambda x: x.get("score", -float('inf')), reverse=True)

        # ---------- Aggregation ----------
        aggregated = Organizer._aggregate_items(candidate_items)

        # Build aggregated text for LLM prompt
        aggregated_text = Organizer._build_aggregated_text(aggregated, genes_data, tumor_type)

        # Generate summary
        llm_summary = Organizer._generate_llm_summary(aggregated_text, tumor_type, query)
        if llm_summary:
            kg_summary = llm_summary
            logger.info("LLM summary generated successfully.")
        else:
            logger.info("LLM summary returned None, falling back to template.")
            kg_summary = Organizer._build_template_summary(aggregated, genes_data)

        return unique_retrievals, kg_summary

    @staticmethod
    def format_context(retrievals):
        """Legacy: kept for compatibility."""
        if not retrievals:
            return "_No relevant medical evidence retrieved._"
        lines = []
        for i, r in enumerate(retrievals, 1):
            score_str = f"{r.get('score', 0):.3f}" if r.get('score') is not None else ""
            source = r.get('source', r.get('type', 'unknown'))
            lines.append(f"{i}. ({source}, relevance {score_str}) {r.get('target_name', '')}")
        return "\n".join(lines)