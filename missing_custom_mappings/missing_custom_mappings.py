import random
import argparse
import yaml
import pandas as pd
from datetime import datetime
import os
import sys
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
# Memory monitoring imports
import psutil
from pympler import asizeof
import time


def load_config(config_path):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def save_config(config_path, config_data):
    with open(config_path, 'w') as f:
        yaml.dump(config_data, f)


def get_distinct_values(engine, table, column):
    """
    Query only distinct values for the specified column from the database.
    """
    schema, table_name = table.split('.', 1)
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            query = text(f"SELECT DISTINCT {column} FROM {schema}.{table_name} WHERE {column} IS NOT NULL")
            result = conn.execute(query)
            values = [row[0] for row in result]
        return values
    except Exception as e:
        print(f"Error reading distinct values from {table}.{column}: {e}")
        return []


# def get_example_row(engine, table, column, value):
#     """
#     Query the database for a single example row matching the value in the specified column.
#     """
#     # --- ENGINE-BASED APPROACH (commented out) ---
#     schema, table_name = table.split('.', 1)
#     from sqlalchemy import text
#     try:
#         with engine.connect() as conn:
#             query = text(f"SELECT * FROM {schema}.{table_name} WHERE {column} = :val LIMIT 1")
#             result = conn.execute(query, {"val": value})
#             row = result.fetchone()
#             if row:
#                 return dict(row._mapping)
#     except Exception as e:
#         print(f"Warning: Could not get example row for {table}.{column} = {value} from DB: {e}")
#     return {}

    # --- SIMPLER CONNECTION-STRING BASED APPROACH ---
    # import psycopg2
    # schema, table_name = table.split('.', 1)
    # conn_str = os.getenv('PG_CONN_STR', 'dbname=mimic')
    # try:
    #     with psycopg2.connect(conn_str) as conn:
    #         with conn.cursor() as cur:
    #             query = f"SELECT * FROM {schema}.{table_name} WHERE {column} = %s LIMIT 1"
    #             cur.execute(query, (value,))
    #             row = cur.fetchone()
    #             if row:
    #                 colnames = [desc[0] for desc in cur.description]
    #                 return dict(zip(colnames, row))
    # except Exception as e:
    #     print(f"Warning: Could not get example row for {table}.{column} = {value} from DB: {e}")
    # return {}


# def paren_split_match(val_lower, series):
#     """
#     Try to match val_lower against a pandas Series, handling parentheses.
#     Returns (matches, match_type) or (empty DataFrame, None) if no match.
#     """
#     import re
#     paren_match = re.search(r'^(.*)\((.*)\)(.*)$', val_lower)
#     if paren_match:
#         before = paren_match.group(1).strip()
#         inside = paren_match.group(2).strip()
#         after = paren_match.group(3).strip()
#         no_paren = (before + ' ' + after).strip()
#         # Try matching without the parentheses and their contents
#         matches = series[series == no_paren]
#         if len(matches) > 0:
#             return matches, 'no_paren'
#         # Try matching just the inside of the parentheses
#         matches = series[series == inside]
#         if len(matches) > 0:
#             return matches, 'paren_content'
#     else:
#         matches = series[series == val_lower]
#         if len(matches) > 0:
#             return matches, 'direct'
#     return pd.Series(dtype=series.dtype), None

def find_concept_matches(value, filtered_df, synonym_names_set=None, code=False, concept_names_set=None, concept_codes_set=None,
                         concept_names_noparen_set=None):
    """
    Find concept matches, first trying direct matches, then synonyms if no direct match found.

    Args:
        value: The value to search for
        filtered_df: Filtered concept DataFrame
        synonym_df: Concept synonym DataFrame
        code: Boolean indicating if searching by concept_code
        concept_names_set: Set of concept names (lowercase) for fast lookup
        concept_codes_set: Set of concept codes for fast lookup

    Returns:
        tuple: (matches, match_type) where match_type is 'direct' or 'synonym'
    """
    # synonym_names_set is now an explicit argument, precomputed outside this function
    if code:
        value_str = str(value).strip()
        # Strip leading single quote if present (but keep as string to preserve leading zeros)
        if value_str.startswith("'"):
            value_str = value_str[1:]
        # Fast set lookup for direct code match
        if concept_codes_set is not None and value_str in concept_codes_set:
            # Return a dummy match (could be improved to return actual row if needed)
            return pd.DataFrame({'concept_code': [value_str]}), 'direct'
        # If no direct match, try decimal insertion logic
        decimal_positions = [3, 4, 2]
        for pos in decimal_positions:
            if len(value_str) > pos:
                value_with_decimal = value_str[:pos] + '.' + value_str[pos:]
                if concept_codes_set is not None and value_with_decimal in concept_codes_set:
                    return pd.DataFrame({'concept_code': [value_with_decimal]}), f'decimal_pos_{pos}'
        # No match found, run alternate logic if needed (could be extended)
        return pd.DataFrame(), 'none'
    else:
        val_lower = str(value).strip().lower()
        # --- Start timing non-code string matching ---
        # block_begin = time.time()
        # Direct name match block
        if concept_names_set is not None:
            in_names = val_lower in concept_names_set
            if in_names:
                # print(f"[PROFILE] direct name match block for '{val_lower}' took {time.time() - block_begin:.6f} sec: {in_names}")
                return pd.DataFrame({'concept_name_lower': [val_lower]}), 'direct'
        # block_start = time.time()
        # Direct synonym match block
        if synonym_names_set is not None:
            in_synonyms = val_lower in synonym_names_set
            if in_synonyms:
                # print(f"[PROFILE] direct synonym match block for '{val_lower}' took {time.time() - block_start:.6f} sec: {in_synonyms}")
                # Return a dummy match since existence is sufficient
                return pd.DataFrame({'concept_synonym_name': [val_lower]}), 'synonym_direct'
        # block_start = time.time()
        # Parentheses content match block
        import re
        paren_match = re.search(r'^(.*)\((.*)\)$', val_lower)
        if paren_match:
            before = paren_match.group(1).strip()
            inside = paren_match.group(2).strip()
            before_match = concept_names_set is not None and before in concept_names_set
            inside_match = concept_names_set is not None and inside in concept_names_set
            if before_match:
                # print(f"[PROFILE] parentheses content match block for '{val_lower}' took {time.time() - block_start:.6f} sec: before={before_match}")
                # Return a dummy match since existence is sufficient
                return pd.DataFrame({'concept_name_lower': [before]}), 'direct_before_paren'
            if inside_match:
                # print(f"[PROFILE] parentheses content match block for '{val_lower}' took {time.time() - block_start:.6f} sec: inside={inside_match}")
                # Return a dummy match since existence is sufficient
                return pd.DataFrame({'concept_name_lower': [inside]}), 'direct_inside_paren'
        # block_start = time.time()
        # Remove parentheses and match block (optimized with set)
        if concept_names_noparen_set is not None:
            in_noparen = val_lower in concept_names_noparen_set
            if in_noparen:
                # print(f"[PROFILE] remove parentheses match block for '{val_lower}' took {time.time() - block_start:.6f} sec: found={in_noparen}")
                # Return a dummy match since existence is sufficient
                return pd.DataFrame({'concept_name_lower_noparen': [val_lower]}), 'direct_no_paren'
        # block_start = time.time()
       #  print(f"[PROFILE] no match block for '{val_lower}' took {time.time() - block_begin:.6f} sec")
        return pd.DataFrame(), 'none'


def main():
    parser = argparse.ArgumentParser(description="Check BigQuery values against local CSV")
    parser.add_argument('--config', required=True, help='Path to YAML config file')
    parser.add_argument('--concept_table', required=True, help='Path to local CSV file')
    parser.add_argument('--synonym_table', required=True, help='Path to CONCEPT_SYNONYM CSV file')
    parser.add_argument('--output_path', required=True, help='Output CSV path (auto-timestamped if not provided)')
    parser.add_argument('--mode', choices=['all', 'new-only'], default='new-only',
                        help='Process all or only new sources')
    args = parser.parse_args()

    config = load_config(args.config)
    # Build SQLAlchemy connection string for PostgreSQL
    # Example: 'postgresql+psycopg2://user:password@host:port/dbname'
    # Use tunattisdb alias to connect 5432 to 2245
    load_dotenv()
    # db_user = os.getenv('PGUSER', 'your_user')
    # db_pass = os.getenv('PGPASSWORD', 'your_password')
    # db_host = 'localhost'
    # db_port = '5432'
    # db_name = os.getenv('PGDATABASE', 'mimic')
    # engine_str = f'postgresql+psycopg2://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}'
    engine_str = 'postgresql+psycopg2:///mimic'
    from sqlalchemy import create_engine
    # Create a single shared engine for all DB access
    engine = create_engine(engine_str, pool_size=4, max_overflow=2)

    # Load concept table
    local_df = pd.read_csv(args.concept_table, sep='\t')
    local_df = local_df[local_df['invalid_reason'].isna()]  # remove invalid concepts
    # print(
    #     f"[MEM] After loading concept table: {psutil.Process(os.getpid()).memory_info().rss / 1024 ** 3:.2f} GB (local_df: {asizeof.asizeof(local_df) / 1024 ** 3:.2f} GB)")
    # Load synonym table
    print("Loading CONCEPT_SYNONYM table...")
    synonym_df = pd.read_csv(args.synonym_table, sep='\t')
    print(f"Loaded {len(synonym_df)} synonym entries")
    # print(
    #    f"[MEM] After loading synonym table: {psutil.Process(os.getpid()).memory_info().rss / 1024 ** 3:.2f} GB (synonym_df: {asizeof.asizeof(synonym_df) / 1024 ** 3:.2f} GB)")
    # Precompute synonym_names_set once
    synonym_names_set = set(synonym_df['concept_synonym_name'].astype(str).str.lower()) if 'concept_synonym_name' in synonym_df.columns else None
    # Load CONCEPT_RELATIONSHIP table for ICD mapping
    concept_relationship_path = args.synonym_table.replace('CONCEPT_SYNONYM', 'CONCEPT_RELATIONSHIP')
    if os.path.exists(concept_relationship_path):
        print("Loading CONCEPT_RELATIONSHIP table...")
        concept_relationship_df = pd.read_csv(concept_relationship_path, sep='\t')
        print(f"Loaded {len(concept_relationship_df)} concept relationships")
    else:
        concept_relationship_df = None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"missing_custom_concept_names_{timestamp}.csv"
    # Ensure output directory exists and construct file path
    os.makedirs(args.output_path, exist_ok=True)
    output_path = os.path.join(args.output_path, output_name)
    cumulative_output_rows = []

    # Sort sources by table, column, and domain priority (Drug first, then Device, then others)
    def domain_priority(domain_filter):
        # Drug = 0, Device = 1, Other = 2
        if 'Drug' in domain_filter:
            return 0
        elif 'Device' in domain_filter:
            return 1
        return 2

    sources_sorted = sorted(
        config["sources"],
        key=lambda s: (
            s["table"],
            s["column"],
            domain_priority(s.get("domain_filter", []))
        )
    )
    current_table = None
    current_column = None
    values = None

    # Track Drug mismatches for each table/column
    drug_mismatches = {}

    for source in tqdm(sources_sorted):
        # Precompute concept code set for fast lookup if code=True
        # start_time = time.time()
        table = source["table"]
        column = source["column"]
        domain_filter = source.get("domain_filter", [])
        code = source.get("code", False)
        last_checked = source.get("last_checked")
        concept_id_full = source.get("concept_id", "")
        concept_id_no_cdm = concept_id_full.replace("cdm_", "")

        if args.mode == "new-only" and last_checked:
            continue

        # --- Fetch example rows for all distinct values ---
        def get_example_rows_df(engine, table, column, values):
            """
            Fetch a DataFrame with one example row per distinct value in the column.
            The DataFrame will have columns: [missing_value, example_row]
            """
            schema, table_name = table.split('.', 1)
            from sqlalchemy import text
            rows = []
            with engine.connect() as conn:
                # Use DISTINCT ON to get one row per value
                query = text(f"SELECT DISTINCT ON ({column}) {column}, * FROM {schema}.{table_name} WHERE {column} IN :vals AND {column} IS NOT NULL")
                result = conn.execute(query, {"vals": tuple(values)})
                for row in result:
                    val = row._mapping[column]
                    row_dict = dict(row._mapping)
                    # if column in row_dict:
                    #     del row_dict[column]
                    rows.append({"missing_value": val, "example_row": row_dict})
            return pd.DataFrame(rows)

        print(f"Processing {table}.{column}...")

        if table != current_table or column != current_column:
            try:
                values = get_distinct_values(engine, table, column)
                # print(
                #   f"[MEM] After loading distinct values for {table}.{column}: {psutil.Process(os.getpid()).memory_info().rss / 1024 ** 3:.2f} GB")
            except Exception as e:
                print(f"Error querying distinct values for {table}.{column}: {e}")
                values = []
            current_table = table
            current_column = column
            try:
                # Fetch example rows DataFrame
                df_example_rows = get_example_rows_df(engine, table, column, values)
            except Exception as e:
                print(f"Failed to build example rows table for {table}.{column}: {e}")
                sys.exit()
        if not values:
            print(f"No values returned for {table}.{column}. Skipping this source.")
            sys.exit()
            # continue

        if column == 'icd_code' and concept_relationship_df is not None:
            # Get all concepts in the target domain
            if domain_filter:
                domain_concepts_df = local_df[local_df["domain_id"].isin(domain_filter)]
            else:
                domain_concepts_df = local_df

            # Get concepts that map to the target domain via CONCEPT_RELATIONSHIP
            maps_to_df = concept_relationship_df[concept_relationship_df['relationship_id'] == 'Maps to']
            merged_df = pd.merge(local_df, maps_to_df, left_on='concept_id', right_on='concept_id_1', how='inner')
            if domain_filter:
                mapped_concepts_df = merged_df[merged_df["domain_id"].isin(domain_filter)]
            else:
                mapped_concepts_df = merged_df

            # Concatenate and drop duplicates
            filtered_df = pd.concat([domain_concepts_df, mapped_concepts_df], ignore_index=True).drop_duplicates(
                subset=["concept_id"])
            # Profiling: print DataFrame shapes and timing after filtered_df is created
            # if domain_filter:
            #     print(f"[PROFILE] domain_concepts_df shape: {domain_concepts_df.shape}")
            # print(f"[PROFILE] mapped_concepts_df shape: {mapped_concepts_df.shape}")
            # print(f"[PROFILE] filtered_df shape after concat: {filtered_df.shape}")
            # print(f"[PROFILE] Time to build filtered_df for {table}.{column}: {time.time() - start_time:.2f} sec")
        else:
            if domain_filter:
                filtered_df = local_df[local_df["domain_id"].isin(domain_filter)]
            else:
                filtered_df = local_df

            if not code:
                filtered_df = filtered_df.copy()
                filtered_df["concept_name_lower"] = (
                    filtered_df["concept_name"].astype(str).str.lower()
                )
            # Profiling: print DataFrame shape and timing after filtered_df is created
            # print(f"[PROFILE] filtered_df shape: {filtered_df.shape}")
            # print(f"[PROFILE] Time to build filtered_df for {table}.{column}: {time.time() - start_time:.2f} sec")

        # Sample 5% of values for example row fetching
        sample_size = max(1, int(0.05 * len(values))) if values else 0
        sampled_values = set(random.sample(values, sample_size)) if sample_size > 0 else set()

        # Precompute concept_names_set, concept_codes_set, and concept_names_noparen_set once per table/column
        concept_names_set = set(filtered_df["concept_name"].astype(str).str.strip().str.lower())
        concept_codes_set = set(
            filtered_df["concept_code"].astype(str).str.strip()) if "concept_code" in filtered_df.columns else None

        def remove_parentheses(s):
            import re
            return re.sub(r'\s*\([^)]*\)', '', s)

        concept_names_noparen_set = set(
            filtered_df["concept_name"].astype(str).apply(remove_parentheses).str.strip().str.lower()
        ) if filtered_df["concept_name"].astype(str).str.contains(r'\(', regex=True).any() else None

        def process_value(val, table, column, domain_filter, code, concept_id_no_cdm, timestamp, engine):
            if val is None:
                return None
            # start = time.time()
            matches, match_type = find_concept_matches(
                val,
                filtered_df,
                synonym_names_set,
                code,
                concept_names_set,
                concept_codes_set,
                concept_names_noparen_set
            )
            # print(f"[PROFILE] find_concept_matches for value '{val}' took {time.time() - start:.6f} sec (match_type: {match_type})")
            match_count = len(matches)
            if match_count == 0:
                # example_row_dict = None
                # if val in sampled_values:
                #     # t0 = time.time()
                #     example_row_dict = get_example_row(engine, table, column, val)
                #     # t1 = time.time()
                #     # print(f"[PROFILE] get_example_row for {table}.{column} value '{val}' took {t1-t0:.4f} sec")
                return {
                    "missing_value": val,
                    "mimic_table": table,
                    "mimic_column": column,
                    "domain": domain_filter,
                    "code": code,
                    "concept_id": concept_id_no_cdm,
                    "timestamp": timestamp
                }
                # "example_row": example_row_dict

            return None

        # Device domain logic: only report if also a Drug mismatch
        is_drug = 'Drug' in domain_filter
        is_device = 'Device' in domain_filter

        # Collect output rows for this source only
        source_output_rows = []
        if is_drug:
            drug_mismatches_key = f"{table}.{column}"
            if drug_mismatches_key not in drug_mismatches:
                drug_mismatches[drug_mismatches_key] = set()
            results = []
            for val in tqdm(values, desc=f"Processing Drug values for {table}.{column}"):
                result = process_value(val, table, column, domain_filter, code, concept_id_no_cdm, timestamp, engine)
                if result:
                    results.append((result["missing_value"], result))
            for missing_val, result in results:
                source_output_rows.append(result)
                drug_mismatches[drug_mismatches_key].add(missing_val)
            drug_mismatches[drug_mismatches_key] = set(drug_mismatches[drug_mismatches_key])

        elif is_device:
            drug_mismatches_key = f"{table}.{column}"
            device_values = [val for val in values if drug_mismatches.get(drug_mismatches_key) and val in drug_mismatches[drug_mismatches_key]]
            for val in tqdm(device_values, desc=f"Processing Device values for {table}.{column}"):
                result = process_value(val, table, column, domain_filter, code, concept_id_no_cdm, timestamp, engine)
                if result:
                    source_output_rows.append(result)

        else:
            for val in tqdm(values, desc=f"Processing values for {table}.{column}"):
                result = process_value(val, table, column, domain_filter, code, concept_id_no_cdm, timestamp, engine)
                if result:
                    source_output_rows.append(result)

        source["last_checked"] = timestamp

        # Merge example rows for this source only, then append to cumulative output
        if source_output_rows:
            source_output_df = pd.DataFrame(source_output_rows)
            source_output_df = source_output_df.merge(df_example_rows, on="missing_value", how="left", suffixes=("", "_extra"))
            if "missing_value_extra" in source_output_df.columns:
                source_output_df = source_output_df.drop(columns=["missing_value_extra"])
            cumulative_output_rows.append(source_output_df)

    # After all sources processed, concatenate and write output
    if cumulative_output_rows:
        final_output_df = pd.concat(cumulative_output_rows, ignore_index=True)
        final_output_df.to_csv(output_path, index=False)
        print(f"Missing values written to: {output_path}")
    else:
        print("No missing values found.")

    save_config(args.config, config)

if __name__ == "__main__":
    main()
