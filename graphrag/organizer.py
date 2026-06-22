

#!/usr/bin/env python3
#Organizer: convert raw Neo4j data into evidence snippets with objective scoring.

import os
import json
import logging

logger = logging.getLogger(__name__)

# Load treatment mapping from external JSON file
TREATMENT_FILE = os.environ.get('TREATMENT_MAP_FILE', 'treatments.json')

def load_treatments():
    try:
        if os.path.exists(TREATMENT_FILE):
            with open(TREATMENT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data)} treatment mappings from {TREATMENT_FILE}")
                return data
    except Exception as e:
        logger.warning(f"Could not load {TREATMENT_FILE}: {e}. Using built-in fallback.")
    return {
        "hnscc": [
            "Surgery (primary resection ± neck dissection)",
            "Radiotherapy (definitive or adjuvant IMRT)",
            "Chemotherapy (cisplatin-based, concurrent with radiation)",
            "Targeted therapy (cetuximab for EGFR-overexpressing tumors)",
            "Immunotherapy (pembrolizumab for recurrent/metastatic PD-L1+ disease)"
        ],
        "head and neck squamous cell carcinoma": [
            "Surgery (primary resection ± neck dissection)",
            "Radiotherapy (definitive or adjuvant IMRT)",
            "Chemotherapy (cisplatin-based, concurrent with radiation)",
            "Targeted therapy (cetuximab for EGFR-overexpressing tumors)",
            "Immunotherapy (pembrolizumab for recurrent/metastatic PD-L1+ disease)"
        ],
        "oral squamous cell carcinoma": [
            "Surgery (wide local excision ± neck dissection)",
            "Radiotherapy (definitive or adjuvant)",
            "Chemotherapy (cisplatin, 5-FU, or carboplatin)",
            "Targeted therapy (cetuximab)",
            "Immunotherapy (pembrolizumab/nivolumab in recurrent/metastatic)"
        ],
        "oral cavity squamous cell carcinoma": [
            "Surgery (wide local excision ± neck dissection)",
            "Radiotherapy (definitive or adjuvant)",
            "Chemotherapy (cisplatin, 5-FU, or carboplatin)",
            "Targeted therapy (cetuximab)",
            "Immunotherapy (pembrolizumab/nivolumab in recurrent/metastatic)"
        ],
        "tongue": [
            "Surgery (partial glossectomy ± neck dissection)",
            "Radiotherapy (definitive or adjuvant)",
            "Chemotherapy (cisplatin-based)",
            "Targeted therapy (cetuximab)"
        ],
        "larynx": [
            "Surgery (partial/total laryngectomy)",
            "Radiotherapy (definitive or adjuvant)",
            "Chemotherapy (cisplatin-based)",
            "Targeted therapy (cetuximab)"
        ],
        "oropharynx": [
            "Surgery (transoral robotic surgery)",
            "Radiotherapy (definitive or adjuvant)",
            "Chemotherapy (cisplatin-based)",
            "Targeted therapy (cetuximab)"
        ],
        "leukoplakia": [
            "Surgical excision (if dysplastic)",
            "Regular surveillance",
            "Smoking/alcohol cessation",
            "Topical retinoids (investigational)"
        ],
        "erythroplakia": [
            "Incisional biopsy and surgical excision",
            "Regular surveillance",
            "Smoking/alcohol cessation"
        ]
    }

TREATMENT_MAP = load_treatments()

def get_treatments_for_disease(disease_name):
    """Lookup treatments using keyword matching (case-insensitive)."""
    if not disease_name:
        return []
    dn_lower = disease_name.lower()
    for key, treatments in TREATMENT_MAP.items():
        if key.lower() in dn_lower or dn_lower in key.lower():
            return treatments
    return []

# ----- Scoring Functions  -----

def score_cosmic_gene():
    """COSMIC Gene Census – Tier 1 by definition."""
    return 1.0

def score_cosmic_mutation(clinvar):
    """Score based on ClinVar pathogenicity (objective)."""
    if not clinvar:
        return 0.5
    clinvar_lower = clinvar.lower()
    if "pathogenic" in clinvar_lower and "likely" not in clinvar_lower:
        return 1.0
    elif "likely pathogenic" in clinvar_lower:
        return 0.8
    elif "risk" in clinvar_lower:
        return 0.7
    elif "benign" in clinvar_lower:
        return 0.2
    else:
        return 0.5

def score_cancermine(citations):
    """Score CancerMine strictly based on citation count."""
    if citations >= 100:
        return 1.0
    elif citations >= 50:
        return 0.85
    elif citations >= 20:
        return 0.70
    elif citations >= 10:
        return 0.55
    elif citations >= 3:
        return 0.40
    else:
        return 0.30

def score_disease_context():
    return 0.6

class Organizer:
    @staticmethod
    def format_retrievals(raw_data, top_k=10):
        """
        Transform raw Neo4j output into list of evidence dicts.
        Limits mutations to top 2 per gene to balance evidence diversity.
        """
        retrievals = []
        genes_data = raw_data.get("genes", [])

        for gene in genes_data:
            symbol = gene.get("symbol", "Unknown")
            roles = gene.get("roles", [])
            tissues = gene.get("tissues", [])
            mut_types = gene.get("mutation_types", [])
            syndromes = gene.get("syndromes", [])
            mutations = gene.get("mutations", [])
            disease_names = gene.get("disease_names", [])
            disease_ancestors = gene.get("disease_ancestors", {})
            cosmic_diseases = gene.get("cosmic_diseases", [])
            cancermine_diseases = gene.get("cancermine_diseases", [])

            # --- 1. Gene evidence (COSMIC) ---
            role_str = ", ".join(roles) if roles else "unknown role"
            tissue_str = ", ".join(tissues) if tissues else "various tissues"
            mut_type_str = ", ".join(mut_types) if mut_types else "various mutation types"
            syndrome_str = ", ".join(syndromes) if syndromes else "none reported"

            content = (f"Gene {symbol} (COSMIC Cancer Gene Census): roles: {role_str}; "
                       f"tissues: {tissue_str}; mutation types: {mut_type_str}; "
                       f"associated syndromes: {syndrome_str}.")
            retrievals.append({
                "content": content,
                "source": "COSMIC-GeneCensus",
                "relevance_score": score_cosmic_gene(),
                "entities": [symbol] + roles + tissues,
                "evidence_level": "Tier 1"
            })

            # --- 2. Mutations (COSMIC)  ---
            # Sort mutations by ClinVar significance (Pathogenic > Likely Pathogenic > others)
            mutations_sorted = sorted(
                mutations,
                key=lambda m: score_cosmic_mutation(m.get('clinvar', '')),
                reverse=True
            )
            
            for mut in mutations_sorted[:2]:
                aa_change = mut.get("aa_change", "unknown")
                clinvar = mut.get("clinvar", "")
                cds = mut.get("cds_change", "")
                mut_content = (f"Mutation {aa_change} in gene {symbol}: "
                               f"CDS change: {cds}; ClinVar significance: {clinvar}.")
                score = score_cosmic_mutation(clinvar)
                ev_level = "Level 1" if score >= 0.9 else "Level 2" if score >= 0.7 else "Level 3"
                retrievals.append({
                    "content": mut_content,
                    "source": "COSMIC-MutationCensus",
                    "relevance_score": score,
                    "entities": [symbol, aa_change],
                    "evidence_level": ev_level
                })

            # --- 3. COSMIC disease associations ---
            for disease_name in cosmic_diseases:
                ancestors = disease_ancestors.get(disease_name, [])
                ancestor_str = " → ".join(ancestors) if ancestors else "no hierarchical context"
                treatments = get_treatments_for_disease(disease_name)
                treatment_str = ", ".join(treatments) if treatments else "specific treatment information not available"
                content = (f"Disease: {disease_name}. "
                           f"HeNeCOn hierarchical context: {ancestor_str}. "
                           f"Associated treatments: {treatment_str}.")
                retrievals.append({
                    "content": content,
                    "source": "COSMIC + HeNeCOn",
                    "relevance_score": score_disease_context(),
                    "entities": [disease_name] + ancestors,
                    "evidence_level": "Clinical"
                })

            # --- 4. CancerMine disease associations ---
            for cm in cancermine_diseases:
                disease_name = cm["name"]
                role = cm["role"]
                citations = cm["citations"]
                role_pretty = {
                    "IS_ONCOGENE_IN": "oncogene",
                    "IS_TUMOR_SUPPRESSOR_IN": "tumor suppressor",
                    "IS_DRIVER_IN": "driver"
                }.get(role, role)

                ancestors = disease_ancestors.get(disease_name, [])
                ancestor_str = " → ".join(ancestors) if ancestors else "no hierarchical context"
                treatments = get_treatments_for_disease(disease_name)
                treatment_str = ", ".join(treatments) if treatments else "specific treatment information not available"

                content = (f"CancerMine (literature-mined): gene {symbol} is reported as a {role_pretty} in {disease_name} "
                           f"({citations} supporting publications). "
                           f"HeNeCOn hierarchical context: {ancestor_str}. "
                           f"Associated treatments: {treatment_str}.")

                score = score_cancermine(citations)

                if score >= 0.85:
                    ev_level = "Level 1"
                elif score >= 0.70:
                    ev_level = "Level 2"
                elif score >= 0.55:
                    ev_level = "Level 3"
                else:
                    ev_level = "Level 4"

                retrievals.append({
                    "content": content,
                    "source": "CancerMine",
                    "relevance_score": round(score, 3),
                    "entities": [symbol, disease_name],
                    "evidence_level": ev_level,
                    "citations": citations
                })

        # Deduplicate by content (keep highest score)
        seen = {}
        for r in retrievals:
            key = r["content"]
            if key not in seen or r["relevance_score"] > seen[key]["relevance_score"]:
                seen[key] = r

        # Sort by relevance score descending and return top_k
        sorted_items = sorted(seen.values(), key=lambda x: x["relevance_score"], reverse=True)
        return sorted_items[:top_k]

    @staticmethod
    def format_context(retrievals):
        """Build the bulleted context string for the orchestrator."""
        if not retrievals:
            return "_No relevant medical evidence retrieved._"
        lines = []
        for i, r in enumerate(retrievals, 1):
            ev = f" [evidence {r['evidence_level']}]" if r.get("evidence_level") else ""
            score_str = f"{r.get('relevance_score', 0):.3f}"
            lines.append(f"{i}. ({r['source']}{ev}, relevance {score_str}) {r['content']}")
        return "\n".join(lines)