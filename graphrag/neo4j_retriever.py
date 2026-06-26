#!/usr/bin/env python3
#Neo4j Retriever fetches rich_description from the knowledge graphs

import os
import logging
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

class Neo4jRetriever:
    def __init__(self):
        self.uri = os.environ.get('NEO4J_URI', 'neo4j://localhost:7687')
        self.user = os.environ.get('NEO4J_USER', 'neo4j')
        self.password = os.environ.get('NEO4J_PASSWORD', 'password')
        self.database = os.environ.get('NEO4J_DATABASE', 'database')
        self.driver = None

        self.citation_threshold = int(os.environ.get('CITATION_THRESHOLD', 3))
        self.max_cancermine_diseases = int(os.environ.get('MAX_CANCERMINE_DISEASES', 10))
        self.max_mutations_per_gene = int(os.environ.get('MAX_MUTATIONS_PER_GENE', 10))

        self.base_hnc_keywords = [
            'head and neck', 'oral', 'tongue', 'larynx', 'pharynx', 'hnscc',
            'squamous cell carcinoma', 'mouth', 'lip', 'gum', 'palate',
            'oropharynx', 'nasopharynx', 'hypopharynx', 'salivary', 'neck'
        ]

    def _get_driver(self):
        if self.driver is None:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self.driver

    def test_connection(self):
        try:
            with self._get_driver().session(database=self.database) as session:
                result = session.run("RETURN 1 AS test")
                record = result.single()
                return record and record['test'] == 1
        except Exception as e:
            logger.error(f"Neo4j connection test failed: {e}")
            return False

    def _is_hnc(self, disease_name, tumor_type=None):
        if not disease_name:
            return False
        name_lower = disease_name.lower()
        keywords = self.base_hnc_keywords.copy()
        if tumor_type:
            keywords.append(tumor_type.lower())
        return any(kw in name_lower for kw in keywords)

    def retrieve_for_genes(self, gene_symbols, tumor_type=None, max_ancestors=3):
        if not gene_symbols:
            return {"genes": []}

        main_query = """
        UNWIND $gene_symbols AS symbol
        MATCH (g:Gene {symbol: symbol})
        OPTIONAL MATCH (g)-[:HAS_ROLE]->(r:Role)
        OPTIONAL MATCH (g)-[:HAS_TISSUE]->(t:Tissue)
        OPTIONAL MATCH (g)-[:HAS_MUTATION_TYPE]->(mt:MutationType)
        OPTIONAL MATCH (g)-[:ASSOCIATED_WITH_SYNDROME]->(sy:Syndrome)
        OPTIONAL MATCH (g)-[:ASSOCIATED_WITH]->(d_g:Disease)
        OPTIONAL MATCH (g)-[cm_rel:IS_ONCOGENE_IN|IS_TUMOR_SUPPRESSOR_IN|IS_DRIVER_IN]->(d_cm:Disease)
        WHERE cm_rel.citations >= $citation_threshold
        WITH g, r, t, mt, sy, d_g, cm_rel, d_cm
        WITH g, r, t, mt, sy, d_g,
             collect(DISTINCT {name: d_cm.name, role: type(cm_rel), citations: cm_rel.citations}) AS cm_all
        OPTIONAL MATCH (g)-[:HAS_MUTATION]->(m:Mutation)
        OPTIONAL MATCH (m)-[:ASSOCIATED_WITH]->(d_m:Disease)
        WITH g,
             collect(DISTINCT r.name) AS roles,
             collect(DISTINCT t.name) AS tissues,
             collect(DISTINCT mt.name) AS mut_types,
             collect(DISTINCT sy.name) AS syndromes,
             collect(DISTINCT d_g.name) AS cosmic_gene_diseases,
             collect(DISTINCT d_m.name) AS cosmic_mutation_diseases,
             cm_all,
             collect(DISTINCT m {
                 aa_change: m.aa_change,
                 clinvar: m.clinvar,
                 cds_change: m.cds_change,
                 rich_description: m.rich_description
             }) AS mutations,
             g.rich_description AS gene_desc
        RETURN g.symbol AS gene_symbol,
               g.rich_description AS gene_desc,
               roles, tissues, mut_types, syndromes, mutations,
               cosmic_gene_diseases,
               cosmic_mutation_diseases,
               cm_all
        """

        results = []
        with self._get_driver().session(database=self.database) as session:
            records = session.run(
                main_query,
                gene_symbols=gene_symbols,
                citation_threshold=self.citation_threshold
            )
            for record in records:
                cosmic_diseases = record["cosmic_gene_diseases"] + record["cosmic_mutation_diseases"]
                cancermine_all = record["cm_all"]

                hnc_diseases = []
                non_hnc_diseases = []
                for cm in cancermine_all:
                    if self._is_hnc(cm.get('name', ''), tumor_type):
                        hnc_diseases.append(cm)
                    else:
                        non_hnc_diseases.append(cm)

                hnc_diseases.sort(key=lambda x: x.get('citations', 0), reverse=True)
                non_hnc_diseases.sort(key=lambda x: x.get('citations', 0), reverse=True)

                cancermine_diseases = (hnc_diseases + non_hnc_diseases)[:self.max_cancermine_diseases]
                disease_names = cosmic_diseases + [cm["name"] for cm in cancermine_diseases if cm and cm.get("name")]

                # Limit mutations to max_mutations_per_gene (sorted by ClinVar pathogenicity)
                mutations = record["mutations"]
                # Sort mutations by ClinVar severity: Pathogenic > Likely Pathogenic > others
                def clinvar_score(clinvar):
                    if not clinvar:
                        return 0
                    c = clinvar.lower()
                    if "pathogenic" in c and "likely" not in c:
                        return 3
                    elif "likely pathogenic" in c:
                        return 2
                    elif "risk" in c:
                        return 1
                    else:
                        return 0
                mutations_sorted = sorted(mutations, key=lambda m: clinvar_score(m.get('clinvar', '')), reverse=True)
                mutations_limited = mutations_sorted[:self.max_mutations_per_gene]

                gene_data = {
                    "symbol": record["gene_symbol"],
                    "gene_desc": record["gene_desc"],
                    "roles": record["roles"],
                    "tissues": record["tissues"],
                    "mutation_types": record["mut_types"],
                    "syndromes": record["syndromes"],
                    "mutations": mutations_limited,
                    "disease_names": disease_names,
                    "cosmic_diseases": cosmic_diseases,
                    "cancermine_diseases": cancermine_diseases,
                }
                results.append(gene_data)

      
        return {"genes": results}

    def close(self):
        if self.driver:
            self.driver.close()