# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marco Massarelli

# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import re
import sys
import shutil
import argparse

def flatten_folders(downloads_dir):
    print("Flattening folders...")
    
    if not os.path.exists(downloads_dir):
        print(f"Error: {downloads_dir} directory not found.")
        return
        
    # Get children folders (e.g. Byron, Catherine)
    children = [d for d in os.listdir(downloads_dir) if os.path.isdir(os.path.join(downloads_dir, d))]
    
    total_moved = 0
    
    for child in children:
        child_dir = os.path.join(downloads_dir, child)
        print(f"Processing child: {child}")
        
        # Walk through the child's directories and find all media files
        # We need to collect them first to avoid modifying the directory tree while walking
        files_to_move = []
        for root, dirs, files in os.walk(child_dir):
            # Skip the root child directory itself (we want to move files here)
            if root == child_dir:
                continue
            for file in files:
                if file.startswith('.') or file == 'manifest.json':
                    continue
                src_path = os.path.join(root, file)
                dest_path = os.path.join(child_dir, file)
                files_to_move.append((src_path, dest_path))
                
        # Move the files
        for src, dest in files_to_move:
            try:
                # If file already exists in dest, delete the source to clean up duplicates
                if os.path.exists(dest):
                    if os.path.getsize(src) == os.path.getsize(dest):
                        os.remove(src)
                    else:
                        # Append a suffix if sizes differ
                        name, ext = os.path.splitext(dest)
                        shutil.move(src, f"{name}_conflict{ext}")
                else:
                    shutil.move(src, dest)
                total_moved += 1
            except Exception as e:
                print(f"  Error moving {src} to {dest}: {e}")
                
        # Clean up empty directories (removing hidden .DS_Store files first)
        for root, dirs, files in os.walk(child_dir, topdown=False):
            if root == child_dir:
                continue
            try:
                ds_store = os.path.join(root, '.DS_Store')
                if os.path.exists(ds_store):
                    os.remove(ds_store)
                if not os.listdir(root):
                    os.rmdir(root)
            except Exception as e:
                pass
                
    print(f"Successfully flattened {total_moved} files.")

def nest_folders(downloads_dir):
    print("Reverting files back to nested year/month structure...")
    
    if not os.path.exists(downloads_dir):
        print(f"Error: {downloads_dir} directory not found.")
        return
        
    children = [d for d in os.listdir(downloads_dir) if os.path.isdir(os.path.join(downloads_dir, d))]
    
    total_moved = 0
    
    # Matches name like "Byron 2026-02-06 (5).mp4"
    # Group 1: Child name
    # Group 2: Year (4 digits)
    # Group 3: Month (2 digits)
    filename_pattern = re.compile(r'^(.+?)\s+(\d{4})-(\d{2})-\d{2}\s+\(\d+\)\.[a-zA-Z0-9]+$')
    
    for child in children:
        child_dir = os.path.join(downloads_dir, child)
        print(f"Processing child: {child}")
        
        # Scan files directly under the child directory
        files = [f for f in os.listdir(child_dir) if os.path.isfile(os.path.join(child_dir, f))]
        
        for file in files:
            if file.startswith('.') or file == 'manifest.json':
                continue
                
            match = filename_pattern.match(file)
            if not match:
                print(f"  Skipping file (does not match naming convention): {file}")
                continue
                
            year = match.group(2)
            month = match.group(3)
            
            # Target path: downloads/[ChildName]/[YYYY]/[MM]/
            dest_dir = os.path.join(child_dir, year, month)
            os.makedirs(dest_dir, exist_ok=True)
            
            src = os.path.join(child_dir, file)
            dest = os.path.join(dest_dir, file)
            
            try:
                shutil.move(src, dest)
                total_moved += 1
            except Exception as e:
                print(f"  Error nesting {file}: {e}")
                
    print(f"Successfully nested {total_moved} files.")

def main():
    parser = argparse.ArgumentParser(description="Organize child media files (Flatten or Nest)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--flat", action="store_true", help="Flatten files to downloads/[ChildName]/[filename]")
    group.add_argument("--nest", action="store_true", help="Revert files back to downloads/[ChildName]/[YYYY]/[MM]/[filename]")
    
    args = parser.parse_args()
    downloads_dir = "./downloads"
    
    if args.flat:
        flatten_folders(downloads_dir)
    elif args.nest:
        nest_folders(downloads_dir)

if __name__ == '__main__':
    main()
