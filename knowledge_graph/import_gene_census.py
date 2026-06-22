import pandas as pd
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# 1. Connect to Neo4j
uri = "neo4j://127.0.0.1:7687" 
driver = GraphDatabase.driver(uri, auth=("neo4j", "password"), database="db")

print("Loading Sentence Transformer...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded.")

df = pd.read_csv('Cosmic_Gene_Census.tsv', sep='\t', encoding='utf-8')

def import_gene(tx, row):
    gene_symbol = row['Gene Symbol']
    if pd.isna(gene_symbol):
        return
    
    # --- MAPPING CHANGE: name = symbol, full_name = long description ---
    long_name = row['Name'] if pd.notna(row['Name']) else ""
    entrez_id = row['Entrez GeneId'] if pd.notna(row['Entrez GeneId']) else ""
    genome_location = row['Genome Location'] if pd.notna(row['Genome Location']) else ""
    chr_band = row['Chr Band'] if pd.notna(row['Chr Band']) else ""
    hallmark = row['Hallmark'] if pd.notna(row['Hallmark']) else "No"
    
    syn_list = [s.strip() for s in str(row['Synonyms']).split(',') if s.strip()] if pd.notna(row['Synonyms']) else []
    
    # --- Parse multi-value lists ---
    tissue_list = [t.strip() for t in str(row['Tissue Type']).split(',') if t.strip()] if pd.notna(row['Tissue Type']) else []
    role_list = [r.strip() for r in str(row['Role in Cancer']).split(',') if r.strip()] if pd.notna(row['Role in Cancer']) else []
    mut_list = [m.strip() for m in str(row['Mutation Types']).split(',') if m.strip()] if pd.notna(row['Mutation Types']) else []
    partner_list = [p.strip() for p in str(row['Translocation Partner']).split(',') if p.strip()] if pd.notna(row['Translocation Partner']) else []
    cancer_list = [c.strip() for c in str(row['Tumour Types(Somatic)']).split(',') if c.strip()] if pd.notna(row['Tumour Types(Somatic)']) else []
    syndrome_list = [sy.strip() for sy in str(row['Cancer Syndrome']).split(',') if sy.strip()] if pd.notna(row['Cancer Syndrome']) else []
    
    tier_value = str(row['Tier']) if pd.notna(row['Tier']) else ""
    
    # --- Generate Embedding (using the long name for context) ---
    gene_description = f"{gene_symbol} ({long_name}). Tier {tier_value}. Roles: {', '.join(role_list)}. Tissues: {', '.join(tissue_list)}. Associated cancers: {', '.join(cancer_list[:5])}."
    embedding = embedder.encode(gene_description).tolist()
    
    # --- The Cypher Query ---
    query = """
    // 1. Create the Gene node
    // Note: 'name' is set to the symbol so it displays permanently
    MERGE (g:Gene {symbol: $symbol})
    SET g.name = $symbol,           // <-- DISPLAY NAME (shown on graph)
        g.full_name = $full_name,   // <-- Long description (hidden, but stored)
        g.entrez_id = $entrez_id,
        g.genome_location = $genome_location,
        g.chr_band = $chr_band,
        g.synonyms = $synonyms,
        g.hallmark = $hallmark,
        g.embedding = $embedding
    
    // 2. Link to Tier node
    WITH g
    MERGE (tier:Tier {name: $tier})
    MERGE (g)-[:HAS_TIER]->(tier)
    
    // 3. Link to Tissue nodes
    WITH g
    UNWIND $tissues AS tissue_name
    MERGE (t:Tissue {name: tissue_name})
    MERGE (g)-[:HAS_TISSUE]->(t)
    
    // 4. Link to Role nodes
    WITH g
    UNWIND $roles AS role_name
    MERGE (r:Role {name: role_name})
    MERGE (g)-[:HAS_ROLE]->(r)
    
    // 5. Link to MutationType nodes
    WITH g
    UNWIND $mut_types AS mut_name
    MERGE (mt:MutationType {name: mut_name})
    MERGE (g)-[:HAS_MUTATION_TYPE]->(mt)
    
    // 6. Link to Disease nodes
    WITH g
    UNWIND $cancers AS cancer_name
    MERGE (d:Disease {name: cancer_name})
    MERGE (g)-[:ASSOCIATED_WITH]->(d)
    
    // 7. Link to Syndrome nodes
    WITH g
    UNWIND $syndromes AS syndrome_name
    MERGE (s:Syndrome {name: syndrome_name})
    MERGE (g)-[:ASSOCIATED_WITH_SYNDROME]->(s)
    
    // 8. Link to translocation partners
    WITH g
    UNWIND $partners AS partner_symbol
    MERGE (partner:Gene {symbol: partner_symbol})
    MERGE (g)-[:FUSES_WITH]->(partner)
    """
    
    tx.run(query, symbol=gene_symbol, full_name=long_name, 
           entrez_id=entrez_id, genome_location=genome_location,
           chr_band=chr_band, hallmark=hallmark, tier=tier_value,
           tissues=tissue_list, roles=role_list, mut_types=mut_list,
           synonyms=syn_list, partners=partner_list, cancers=cancer_list,
           syndromes=syndrome_list, embedding=embedding)


# 4. Run the import
with driver.session() as session:
    total_rows = len(df)
    for index, row in df.iterrows():
        session.execute_write(import_gene, row)
        if index % 50 == 0:
            print(f"Imported {index}/{total_rows} genes...")

print("Gene Census Import Complete")



driver.close()