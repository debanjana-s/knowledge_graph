#!/usr/bin/env python3
"""
Import CancerMine gene-cancer role associations with a citation threshold.
Only imports associations with citation_count >= THRESHOLD.
"""

import os
import csv
import logging
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# Neo4j connection
NEO4J_URI = os.environ.get('NEO4J_URI', 'neo4j://localhost:7687')
NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
NEO4J_DATABASE = os.environ.get('NEO4J_DATABASE', 'db')

# Path to CancerMine TSV
CANCERMINE_FILE = os.environ.get('CANCERMINE_FILE', 'cancermine_collated.tsv')

# Citation threshold - only import associations with citations >= this value
CITATION_THRESHOLD = int(os.environ.get('CANCERMINE_CITATION_THRESHOLD', 4))

# Map role strings to relationship types
ROLE_TO_REL = {
    'Oncogene': 'IS_ONCOGENE_IN',
    'Tumor_Suppressor': 'IS_TUMOR_SUPPRESSOR_IN',
    'Driver': 'IS_DRIVER_IN',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CancerMineImporter:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self.database = NEO4J_DATABASE

    def close(self):
        self.driver.close()

    def create_indexes(self):
        with self.driver.session(database=self.database) as session:
            session.run("CREATE INDEX IF NOT EXISTS FOR (g:Gene) ON (g.symbol)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (d:Disease) ON (d.name)")
            logger.info("Indexes created (or already exist).")

    def import_cancermine(self, file_path):
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return

        rows_processed = 0
        rows_skipped = 0
        rows_imported = 0

        with self.driver.session(database=self.database) as session:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    rows_processed += 1
                    gene = row.get('gene_normalized', '').strip()
                    cancer = row.get('cancer_normalized', '').strip()
                    role = row.get('role', '').strip()
                    citations = row.get('citation_count', '').strip()
                    
                    if not gene or not cancer or not role:
                        rows_skipped += 1
                        continue
                    
                    try:
                        citations = int(float(citations)) if citations else 0
                    except ValueError:
                        citations = 0

                    # Only import if citations meet threshold
                    if citations < CITATION_THRESHOLD:
                        rows_skipped += 1
                        continue

                    rel_type = ROLE_TO_REL.get(role)
                    if rel_type is None:
                        rows_skipped += 1
                        continue

                    query = """
                    MERGE (g:Gene {symbol: $gene})
                    MERGE (d:Disease {name: $cancer})
                    MERGE (g)-[r:%s]->(d)
                    SET r.source = 'CancerMine',
                        r.citations = $citations
                    RETURN g.symbol, d.name, type(r)
                    """ % rel_type

                    result = session.run(query, gene=gene, cancer=cancer, citations=citations)
                    if result.single():
                        rows_imported += 1
                        if rows_imported % 500 == 0:
                            logger.info(f"Imported {rows_imported} associations...")

        logger.info(f"Import complete: {rows_imported} associations imported, {rows_skipped} skipped (citation < {CITATION_THRESHOLD}).")

    def delete_cancermine(self):
        """Delete all CancerMine relationships."""
        with self.driver.session(database=self.database) as session:
            result = session.run("""
                MATCH ()-[r]->()
                WHERE r.source = 'CancerMine'
                DELETE r
                RETURN count(r) AS deleted_rels
            """)
            deleted_rels = result.single()['deleted_rels']
            logger.info(f"Deleted {deleted_rels} CancerMine relationships.")

            # Delete orphan Disease nodes
            result = session.run("""
                MATCH (d:Disease)
                WHERE NOT (d)--()
                DELETE d
                RETURN count(d) AS deleted_diseases
            """)
            deleted_diseases = result.single()['deleted_diseases']
            logger.info(f"Deleted {deleted_diseases} orphan Disease nodes.")


def main():
    importer = CancerMineImporter()
    try:
        importer.create_indexes()
        importer.import_cancermine(CANCERMINE_FILE)
    finally:
        importer.close()


if __name__ == '__main__':
    main()