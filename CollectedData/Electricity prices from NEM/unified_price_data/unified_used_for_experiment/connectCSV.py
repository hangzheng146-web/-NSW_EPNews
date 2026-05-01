import os
import argparse
import pandas as pd


def collect_and_merge_csv(root_dir: str, output_file: str):
    """
    Recursively traverse root_dir, read all .csv files, and merge them into one output CSV.
    """
    all_dfs = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith('.csv'):
                file_path = os.path.join(dirpath, filename)
                try:
                    df = pd.read_csv(file_path)
                    all_dfs.append(df)
                    print(f"Loaded {file_path}, {len(df)} records.")
                except Exception as e:
                    print(f"Failed to read {file_path}: {e}")

    if not all_dfs:
        print("No CSV files found.")
        return

    merged_df = pd.concat(all_dfs, ignore_index=True)
    merged_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"Merged {len(all_dfs)} files into {output_file}, total {len(merged_df)} records.")


def main():
    parser = argparse.ArgumentParser(
        description="Recursively collect and merge all CSV files under a root directory."
    )
    parser.add_argument(
        'root_dir',
        nargs='?',
        default='.',
        help='Root directory to search for CSV files (default: current directory)'
    )
    parser.add_argument(
        '--output', '-o',
        default='2015To2024Data.csv',
        help='Output CSV filename (default: 2015To2024Data.csv)'
    )
    args = parser.parse_args()

    collect_and_merge_csv(args.root_dir, args.output)


if __name__ == '__main__':
    main()
