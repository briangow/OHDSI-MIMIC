#!/usr/bin/env python3
"""
Script to translate CSV data into config.yaml format for missing_custom_mappings.py

Expected CSV columns:
- concept_id: maps to concept_id (with 'cdm_' prefix removed)
- mimic_source_table: maps to table (with full table path)
- mimic_source_column: maps to column
- domain_ids: maps to domain_filter (parsed as comma-separated list)
- code: maps to code (converted to boolean)
- notes: ignored (for reference only)

Output:
- config.yaml file with the same structure as the existing config
"""

import argparse
import csv
import yaml
import re
import pandas as pd
from pathlib import Path


def parse_domain_ids(domain_ids_str):
    """
    Parse domain_ids string into a list, handling various formats.
    
    Args:
        domain_ids_str: String containing domain IDs, possibly with commas, periods, etc.
    
    Returns:
        list: Cleaned list of domain IDs
    """
    if not domain_ids_str or pd.isna(domain_ids_str):
        return []
    
    # Remove trailing punctuation and split by comma
    cleaned = str(domain_ids_str).strip().rstrip('.,')
    
    # Split by comma and clean each item
    domains = [domain.strip() for domain in cleaned.split(',') if domain.strip()]
    
    return domains


def convert_code_to_boolean(code_str):
    """
    Convert code string to boolean.
    
    Args:
        code_str: String representation of boolean ('TRUE', 'FALSE', etc.)
    
    Returns:
        bool: Boolean value
    """
    if not code_str or pd.isna(code_str):
        return False
    
    code_str = str(code_str).strip().upper()
    return code_str in ['TRUE', 'YES', '1', 'T', 'Y']


def build_table_path(table_name):
    """
    Build full table path for MIMIC-IV tables.
    
    Args:
        table_name: Short table name (e.g., 'admissions', 'transfers')
    
    Returns:
        str: Full table path
    """
    # Map of table names to their full paths
    table_mapping = {
        'admissions': 'hosp.admissions',
        'transfers': 'hosp.transfers',
        'services': 'hosp.services',
        'prescriptions': 'hosp.prescriptions',
        'diagnoses_icd': 'hosp.diagnoses_icd',
        'chartevents': 'icu.chartevents',
        'datetimeevents': 'icu.datetimeevents',
        'procedureevents': 'icu.procedureevents',
    }
    
    return table_mapping.get(table_name, f'hosp.{table_name}')


def csv_to_config(csv_path, output_path):
    """
    Convert CSV file to config.yaml format.
    
    Args:
        csv_path: Path to input CSV file
        output_path: Path to output YAML file
    """
    sources = []
    
    with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            # Extract and process each field
            concept_id = row.get('concept_id', '').strip()
            if concept_id.startswith('cdm_'):
                concept_id = concept_id[4:]  # Remove 'cdm_' prefix
            
            mimic_source_table = row.get('mimic_source_table', '').strip()
            mimic_source_column = row.get('mimic_source_column', '').strip()
            domain_ids_str = row.get('domain_ids', '').strip()
            code_str = row.get('code', '').strip()
            
            # Skip rows with missing essential data
            if not concept_id or not mimic_source_table or not mimic_source_column:
                print(f"Warning: Skipping row with missing essential data: {row}")
                continue
            
            # Build the source entry
            source_entry = {
                'concept_id': concept_id,
                'table': build_table_path(mimic_source_table),
                'column': mimic_source_column,
                'domain_filter': parse_domain_ids(domain_ids_str),
                'last_checked': None  # Set to null as requested
            }
            
            # Add code field only if it's True
            code_value = convert_code_to_boolean(code_str)
            if code_value:
                source_entry['code'] = True
            
            sources.append(source_entry)
    
    # Create the config structure
    config = {
        'sources': sources
    }
    
    # Write to YAML file
    with open(output_path, 'w', encoding='utf-8') as yamlfile:
        yaml.dump(config, yamlfile, default_flow_style=False, sort_keys=False)
    
    print(f"Successfully converted {len(sources)} entries to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert CSV file to config.yaml format for missing_custom_mappings.py"
    )
    parser.add_argument(
        '--csv_path', 
        help='Path to input CSV file'
    )
    parser.add_argument(
        '--output', 
        '-o', 
        default='config_generated.yaml',
        help='Output YAML file path (default: config_generated.yaml)'
    )
    
    args = parser.parse_args()
    
    # Validate input file exists
    if not Path(args.csv_path).exists():
        print(f"Error: Input file '{args.csv_path}' does not exist")
        return 1
    
    try:
        csv_to_config(args.csv_path, args.output)
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
