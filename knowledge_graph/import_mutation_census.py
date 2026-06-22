import pandas as pd
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# 1. Connect to Neo4j 
uri = "neo4j://127.0.0.1:7687" 
driver = GraphDatabase.driver(uri, auth=("neo4j", "password"))

# 2. Load the Sentence Transformer (same model as before)
print("Loading Sentence Transformer...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded.")

# 3. Read the Mutation Census

df = pd.read_csv('Cosmic_Mutation_Census.tsv', sep='\t', encoding='utf-8')

print(f"Loaded {len(df)} mutation records. Processing...")

def import_mutation(tx, row):
    gene_name = row['GENE_NAME']
    if pd.isna(gene_name):
        return
    
    # Extract mutation details
    aa_change = row['Mutation AA'] if pd.notna(row['Mutation AA']) else ""
    cds_change = row['Mutation CDS'] if pd.notna(row['Mutation CDS']) else ""
    
    # Clinical significance and pathogenicity (key for pruning later)
    clinvar = row['CLINVAR_CLNSIG'] if pd.notna(row['CLINVAR_CLNSIG']) else ""
    dnds_sig = row['DNDS_DISEASE_QVAL_SIG'] if pd.notna(row['DNDS_DISEASE_QVAL_SIG']) else ""
    
    # Extract associated diseases 
    disease_raw = row['DISEASE'] if pd.notna(row['DISEASE']) else ""
    disease_list = []
    if disease_raw:
        disease_list = [d.strip() for d in str(disease_raw).split(',') if d.strip()]
    
    # --- Generate a REAL embedding for the mutation ---
    # Create a descriptive text that captures the mutation's context
    mutation_description = f"Mutation {aa_change} in gene {gene_name}. CDS change: {cds_change}. Clinical significance: {clinvar}. Associated diseases: {', '.join(disease_list[:3])}."
    embedding = embedder.encode(mutation_description).tolist()
    
    # Cypher Query: 
    # 1. Finds the existing Gene node (from the Gene Census import)
    # 2. Creates the Mutation node with its embedding
    # 3. Links Gene -> Mutation
    # 4. Links Mutation -> Disease (if disease is specified)
    query = """
    // Find the existing Gene node
    MATCH (g:Gene {symbol: $gene})
    
    // Create the Mutation node
    MERGE (m:Mutation {aa_change: $aa_change})
    SET m.cds_change = $cds_change,
        m.clinvar = $clinvar,
        m.dnds_sig = $dnds_sig,
        m.embedding = $embedding,
        m.description = $description
    
    // Link Gene to Mutation
    MERGE (g)-[:HAS_MUTATION]->(m)
    
    // If this mutation has associated diseases, link them too
    WITH m
    UNWIND $diseases AS disease_name
    MERGE (d:Disease {name: disease_name})
    MERGE (m)-[:ASSOCIATED_WITH]->(d)
    """
    
    tx.run(query, 
           gene=gene_name, 
           aa_change=aa_change, 
           cds_change=cds_change,
           clinvar=clinvar,
           dnds_sig=dnds_sig,
           embedding=embedding,
           description=mutation_description,
           diseases=disease_list)

# 4. Execute the import
with driver.session() as session:
    total_rows = len(df)
    for index, row in df.iterrows():
        session.execute_write(import_mutation, row)
        if index % 100 == 0:
            print(f"Processed {index}/{total_rows} mutations...")

print("Mutation import complete. All mutations are now linked to genes.")
driver.close()