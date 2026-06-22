# 
# Import HeNeCOn 
# 

import os
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

# ---------- CONFIG ----------
URI = "neo4j://127.0.0.1:7687"
DATABASE = "cosmicmutationhenecon"       
OWL_FILE = "HENECON.owl"                 
FORCE_REIMPORT = True                    

driver = GraphDatabase.driver(URI, auth=("neo4j", "password"), database='db')

print("Loading Sentence Transformer...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded.\n")

print(f"Parsing {OWL_FILE} with rdflib...")
g = Graph()
g.parse(OWL_FILE, format="xml")
print(f"Graph loaded: {len(g)} triples.")

# Namespaces
BD2D = Namespace("http://ontology.lst.tfo.upm.es/BD2D/")
OBO = Namespace("http://purl.obolibrary.org/obo/")

# -------------------- HELPER FUNCTIONS --------------------
def get_label(uri):
    for _, _, label in g.triples((uri, RDFS.label, None)):
        return str(label)
    return None

def get_definition(uri):
    for _, _, defn in g.triples((uri, OBO["IAO_0000115"], None)):
        return str(defn)
    return None

def get_superclasses(uri):
    supers = []
    for s, p, o in g.triples((uri, RDFS.subClassOf, None)):
        supers.append(o)
    return supers

def get_class_name(uri):
    iri_str = str(uri)
    if '#' in iri_str:
        return iri_str.split('#')[-1]
    else:
        return iri_str.split('/')[-1]

# -------------------- COLLECT CLASSES --------------------
classes = []
for cls_uri in g.subjects(RDF.type, OWL.Class):
    if cls_uri not in [OWL.Thing, OWL.Class]:
        classes.append(cls_uri)
print(f"Found {len(classes)} class definitions.\n")

# -------------------- DELETE OLD HeNeCOn (if FORCE_REIMPORT) --------------------
def delete_henecon_nodes(tx):
    print("Deleting all existing HeNeCOn nodes and relationships...")
    tx.run("MATCH (n:HeNeCOnClass) DETACH DELETE n")
    tx.run("MATCH (n:ObjectProperty) DETACH DELETE n")
    tx.run("MATCH (n:DatatypeProperty) DETACH DELETE n")
    print("HeNeCOn nodes deleted.")

# -------------------- IMPORT CLASSES (with placeholder embedding) --------------------
def import_classes(tx):
    print("Creating HeNeCOn class nodes...")
    count = 0
    for cls_uri in classes:
        iri = str(cls_uri)
        name = get_class_name(cls_uri)
        label = get_label(cls_uri)
        definition = get_definition(cls_uri)

        # Use a dummy embedding (will be replaced later)
        dummy_emb = [0.0] * 384
        query = """
        MERGE (c:HeNeCOnClass {iri: $iri})
        SET c.name = $name,
            c.label = $label,
            c.definition = $definition,
            c.embedding = $dummy_emb
        """
        tx.run(query, iri=iri, name=name, label=label, definition=definition, dummy_emb=dummy_emb)
        count += 1
        if count % 200 == 0:
            print(f"  Imported {count} classes...")
    print(f"Class nodes created: {count}")

# -------------------- IMPORT SUBCLASS HIERARCHY --------------------
def import_subclass_relationships(tx):
    print("Creating SUBCLASS_OF relationships...")
    # Collect all superclass IRIs
    all_super_iris = set()
    for cls_uri in classes:
        for parent in get_superclasses(cls_uri):
            all_super_iris.add(str(parent))
    print(f"Found {len(all_super_iris)} unique superclass IRIs.")

    # Placeholder nodes for external superclasses
    for iri in all_super_iris:
        result = tx.run("MATCH (n {iri: $iri}) RETURN n", iri=iri).single()
        if not result:
            name = get_class_name(URIRef(iri))
            tx.run("""
            MERGE (n:HeNeCOnClass:External {iri: $iri})
            SET n.name = $name,
                n.external = true
            """, iri=iri, name=name)

    # Create edges
    edge_count = 0
    for cls_uri in classes:
        child_iri = str(cls_uri)
        for parent_uri in get_superclasses(cls_uri):
            parent_iri = str(parent_uri)
            query = """
            MATCH (child {iri: $child_iri})
            MATCH (parent {iri: $parent_iri})
            MERGE (child)-[:SUBCLASS_OF]->(parent)
            """
            tx.run(query, child_iri=child_iri, parent_iri=parent_iri)
            edge_count += 1
    print(f"Subclass relationships created: {edge_count}")

# -------------------- GENERATE RICH EMBEDDINGS --------------------
def get_ancestors(tx, iri):
    query = """
    MATCH (c:HeNeCOnClass {iri: $iri})
    MATCH (c)-[:SUBCLASS_OF*1..5]->(ancestor)
    RETURN collect(DISTINCT ancestor.name)[0..5] AS ancestors
    """
    result = tx.run(query, iri=iri).single()
    return result['ancestors'] if result else []

def generate_rich_embeddings(tx):
    print("Generating rich embeddings for HeNeCOn classes...")
    query = """
    MATCH (h:HeNeCOnClass)
    RETURN h.iri AS iri, h.name AS name, h.label AS label, h.definition AS definition
    """
    result = tx.run(query)
    updated = 0
    for record in result:
        iri = record['iri']
        name = record['name']
        label = record['label'] or ""
        definition = record['definition'] or ""

        # 1. Get ancestors
        ancestors = get_ancestors(tx, iri)

        # 2. Extract module from IRI
        if '#' in iri:
            module = iri.split('/')[-1].split('#')[0]
        else:
            module = iri.split('/')[-1]

        module_domain = {
            'img': 'Imaging',
            'patho': 'Pathology',
            'risk': 'Risk Factors',
            'ctn': 'Tumor Characterization',
            'tox': 'Treatment Toxicity',
            'surge': 'Surgery',
            'radio': 'Radiotherapy',
            'chemo': 'Chemotherapy',
            'follow': 'Follow-up',
            'qol': 'Quality of Life',
            'genomic': 'Genomics',
            'genes': 'Genes',
            'clinical': 'Clinical Data',
            'radiomri': 'Radiomics',
            'BD2D': 'Core HeNeCOn',
            'PS': 'Population Study',
            'HRS': 'High Resolution Study',
        }.get(module, module)

        # 3. Build description
        parts = []
        if label and label != name:
            parts.append(f"{name} ({label})")
        else:
            parts.append(name)

        if module_domain:
            parts.append(f"Domain: {module_domain}")

        if definition:
            parts.append(f"Definition: {definition[:150]}")

        if ancestors:
            parts.append(f"Ancestors: {' → '.join(ancestors)}")

        description = " – ".join(parts)

        # 4. Generate embedding
        embedding = embedder.encode(description).tolist()

        # 5. Update node
        tx.run("""
            MATCH (h:HeNeCOnClass {iri: $iri})
            SET h.embedding = $embedding,
                h.rich_description = $description
        """, iri=iri, embedding=embedding, description=description)

        updated += 1
        if updated % 100 == 0:
            print(f"  Updated {updated} classes...")

    return updated

# -------------------- MAIN EXECUTION --------------------
with driver.session() as session:
    # Check if HeNeCOn nodes exist
    result = session.run("MATCH (h:HeNeCOnClass) RETURN count(h) AS cnt").single()
    existing = result['cnt'] if result else 0

    if existing == 0 or FORCE_REIMPORT:
        if existing > 0:
            print(f"FORCE_REIMPORT is True. Deleting {existing} existing HeNeCOn nodes.")
            session.execute_write(delete_henecon_nodes)
        else:
            print("No HeNeCOn nodes found. Proceeding with import.")
        # Import
        session.execute_write(import_classes)
        session.execute_write(import_subclass_relationships)
    else:
        print(f"HeNeCOn nodes already exist ({existing} classes). Skipping import.")

    # Always (re)generate rich embeddings
    print("\nGenerating rich embeddings for HeNeCOn classes...")
    count = session.execute_write(generate_rich_embeddings)
    print(f" Updated embeddings for {count} HeNeCOn classes.")

    # Create indexes
    session.run("CREATE INDEX IF NOT EXISTS FOR (n:HeNeCOnClass) ON (n.iri)")
    session.run("CREATE INDEX IF NOT EXISTS FOR (n:HeNeCOnClass) ON (n.name)")
    print("Indexes created.")

print("\n===== HeNeCOn import + rich embeddings complete =====")
driver.close()