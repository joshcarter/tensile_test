#!/usr/bin/env python3
"""
One-time conversion script to convert data/data.csv from old format to new format.
Removes "extrusion width", "layer height", and "printer" columns and adds a "notes" column
containing key=value pairs separated by semicolons from those removed columns.
"""

import csv
import os
import shutil


def convert_csv():
    csv_path = "data/data.csv"
    backup_path = "data/data.csv.backup"
    
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} does not exist")
        return False
    
    # Create backup
    shutil.copy2(csv_path, backup_path)
    print(f"Created backup: {backup_path}")
    
    # Read existing data
    rows = []
    with open(csv_path, newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            rows.append(row)
    
    print(f"Read {len(rows)} rows from existing CSV")
    
    # Convert to new format
    new_fieldnames = [
        "brand", "material type", "color",
        "xy strength (Mpa)", "z strength (Mpa)", "notes"
    ]
    
    converted_rows = []
    for row in rows:
        # Create notes string with key=value pairs from old columns
        notes_parts = []
        
        # Only add non-empty values
        if row.get("extrusion width") and row["extrusion width"].strip():
            notes_parts.append(f"extrusion_width={row['extrusion width'].strip()}")
        
        if row.get("layer height") and row["layer height"].strip():
            notes_parts.append(f"layer_height={row['layer height'].strip()}")
        
        if row.get("printer") and row["printer"].strip():
            notes_parts.append(f"printer={row['printer'].strip()}")
        
        # Join with semicolons
        notes_str = ";".join(notes_parts)
        
        # Create new row
        new_row = {
            "brand": row.get("brand", ""),
            "material type": row.get("material type", ""),
            "color": row.get("color", ""),
            "xy strength (Mpa)": row.get("xy strength (Mpa)", ""),
            "z strength (Mpa)": row.get("z strength (Mpa)", ""),
            "notes": notes_str
        }
        
        converted_rows.append(new_row)
    
    # Write converted data
    with open(csv_path, "w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(converted_rows)
    
    print(f"Converted and saved {len(converted_rows)} rows to new format")
    print("Conversion completed successfully!")
    
    # Show sample of converted data
    print("\nSample of converted data:")
    print("-" * 80)
    for i, row in enumerate(converted_rows[:3]):  # Show first 3 rows
        print(f"Row {i+1}:")
        print(f"  Brand: {row['brand']}")
        print(f"  Material: {row['material type']}")
        print(f"  Color: {row['color']}")
        print(f"  XY Strength: {row['xy strength (Mpa)']}")
        print(f"  Z Strength: {row['z strength (Mpa)']}")
        print(f"  Notes: {row['notes']}")
        print()
    
    return True


if __name__ == "__main__":
    success = convert_csv()
    exit(0 if success else 1)